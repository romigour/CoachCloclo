"""Imprévus de l'athlète : validation avant enregistrement."""

import json
from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, Field

from coach.llm.schemas import Weekday
from coach.plan import calendar
from coach.plan.models import Event, Goal
from coach.plan.repo import Repo
from coach.services import CoachError
from coach.services.plans import normalize_days


class EventError(CoachError):
    """Imprévu invalide."""


class EventInput(BaseModel):
    kind: Literal["unavailable", "injury", "light_week", "fatigue"]
    start_date: date | None = None
    end_date: date | None = None
    max_sessions: int | None = Field(None, ge=0)
    days: list[Weekday] | None = None
    session_id: int | None = None
    note: str | None = Field(None, max_length=1000)


def _check_order(start: date, end: date | None) -> None:
    if end is not None and end < start:
        raise EventError("La fin doit être après le début")


def _is_plan_monday(goal: Goal, d: date | None) -> bool:
    return (
        d is not None
        and d.weekday() == 0
        and 1 <= calendar.week_of(goal, d) <= calendar.n_weeks(goal.plan_start, goal.race_date)
    )


def build_event(repo: Repo, goal: Goal, data: EventInput, today: date) -> Event:
    """Valide `data` et renvoie l'imprévu à enregistrer (n'écrit rien)."""
    start, end = data.start_date, data.end_date
    max_sessions = days = session_id = None
    if data.kind == "unavailable":
        if start is None or end is None:
            raise EventError("Indique les dates de début et de fin")
        _check_order(start, end)
    elif data.kind == "injury":
        if start is None:
            raise EventError("Indique la date de début")
        _check_order(start, end)
        # un seul arrêt ouvert : seul un nouvel arrêt ouvert entre en conflit
        if end is None and repo.open_injury(goal.id) is not None:
            raise EventError("Un arrêt est déjà en cours : signale d'abord la reprise")
    elif data.kind == "light_week":
        if not _is_plan_monday(goal, start):
            raise EventError("Choisis une semaine du plan")
        if data.max_sessions is None:
            raise EventError("Indique le nombre de séances maximum")
        end = start + timedelta(days=6)
        max_sessions = data.max_sessions
        if data.days is not None:
            days = normalize_days(data.days)
            if not set(days) <= set(goal.available_days()):
                raise EventError("Les jours de la semaine allégée doivent faire partie de tes jours possibles")
    else:  # fatigue : toujours datée d'aujourd'hui
        start = end = today
        if data.session_id is not None:
            try:
                owned = repo.session(data.session_id).goal_id == goal.id
            except KeyError:
                owned = False
            if not owned:
                raise EventError("Séance introuvable")
            session_id = data.session_id
    return Event(
        goal_id=goal.id,
        kind=data.kind,
        start_date=start,
        end_date=end,
        max_sessions=max_sessions,
        days_json=None if days is None else json.dumps(days),
        session_id=session_id,
        note=data.note,
    )
