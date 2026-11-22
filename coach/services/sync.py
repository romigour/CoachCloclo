"""Synchro Garmin : import des activités, séances manquées, proposition (rattachement manuel uniquement)."""

from datetime import date, datetime, timedelta

from pydantic import BaseModel
from sqlmodel import select

from coach.analysis.compliance import mark_missed
from coach.analysis.zones import Zones
from coach.garmin.port import GarminPort
from coach.llm.provider import LLMProvider
from coach.plan.models import Activity, Cycle, Session
from coach.plan.repo import Repo
from coach.services.activities import store_summaries
from coach.services.adjust import ask_adjustment, save_proposal
from coach.services.context import refresh_snapshot
from coach.services.cycles import close_passed
from coach.services.garmin_export import retry_pending_cleanup
from coach.services.history import refresh_records
from coach.services.laps import fetch_missing_laps

FIRST_SYNC_DAYS = 56
OVERLAP_DAYS = 2


SYNC_KEY = "sync"


class SyncState(BaseModel):
    last_sync_at: datetime | None = None
    proposal_due: bool = False
    # séances rattachées à la main depuis la dernière proposition : transmises à Claude à la synchro suivante
    pending_done: list[int] = []


def load_sync_state(repo: Repo) -> SyncState:
    raw = repo.get_state(SYNC_KEY)
    if raw is None:
        return SyncState()
    try:
        return SyncState.model_validate(raw)
    except ValueError:
        return SyncState()


def save_sync_state(repo: Repo, s: SyncState) -> None:
    repo.set_state(SYNC_KEY, s.model_dump(mode="json"))


def add_pending_done(repo: Repo, session_id: int) -> None:
    """Met une séance rattachée à la main en attente d'analyse par Claude (sans doublon)."""
    s = load_sync_state(repo)
    if session_id not in s.pending_done:
        s.pending_done.append(session_id)
        save_sync_state(repo, s)


def remove_pending_done(repo: Repo, session_id: int) -> None:
    """Retire une séance de l'attente d'analyse (détachée avant la synchro)."""
    s = load_sync_state(repo)
    if session_id in s.pending_done:
        s.pending_done.remove(session_id)
        save_sync_state(repo, s)


class SyncResult(BaseModel):
    new_activities: int
    missed: int
    proposal_id: int | None


def _attached_done(repo: Repo, sessions: list[Session], ids: list[int]) -> list[int]:
    """Ids de `ids` encore réalisés dans `sessions` avec une activité rattachée, dans l'ordre d'origine."""
    by_id = {s.id: s for s in sessions}
    with repo.transaction() as db:
        attached = {
            a.session_id
            for a in db.exec(select(Activity).where(Activity.session_id.in_(ids))).all()  # type: ignore[union-attr]
        } if ids else set()
    return [i for i in ids if i in by_id and by_id[i].status == "done" and i in attached]


def sync(repo: Repo, garmin: GarminPort, llm: LLMProvider, *, now: datetime) -> SyncResult:
    """Importe, marque les séances manquées, clôt objectifs et cycle passés, puis propose un ajustement.

    La synchro ne rattache jamais d'activité : les séances rattachées à la main depuis la dernière
    proposition (`pending_done`) sont transmises à Claude comme réalisées."""
    _, zones = refresh_snapshot(repo, garmin)
    today = garmin.today()
    settings = load_sync_state(repo)
    if settings.last_sync_at is not None:
        since = settings.last_sync_at.date() - timedelta(days=OVERLAP_DAYS)
    else:
        since = today - timedelta(days=FIRST_SYNC_DAYS)

    new_activities = store_summaries(repo, garmin.activities(since, today))
    refresh_records(repo, garmin)

    cycle = repo.active_cycle()
    done_ids: list[int] = []
    missed_ids: list[int] = []
    if cycle is not None:
        sessions = repo.sessions(cycle.id)
        done_ids = _attached_done(repo, sessions, settings.pending_done)
        missed_ids = mark_missed(sessions, cycle, today)
        with repo.transaction() as db:
            for sid in missed_ids:
                s = db.get(Session, sid)
                s.status = "missed"
                db.add(s)
        fetch_missing_laps(repo, garmin)

    # après le rattachement (la séance du jour de course reste rattachable) et avant la proposition
    if close_passed(repo, today):
        cycle = None  # cycle clos : plus de proposition jusqu'au cycle suivant
    # retraits Garmin restés en échec, y compris ceux d'un cycle terminé (plus affiché)
    retry_pending_cleanup(repo, garmin, today)

    settings.last_sync_at = now
    settings.proposal_due = cycle is not None and (settings.proposal_due or bool(done_ids or missed_ids))
    # séances disparues ou plus réalisées abandonnées ; cycle clos : plus rien à analyser
    settings.pending_done = done_ids if cycle is not None else []
    save_sync_state(repo, settings)

    proposal_id = None
    # arrêt en cours : pas de proposition ; `proposal_due` reste vrai jusqu'à la reprise ou la suppression
    if (
        cycle is not None
        and cycle.plan_accepted
        and settings.proposal_due
        and repo.open_injury(cycle.id) is None
    ):
        proposal_id = _propose(repo, garmin, llm, cycle, zones, done_ids, missed_ids, today)
        settings.proposal_due = False
        settings.pending_done = []
        save_sync_state(repo, settings)
    return SyncResult(
        new_activities=new_activities,
        missed=len(missed_ids),
        proposal_id=proposal_id,
    )


def _propose(
    repo: Repo,
    garmin: GarminPort,
    llm: LLMProvider,
    cycle: Cycle,
    zones: Zones,
    done_ids: list[int],
    missed_ids: list[int],
    today: date,
) -> int:
    """Demande l'ajustement à Claude et enregistre la Proposal (l'ancienne passe `stale`)."""
    sessions = repo.sessions(cycle.id)
    by_id = {s.id: s for s in sessions}
    with repo.transaction() as db:
        acts = {
            a.session_id: a
            for a in db.exec(select(Activity).where(Activity.session_id.in_(done_ids))).all()  # type: ignore[union-attr]
        } if done_ids else {}
    done = [(by_id[sid], acts[sid]) for sid in done_ids]
    missed = [by_id[sid] for sid in missed_ids]
    adj = ask_adjustment(
        repo, garmin, llm, cycle, zones, sessions, today, done=done, missed=missed
    )
    with repo.transaction() as db:
        return save_proposal(db, adj, cycle.adjust_notes())
