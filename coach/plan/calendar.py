"""Calendrier hebdomadaire du plan (semaines du lundi au dimanche)."""

from datetime import date, timedelta

from coach.plan.models import Goal


def plan_start(today: date) -> date:
    """Lundi de la semaine de `today`."""
    return today - timedelta(days=today.weekday())


def n_weeks(start: date, race_date: date) -> int:
    """Nombre de semaines du plan ; la dernière contient la course."""
    return (race_date - start).days // 7 + 1


def week_monday(goal: Goal, week_index: int) -> date:
    return goal.plan_start + timedelta(weeks=week_index - 1)


def week_of(goal: Goal, d: date) -> int:
    """Index (base 1) de la semaine de `d` ; peut sortir de [1, n] hors du plan."""
    return (d - goal.plan_start).days // 7 + 1
