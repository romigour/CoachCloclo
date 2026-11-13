"""Fin d'un cycle : clôture des objectifs et du cycle passés, préparation du cycle suivant."""

import json
from datetime import date, timedelta

from sqlmodel import select

from coach.garmin.port import GarminPort
from coach.plan import calendar
from coach.plan.goals import cycle_end
from coach.plan.models import ALL_DAYS, Cycle, Event, Goal
from coach.plan.repo import Repo
from coach.services.goals import GoalError, check_availability, normalize_days, stale_pending
from coach.services.plans import PlanSettingsUpdate

DEFAULT_SESSIONS_PER_WEEK = 3  # sans cycle précédent (cas limite : données migrées)


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


def prepare_next_cycle(repo: Repo, garmin: GarminPort, data: PlanSettingsUpdate | None = None) -> Cycle:
    """Crée le cycle suivant, à générer : réglages du dernier cycle (surchargés par `data`), départ le
    lundi suivant la fin de ce cycle (ou le lundi de cette semaine si on s'y prend tard), récupération
    après sa dernière course et arrêt encore ouvert recopié."""
    today = garmin.today()
    close_passed(repo, today)  # la synchro a pu ne pas encore passer depuis la course
    if repo.active_cycle() is not None:
        raise GoalError("Un cycle est déjà en cours")
    prev = repo.last_done_cycle(today)
    start = calendar.plan_start(today)
    if prev is not None:
        start = max(start, prev.end_date + timedelta(days=7 - prev.end_date.weekday()))
    goals = [g for g in repo.upcoming_goals() if g.race_date >= start]
    end = cycle_end(goals)
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
    check_availability(available_days, long_run_day, sessions_per_week)

    recovery = _recovery_goal(repo, prev) if prev else None
    injury = repo.open_injury(prev.id) if prev else None
    with repo.transaction() as db:
        cycle = Cycle(
            plan_start=start,
            end_date=end,
            sessions_per_week=sessions_per_week,
            available_days_json=json.dumps(available_days),
            long_run_day=long_run_day,
            include_bike=include_bike,
            needs_generation=True,
            recovery_from_goal_id=recovery.id if recovery else None,
        )
        db.add(cycle)
        db.flush()
        if injury is not None:  # l'arrêt continue : la génération doit en tenir compte
            db.add(Event(cycle_id=cycle.id, kind="injury", start_date=injury.start_date, note=injury.note))
    return cycle
