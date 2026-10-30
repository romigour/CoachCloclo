"""Tests de la normalisation des activités Garmin pour les statistiques."""

import datetime as dt
import json
from pathlib import Path

from coach.plan.models import Activity, Race
from coach.stats.normalize import sport_family, stat_row

FIXTURE = Path(__file__).parent.parent / "fixtures" / "garmin" / "activity_full.json"

KEYS = {
    "id", "garmin_id", "date", "start", "name", "family", "type_key", "duration_s",
    "distance_m", "d_plus_m", "avg_hr", "max_hr", "vo2max", "hr_zones_s", "race",
}


def _activity(raw: dict | str, **kw) -> Activity:
    base = dict(
        id=1, garmin_activity_id=42, date=dt.date(2026, 10, 18), type_key="running",
        duration_s=3600.0, distance_m=10000.0, d_plus_m=50.0, avg_hr=150.0,
        raw_json=raw if isinstance(raw, str) else json.dumps(raw),
    )
    base.update(kw)
    return Activity(**base)


def test_sport_family():
    assert sport_family("trail_running") == "trail"
    assert sport_family("treadmill_running") == "run"
    assert sport_family("indoor_cycling") == "bike"
    assert sport_family("paddleboarding") == "other"


def test_stat_row_full():
    row = stat_row(_activity(json.loads(FIXTURE.read_text(encoding="utf-8"))), None)
    assert set(row) == KEYS
    assert len(row["hr_zones_s"]) == 5
    assert row["name"] == "Semi de Nantes"
    assert row["max_hr"] == 182.0
    assert row["vo2max"] == 52.0
    assert row["start"] == "2026-10-18 09:00:00"
    assert row["garmin_id"] == 42
    assert row["date"] == "2026-10-18"
    assert isinstance(row["race"], dict) and row["race"]["name"] is None


def test_stat_row_minimal_raw():
    row = stat_row(_activity("{}"), None)
    assert row["start"] is None
    for k in ("name", "max_hr", "vo2max", "hr_zones_s", "race"):
        assert row[k] is None
    assert row["date"] == "2026-10-18"


def test_stat_row_unreadable_raw():
    assert stat_row(_activity("pas du json"), None)["name"] is None


def test_stat_row_partial_zones():
    raw = {f"hrTimeInZone_{i}": 10.0 for i in range(1, 5)}
    assert stat_row(_activity(raw), None)["hr_zones_s"] is None


def test_stat_row_zero_distance():
    row = stat_row(_activity({}, distance_m=0, duration_s=0), None)
    assert row["distance_m"] is None
    assert row["duration_s"] is None


def test_race_priority():
    raw = {"eventType": {"typeKey": "race"}}
    assert stat_row(_activity(raw), Race(activity_id=1, excluded=True))["race"] is None
    row = stat_row(_activity({}), Race(activity_id=1, name="Semi de Nantes"))
    assert row["race"]["name"] == "Semi de Nantes"
