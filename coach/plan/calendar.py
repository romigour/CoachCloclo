"""Calendrier hebdomadaire du plan (semaines du lundi au dimanche)."""

from datetime import date, timedelta

from coach.plan.models import Cycle


def plan_start(today: date) -> date:
    """Lundi de la semaine de `today`."""
    return today - timedelta(days=today.weekday())


def n_weeks(start: date, race_date: date) -> int:
    """Nombre de semaines du plan ; la dernière contient la course."""
    return (race_date - start).days // 7 + 1


def week_monday(cycle: Cycle, week_index: int) -> date:
    return cycle.plan_start + timedelta(weeks=week_index - 1)


_WEEKDAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")


def suggested_date(cycle: Cycle, week_index: int, suggested_day: str) -> date:
    """Date du jour suggéré (nom français du jour) dans la semaine `week_index`."""
    return week_monday(cycle, week_index) + timedelta(days=_WEEKDAYS.index(suggested_day))


def week_of(cycle: Cycle, d: date) -> int:
    """Index (base 1) de la semaine de `d` ; peut sortir de [1, n] hors du plan."""
    return (d - cycle.plan_start).days // 7 + 1
