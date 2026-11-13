"""Demande d'ajustement du plan à Claude et enregistrement de la proposition."""

import json
from datetime import date

from sqlmodel import Session as DbSession, select

from coach.analysis.laps import StepComparison
from coach.analysis.zones import Zones
from coach.config import load_settings, save_settings
from coach.garmin.port import GarminPort
from coach.llm.client import ask_structured
from coach.llm.prompts import SYSTEM_PROMPT, build_adjustment_prompt
from coach.llm.provider import LLMProvider
from coach.llm.schemas import AdjustmentResponse, validate_adjustment
from coach.plan.calendar import n_weeks, week_of
from coach.plan.constraints import constraint_errors, planned_after_adjustment
from coach.plan.models import Activity, Cycle, Goal, Proposal, Session
from coach.plan.repo import Repo
from coach.services.context import load_constraints, recent_history, refresh_snapshot
from coach.services.laps import session_comparison
from coach.services.race_strategy import race_line_for_prompt


def ask_adjustment(
    repo: Repo,
    garmin: GarminPort,
    llm: LLMProvider,
    cycle: Cycle,
    zones: Zones,
    sessions: list[Session],
    today: date,
    *,
    done: list[tuple[Session, Activity]] = (),
    missed: list[Session] = (),
    change_note: str | None = None,
    goals: list[Goal] | None = None,
    horizon: list[Goal] | None = None,
) -> AdjustmentResponse:
    """Demande l'ajustement à Claude ; n'écrit rien.

    `cycle` peut être une copie non enregistrée. Les objectifs sont lus dans le dépôt (`goals_in`,
    `horizon_goals`), sauf si `goals` est fourni (objectifs du cycle, parmi lesquels une copie
    modifiée non enregistrée) ; de même `horizon` remplace les objectifs au-delà du cycle.
    """
    if goals is None:
        goals = repo.goals_in(cycle)
    if not goals:
        from coach.services.goals import GoalError  # import tardif : goals importe ce module

        raise GoalError("Le cycle n'a aucun objectif à venir")
    if horizon is None:
        # un objectif transmis dans `goals` (copie modifiée) n'est pas aussi à l'horizon à son ancienne date
        in_cycle = {g.id for g in goals}
        horizon = [g for g in repo.horizon_goals(cycle) if g.id not in in_cycle]
    current_week = week_of(cycle, today)
    upcoming = [s for s in sessions if s.status in ("todo", "exported") and s.week_index >= current_week]
    counts: dict[int, int] = {}
    for s in (x for x in sessions if not x.pending_removal):
        counts[s.week_index] = counts.get(s.week_index, 0) + 1
    # séances figées (ni à faire ni exportées), comptées par semaine pour la règle de semaine allégée
    fixed_counts: dict[int, int] = {}
    for s in sessions:
        if s.status not in ("todo", "exported") and not s.pending_removal:
            fixed_counts[s.week_index] = fixed_counts.get(s.week_index, 0) + 1
    constraints = load_constraints(repo, cycle, today)
    editable = {s.id for s in upcoming}
    week_of_session = {s.id: s.week_index for s in sessions}

    comparisons = {}
    for s, _ in done:
        comparison = session_comparison(repo, s, zones)
        if isinstance(comparison, StepComparison):
            comparisons[s.id] = comparison
    race_texts = [t for g in goals if (t := race_line_for_prompt(repo, g, today))]
    prompt = build_adjustment_prompt(
        cycle, goals, horizon, zones, current_week, list(done), list(missed), upcoming, recent_history(garmin),
        comparisons,
        race_texts=race_texts,
        change_note=change_note,
        constraints=constraints,
    )
    return ask_structured(
        llm,
        SYSTEM_PROMPT,
        prompt,
        AdjustmentResponse,
        validate=lambda a: validate_adjustment(
            a,
            editable_ids=editable,
            current_week=current_week,
            n_weeks=n_weeks(cycle.plan_start, cycle.end_date),
            sessions_per_week=cycle.sessions_per_week,
            counts_by_week=counts,
            pace_available=zones.pace is not None,
            week_of_session=week_of_session,
            exported_ids={s.id for s in upcoming if s.status == "exported"},
        )
        + constraint_errors(planned_after_adjustment(cycle, upcoming, a), constraints, fixed_counts=fixed_counts),
    )


def save_proposal(db: DbSession, adj: AdjustmentResponse) -> int:
    """Passe les propositions en attente à `stale`, ajoute la nouvelle et renvoie son id."""
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


def request_adjustment(
    repo: Repo,
    garmin: GarminPort,
    llm: LLMProvider,
    note: str | None = None,
    missed: list[Session] = (),
) -> int:
    """Demande un ajustement à Claude, l'enregistre en proposition et renvoie son id.

    Porte sur le cycle actif. Les imprévus enregistrés sont transmis par `ask_adjustment` ; `note` décrit
    ce qui vient de changer.
    """
    from coach.services.goals import GoalError  # import tardif : goals importe ce module
    from coach.services.plans import _active_cycle

    cycle = _active_cycle(repo)
    if not cycle.plan_accepted:
        raise GoalError("Le plan doit être validé")
    _, zones = refresh_snapshot(repo, garmin)
    adj = ask_adjustment(
        repo, garmin, llm, cycle, zones, repo.sessions(cycle.id), garmin.today(), missed=list(missed), change_note=note
    )
    with repo.transaction() as db:
        proposal_id = save_proposal(db, adj)
    settings = load_settings()
    settings.proposal_due = False
    save_settings(settings)
    return proposal_id
