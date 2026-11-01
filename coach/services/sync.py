"""Synchro Garmin : import des activités, rattachement, séances manquées, proposition."""

import json
from datetime import date, datetime, timedelta

from pydantic import BaseModel
from sqlmodel import select

from coach.analysis.compliance import mark_missed, match_activities
from coach.analysis.zones import Zones
from coach.config import load_settings, save_settings
from coach.garmin.port import GarminPort
from coach.llm.client import ask_structured
from coach.llm.prompts import SYSTEM_PROMPT, build_adjustment_prompt
from coach.llm.provider import LLMProvider
from coach.llm.schemas import AdjustmentResponse, validate_adjustment
from coach.plan.calendar import week_of
from coach.plan.models import Activity, Goal, Proposal, Session
from coach.plan.repo import Repo
from coach.services.activities import store_summaries
from coach.services.context import recent_history, refresh_snapshot
from coach.services.history import refresh_records
from coach.services.race_strategy import race_line_for_prompt

FIRST_SYNC_DAYS = 56
OVERLAP_DAYS = 2


class SyncResult(BaseModel):
    new_activities: int
    matched: int
    missed: int
    proposal_id: int | None


def sync(repo: Repo, garmin: GarminPort, llm: LLMProvider, *, now: datetime) -> SyncResult:
    """Importe, rattache, marque les séances manquées, puis propose un ajustement."""
    _, zones = refresh_snapshot(repo, garmin)
    today = garmin.today()
    settings = load_settings()
    if settings.last_sync_at is not None:
        since = settings.last_sync_at.date() - timedelta(days=OVERLAP_DAYS)
    else:
        since = today - timedelta(days=FIRST_SYNC_DAYS)

    new_activities = store_summaries(repo, garmin.activities(since, today))
    refresh_records(repo, garmin)

    goal = repo.active_goal()
    pairs: list[tuple[int, int]] = []
    missed_ids: list[int] = []
    if goal is not None:
        sessions = repo.sessions(goal.id)
        pairs = match_activities(sessions, repo.activities_since(since))
        matched = {sid for sid, _ in pairs}
        missed_ids = mark_missed([s for s in sessions if s.id not in matched], goal, today)
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

    settings.last_sync_at = now
    if pairs or missed_ids:
        settings.proposal_due = True
    save_settings(settings)

    proposal_id = None
    if goal is not None and goal.plan_accepted and settings.proposal_due:
        proposal_id = _propose(repo, garmin, llm, goal, zones, pairs, missed_ids, today)
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
    goal: Goal,
    zones: Zones,
    pairs: list[tuple[int, int]],
    missed_ids: list[int],
    today: date,
) -> int:
    """Demande l'ajustement à Claude et enregistre la Proposal (l'ancienne passe `stale`)."""
    sessions = repo.sessions(goal.id)
    by_id = {s.id: s for s in sessions}
    with repo.transaction() as db:
        acts = {aid: db.get(Activity, aid) for _, aid in pairs}
    done = [(by_id[sid], acts[aid]) for sid, aid in pairs]
    missed = [by_id[sid] for sid in missed_ids]
    current_week = week_of(goal, today)
    upcoming = [s for s in sessions if s.status in ("todo", "exported") and s.week_index >= current_week]
    counts: dict[int, int] = {}
    for s in (x for x in sessions if not x.pending_removal):
        counts[s.week_index] = counts.get(s.week_index, 0) + 1
    editable = {s.id for s in upcoming}
    week_of_session = {s.id: s.week_index for s in sessions}
    pace_available = zones.pace is not None

    prompt = build_adjustment_prompt(
        goal, zones, current_week, done, missed, upcoming, recent_history(garmin),
        race_text=race_line_for_prompt(repo, goal, today),
    )
    adj = ask_structured(
        llm,
        SYSTEM_PROMPT,
        prompt,
        AdjustmentResponse,
        validate=lambda a: validate_adjustment(
            a,
            editable_ids=editable,
            current_week=current_week,
            sessions_per_week=goal.sessions_per_week,
            counts_by_week=counts,
            pace_available=pace_available,
            week_of_session=week_of_session,
            exported_ids={s.id for s in upcoming if s.status == "exported"},
        ),
    )
    with repo.transaction() as db:
        for old in db.exec(select(Proposal).where(Proposal.status == "pending")).all():
            old.status = "stale"
            db.add(old)
        proposal = Proposal(
            analysis=adj.analysis,
            changes_json=json.dumps([c.model_dump() for c in adj.changes]),
        )
        db.add(proposal)
        db.flush()
        return proposal.id
