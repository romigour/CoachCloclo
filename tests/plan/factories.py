"""Fabriques de modèles de plan pour les tests."""

from datetime import date

from coach.analysis.zones import Zones, compute_zones, hr_zones
from coach.plan.models import Activity, Cycle, Goal, Session
from tests.llm.factories import make_session

PACE = compute_zones(threshold_pace_s_km=300, pred_10k_s=None, hr_max=182, hr_rest=55).pace


def zones_rest(x: int) -> Zones:
    """Zones dont la FC vient de `hr_zones(182, x)`."""
    return Zones(pace=PACE, hr=hr_zones(182, x), source=["lactate_threshold", "karvonen"])


def make_goal(**overrides) -> Goal:
    data = {
        "plan_start": date(2026, 10, 26),
        "race_date": date(2027, 1, 31),
        "type": "trail",
        "distance_km": 42,
        "d_plus_m": 2000,
        "sessions_per_week": 3,
        "status": "active",
        "priority": "principal",
    }
    data.update(overrides)
    return Goal(**data)


def make_cycle(**overrides) -> Cycle:
    data = {
        "plan_start": date(2026, 10, 26),
        "end_date": date(2027, 1, 31),
        "sessions_per_week": 3,
        "status": "active",
    }
    data.update(overrides)
    return Cycle(**data)


def make_db_session(cycle_id: int, **overrides) -> Session:
    """Session persistable issue de `make_session(**overrides)`."""
    return Session.from_spec(make_session(**overrides), cycle_id=cycle_id)


def make_activity(**overrides) -> Activity:
    """Activité de course à pied par défaut (45 min, 9 km) ; `overrides` écrase les champs."""
    data = {
        "garmin_activity_id": 1,
        "date": date(2026, 11, 10),
        "type_key": "running",
        "duration_s": 2700,
        "distance_m": 9000,
    }
    data.update(overrides)
    return Activity(**data)
