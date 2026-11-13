"""Synchro Garmin : import des activités, rattachement, séances manquées, proposition."""

from datetime import date, datetime, timedelta

from pydantic import BaseModel

from coach.analysis.compliance import mark_missed, match_activities
from coach.analysis.zones import Zones
from coach.config import load_settings, save_settings
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


class SyncResult(BaseModel):
    new_activities: int
    matched: int
    missed: int
    proposal_id: int | None


def sync(repo: Repo, garmin: GarminPort, llm: LLMProvider, *, now: datetime) -> SyncResult:
    """Importe, rattache, marque les séances manquées, clôt objectifs et cycle passés, puis propose un ajustement."""
    _, zones = refresh_snapshot(repo, garmin)
    today = garmin.today()
    settings = load_settings()
    if settings.last_sync_at is not None:
        since = settings.last_sync_at.date() - timedelta(days=OVERLAP_DAYS)
    else:
        since = today - timedelta(days=FIRST_SYNC_DAYS)

    new_activities = store_summaries(repo, garmin.activities(since, today))
    refresh_records(repo, garmin)

    cycle = repo.active_cycle()
    pairs: list[tuple[int, int]] = []
    missed_ids: list[int] = []
    if cycle is not None:
        sessions = repo.sessions(cycle.id)
        pairs = match_activities(sessions, repo.activities_since(since))
        matched = {sid for sid, _ in pairs}
        missed_ids = mark_missed([s for s in sessions if s.id not in matched], cycle, today)
        with repo.transaction() as db:
            for sid, aid in pairs:
                s = db.get(Session, sid)
                s.status = "done"
                db.add(s)
                a = db.get(Activity, aid)
                a.session_id = sid
                a.match_source = "auto"
                db.add(a)
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
    settings.proposal_due = cycle is not None and (settings.proposal_due or bool(pairs or missed_ids))
    save_settings(settings)

    proposal_id = None
    # arrêt en cours : pas de proposition ; `proposal_due` reste vrai jusqu'à la reprise ou la suppression
    if (
        cycle is not None
        and cycle.plan_accepted
        and settings.proposal_due
        and repo.open_injury(cycle.id) is None
    ):
        proposal_id = _propose(repo, garmin, llm, cycle, zones, pairs, missed_ids, today)
        settings.proposal_due = False
        save_settings(settings)
    return SyncResult(
        new_activities=new_activities,
        matched=len(pairs),
        missed=len(missed_ids),
        proposal_id=proposal_id,
    )


def _propose(
    repo: Repo,
    garmin: GarminPort,
    llm: LLMProvider,
    cycle: Cycle,
    zones: Zones,
    pairs: list[tuple[int, int]],
    missed_ids: list[int],
    today: date,
) -> int:
    """Demande l'ajustement à Claude et enregistre la Proposal (l'ancienne passe `stale`)."""
    sessions = repo.sessions(cycle.id)
    by_id = {s.id: s for s in sessions}
    with repo.transaction() as db:
        acts = {aid: db.get(Activity, aid) for _, aid in pairs}
    done = [(by_id[sid], acts[aid]) for sid, aid in pairs]
    missed = [by_id[sid] for sid in missed_ids]
    adj = ask_adjustment(
        repo, garmin, llm, cycle, zones, sessions, today, done=done, missed=missed
    )
    with repo.transaction() as db:
        return save_proposal(db, adj)
