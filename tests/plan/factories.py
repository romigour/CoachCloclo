"""Fabriques de modèles de plan pour les tests."""

from datetime import date

from coach.plan.models import Goal, Session
from tests.llm.factories import make_session


def make_goal(**overrides) -> Goal:
    data = {
        "plan_start": date(2026, 10, 26),
        "race_date": date(2027, 1, 31),
        "type": "trail",
        "distance_km": 42,
        "d_plus_m": 2000,
        "sessions_per_week": 3,
        "status": "active",
    }
    data.update(overrides)
    return Goal(**data)


def make_db_session(goal_id: int, **overrides) -> Session:
    """Session persistable issue de `make_session(**overrides)`."""
    return Session.from_spec(make_session(**overrides), goal_id=goal_id)
