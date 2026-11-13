"""Fin d'un cycle : clôture des objectifs et du cycle passés, préparation du cycle suivant."""

import json
from datetime import date, timedelta

from pydantic import Field
from sqlmodel import Session as DbSession
from sqlmodel import select

from coach.garmin.port import GarminPort
from coach.plan import calendar
from coach.plan.goals import cycle_end
from coach.plan.models import ALL_DAYS, Cycle, Event, Goal
from coach.plan.repo import Repo
from coach.services.goals import GoalError, check_availability, normalize_days, stale_pending
from coach.services.plans import PlanSettingsUpdate

DEFAULT_SESSIONS_PER_WEEK = 3  # sans cycle précédent (cas limite : données migrées)
RECOVERY_DAYS = 28  # premier objectif ajouté longtemps après la fin d'un cycle : plus de récupération


class NextCycleInput(PlanSettingsUpdate):
    """Réglages du cycle suivant : ceux du plan, plus le nombre de séances par semaine."""

    sessions_per_week: int | None = Field(None, ge=2, le=7)


def close_passed(repo: Repo, today: date) -> bool:
    """Objectifs à venir dont la date est passée → `done` ; cycle actif terminé → `done`, et ses
    propositions en attente → `stale`. Les séances restent (historique). Renvoie True si le cycle a été clos."""
    closed = False
    with repo.transaction() as db:
        for g in db.exec(select(Goal).where(Goal.status == "active", Goal.race_date < today)).all():
            g.status = "done"
            db.add(g)
        for c in db.exec(select(Cycle).where(Cycle.status == "active", Cycle.end_date < today)).all():
            c.status = "done"
            db.add(c)
            closed = True
        if closed:
            stale_pending(db)
    return closed


def _recovery_goal(repo: Repo, prev: Cycle) -> Goal | None:
    """Dernier objectif couru du cycle précédent."""
    return next((g for g in repo.past_goals() if prev.plan_start <= g.race_date <= prev.end_date), None)


def next_bounds(prev: Cycle | None, today: date, goals: list[Goal]) -> tuple[date, date | None]:
    """Départ et fin du cycle suivant pour les objectifs à venir `goals` : départ le lundi suivant la fin
    de `prev` (ou le lundi de cette semaine si on s'y prend tard), avancé au lundi de la première course
    si elle tombe avant ; fin selon les objectifs à partir de ce départ (None s'il n'y en a pas)."""
    start = calendar.plan_start(today)
    if prev is not None:
        start = max(start, prev.end_date + timedelta(days=7 - prev.end_date.weekday()))
    if goals:
        # une course avant ce lundi (ex. le samedi qui suit une course du mardi) appartient au nouveau cycle
        start = min(start, calendar.plan_start(min(g.race_date for g in goals)))
    return start, cycle_end([g for g in goals if g.race_date >= start])


def recovery_goal_id(repo: Repo, prev: Cycle | None, today: date | None = None) -> int | None:
    """Objectif dont le nouveau cycle doit commencer par récupérer ; avec `today`, seulement si `prev`
    a fini depuis moins de `RECOVERY_DAYS` jours."""
    if prev is None or (today is not None and (today - prev.end_date).days >= RECOVERY_DAYS):
        return None
    goal = _recovery_goal(repo, prev)
    return goal.id if goal is not None else None


def carry_open_injury(repo: Repo, db: DbSession, prev: Cycle | None, cycle_id: int) -> None:
    """Recopie dans le nouveau cycle l'arrêt encore ouvert de `prev` : la génération doit en tenir compte."""
    injury = repo.open_injury(prev.id) if prev is not None else None
    if injury is not None:
        db.add(Event(cycle_id=cycle_id, kind="injury", start_date=injury.start_date, note=injury.note))


def prepare_next_cycle(
    repo: Repo, garmin: GarminPort, data: PlanSettingsUpdate | NextCycleInput | None = None
) -> Cycle:
    """Crée le cycle suivant, à générer : réglages du dernier cycle (surchargés par `data`), départ le
    lundi suivant la fin de ce cycle (ou le lundi de cette semaine si on s'y prend tard, ou plus tôt si
    une course tombe avant ce lundi), récupération après sa dernière course et arrêt encore ouvert recopié."""
    today = garmin.today()
    close_passed(repo, today)  # la synchro a pu ne pas encore passer depuis la course
    if repo.active_cycle() is not None:
        raise GoalError("Un cycle est déjà en cours")
    prev = repo.last_done_cycle(today)
    start, end = next_bounds(prev, today, repo.upcoming_goals())
    if end is None:
        raise GoalError("Aucun objectif à venir")

    sessions_per_week = prev.sessions_per_week if prev else DEFAULT_SESSIONS_PER_WEEK
    available_days = prev.available_days() if prev else list(ALL_DAYS)
    long_run_day = prev.long_run_day if prev else None
    include_bike = prev.include_bike if prev else False
    if data is not None:
        if data.available_days is not None:
            available_days = normalize_days(data.available_days)
        if data.long_run_day is not None:
            long_run_day = data.long_run_day or None  # "" : plus de jour imposé
        if data.include_bike is not None:
            include_bike = data.include_bike
        if getattr(data, "sessions_per_week", None) is not None:
            sessions_per_week = data.sessions_per_week
    check_availability(available_days, long_run_day, sessions_per_week)

    recovery_id = recovery_goal_id(repo, prev)
    with repo.transaction() as db:
        cycle = Cycle(
            plan_start=start,
            end_date=end,
            sessions_per_week=sessions_per_week,
            available_days_json=json.dumps(available_days),
            long_run_day=long_run_day,
            include_bike=include_bike,
            needs_generation=True,
            recovery_from_goal_id=recovery_id,
        )
        db.add(cycle)
        db.flush()
        carry_open_injury(repo, db, prev, cycle.id)
    return cycle
