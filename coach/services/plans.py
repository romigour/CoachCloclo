"""Génération, validation et réglages du plan du cycle actif."""

import json
from typing import Literal

from pydantic import BaseModel
from sqlmodel import select

from coach.analysis.gpx import GpxSummary, summary_to_text
from coach.garmin.port import GarminPort
from coach.llm.client import ask_structured
from coach.llm.prompts import SYSTEM_PROMPT, build_generation_prompt, estimate_floors, generation_estimates
from coach.llm.provider import LLMProvider
from coach.llm.schemas import PlanResponse, Weekday, validate_plan
from coach.plan import calendar
from coach.plan.constraints import constraint_errors, planned_from_plan
from coach.plan.models import Cycle, Goal, Session
from coach.plan.repo import Repo
from coach.services.context import load_constraints, recent_history, refresh_snapshot
from coach.services.goals import (
    _NO_PLAN,
    _NOT_FOUND,
    MIN_PACE_S_KM,
    GoalError,
    _save_change,
    check_availability,
    normalize_days,
    stale_pending,
)


def _active_cycle(repo: Repo) -> Cycle:
    cycle = repo.active_cycle()
    if cycle is None:
        raise GoalError(_NO_PLAN)
    return cycle


def _gpx_texts(goals: list[Goal]) -> list[str]:
    return [
        summary_to_text(GpxSummary.model_validate_json(g.gpx_summary_json)) for g in goals if g.gpx_summary_json
    ]


def generate_plan(repo: Repo, garmin: GarminPort, llm: LLMProvider) -> PlanResponse:
    """Génère le plan du cycle actif avec Claude et remplace les séances `todo` concernées.

    Si le cycle a déjà des séances faites, manquées ou exportées, seule la suite est régénérée : à partir
    de la semaine courante, les séances non `todo` sont fixes (transmises à Claude et comptées dans leur
    semaine) et seules les `todo` de ces semaines sont remplacées.
    """
    cycle = _active_cycle(repo)
    goals = repo.goals_in(cycle)
    if not goals:
        raise GoalError(_NOT_FOUND)
    horizon = repo.horizon_goals(cycle)
    _, zones = refresh_snapshot(repo, garmin)
    n = calendar.n_weeks(cycle.plan_start, cycle.end_date)
    from coach.services.race_strategy import race_line_for_prompt  # import tardif : race_strategy importe ce module

    today = garmin.today()
    sessions = repo.sessions(cycle.id)
    first_week = 1
    if any(s.status != "todo" for s in sessions):
        first_week = max(1, calendar.week_of(cycle, today))
    # séances fixes : faites, manquées ou exportées, de la semaine courante à la fin du plan
    fixed = [
        s for s in sessions
        if s.status != "todo" and not s.pending_removal and first_week <= s.week_index <= n
        and (s.scheduled_date or calendar.suggested_date(cycle, s.week_index, s.suggested_day)) <= cycle.end_date
    ]
    fixed_counts: dict[int, int] = {}
    for s in fixed:
        fixed_counts[s.week_index] = fixed_counts.get(s.week_index, 0) + 1
    constraints = load_constraints(repo, cycle, today, goals)
    race_texts = [t for g in goals if (t := race_line_for_prompt(repo, g, today))]
    prompt = build_generation_prompt(
        cycle, goals, horizon, zones, recent_history(garmin), n, _gpx_texts(goals), today=today,
        race_texts=race_texts, constraints=constraints, first_week=first_week, fixed=fixed,
    )
    pace_available = zones.pace is not None
    # chaque objectif du cycle en mode `claude` est (ré)estimé, au-dessus de l'allure plancher
    estimate_min_s = estimate_floors(generation_estimates(goals), MIN_PACE_S_KM)
    plan = ask_structured(
        llm,
        SYSTEM_PROMPT,
        prompt,
        PlanResponse,
        validate=lambda p: validate_plan(
            p, n_weeks=n, sessions_per_week=cycle.sessions_per_week,
            pace_available=pace_available, estimate_min_s=estimate_min_s,
            first_week=first_week, fixed_counts=fixed_counts,
        )
        + constraint_errors(planned_from_plan(cycle, p), constraints, fixed_counts=fixed_counts),
    )
    with repo.transaction() as db:
        todo = select(Session).where(
            Session.cycle_id == cycle.id, Session.status == "todo", Session.week_index >= first_week
        )
        for s in db.exec(todo).all():
            db.delete(s)
        for week in plan.weeks:
            for spec in week.sessions:
                db.add(Session.from_spec(spec, cycle.id))
        c = db.get(Cycle, cycle.id)
        if c is None or c.status != "active":
            raise GoalError(_NO_PLAN)
        c.plan_accepted = False
        c.needs_generation = False
        db.add(c)
        stale_pending(db)  # les propositions portaient sur le plan remplacé
        for estimate in plan.estimated_times:
            g = db.get(Goal, estimate.goal_id)
            if estimate.goal_id in estimate_min_s and g is not None and g.target_source == "claude":
                g.target_time_s = estimate.seconds
                db.add(g)
    return plan


class PlanSettingsUpdate(BaseModel):
    available_days: list[Weekday] | None = None
    long_run_day: Weekday | Literal[""] | None = None  # "" : plus de jour imposé
    include_bike: bool | None = None


def update_plan_settings(
    repo: Repo, garmin: GarminPort, llm: LLMProvider, data: PlanSettingsUpdate
) -> tuple[Cycle, int]:
    """Modifie les disponibilités du cycle actif et demande l'ajustement à Claude.

    Rien n'est enregistré si Claude échoue. Renvoie le cycle enregistré et l'id de la proposition.
    """
    from coach.services.adjust import ask_adjustment  # import tardif : cycle via race_strategy

    cycle = _active_cycle(repo)
    if not cycle.plan_accepted:
        raise GoalError("Le plan de l'objectif doit être validé avant de le modifier")
    today = garmin.today()
    update: dict = {}
    notes: list[str] = []
    available_days = cycle.available_days()
    if data.available_days is not None:
        days = normalize_days(data.available_days)
        if days != available_days:
            available_days = days
            update["available_days_json"] = json.dumps(days)
            notes.append(f"jours possibles : {', '.join(days)}")
    long_run_day = cycle.long_run_day
    if data.long_run_day is not None:
        new_day = data.long_run_day or None
        if new_day != long_run_day:
            long_run_day = new_day
            update["long_run_day"] = new_day
            notes.append(f"sortie longue le {new_day}" if new_day else "plus de jour imposé pour la sortie longue")
    if data.include_bike is not None and data.include_bike != cycle.include_bike:
        update["include_bike"] = data.include_bike
        notes.append("vélo autorisé" if data.include_bike else "plus de vélo")
    check_availability(available_days, long_run_day, cycle.sessions_per_week)
    if not update:
        raise GoalError("Aucune modification")
    edited = cycle.model_copy(update=update)

    _, zones = refresh_snapshot(repo, garmin)
    note = f"L'athlète a modifié son objectif : {' ; '.join(notes)}. Adapte les séances à venir en conséquence."
    adj = ask_adjustment(repo, garmin, llm, edited, zones, repo.sessions(cycle.id), today, change_note=note)
    saved: dict[str, Cycle] = {}

    def apply(db) -> None:
        c = db.get(Cycle, cycle.id)
        if c is None or c.status != "active":
            raise GoalError(_NO_PLAN)
        for key, value in update.items():
            setattr(c, key, value)
        db.add(c)
        saved["cycle"] = c

    proposal_id = _save_change(repo, garmin, zones, adj, set(), apply)
    return saved["cycle"], proposal_id


def accept_plan(repo: Repo) -> None:
    """Valide le plan du cycle actif : l'export vers Garmin devient possible."""
    with repo.transaction() as db:
        cycle = db.exec(select(Cycle).where(Cycle.status == "active").order_by(Cycle.id.desc())).first()
        if cycle is None:
            raise GoalError(_NO_PLAN)
        cycle.plan_accepted = True
        db.add(cycle)
