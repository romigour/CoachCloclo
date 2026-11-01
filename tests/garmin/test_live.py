"""Tests réels contre Garmin Connect (tokens requis : `coach login` d'abord).

Lancer : `uv run pytest -m live tests/garmin -v`. Ne pas lancer en CI.
"""

import os
from datetime import timedelta

import pytest
from platformdirs import user_data_dir

from coach.garmin.client import GarminClient
from pathlib import Path


def _client() -> GarminClient:
    home = Path(os.environ.get("COACH_HOME") or user_data_dir("CoachCloclo"))
    return GarminClient.from_tokens(home / "garmin")


@pytest.mark.live
def test_read_only():
    c = _client()
    m = c.metrics()
    print(m)
    today = c.today()
    acts = c.activities(today - timedelta(days=30), today)
    print(len(acts), "activités")
    assert m is not None
    assert all(a.duration_s >= 0 for a in acts)


@pytest.mark.live
@pytest.mark.skipif(os.environ.get("COACH_LIVE_WRITE") != "1", reason="COACH_LIVE_WRITE=1 requis")
def test_workout_roundtrip():
    c = _client()
    workout = {
        "workoutName": "CoachCloclo test (à supprimer)",
        "sportType": {"sportTypeId": 1, "sportTypeKey": "running"},
        "workoutSegments": [
            {
                "segmentOrder": 1,
                "sportType": {"sportTypeId": 1, "sportTypeKey": "running"},
                "workoutSteps": [
                    {
                        "type": "ExecutableStepDTO",
                        "stepOrder": 1,
                        "stepType": {"stepTypeId": 3, "stepTypeKey": "interval"},
                        "endCondition": {"conditionTypeId": 2, "conditionTypeKey": "time"},
                        "endConditionValue": 600.0,
                        "targetType": {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target"},
                    }
                ],
            }
        ],
    }
    wid = sid = None
    try:
        wid = c.upload_workout(workout)
        day = c.today() + timedelta(days=30)
        sid = c.schedule(wid, day)
        c.reschedule(sid, day + timedelta(days=1))
        c.unschedule(sid)
        sid = None
    finally:
        try:
            if sid is not None:
                c.unschedule(sid)
        finally:
            if wid is not None:
                c.delete_workout(wid)


@pytest.mark.live
@pytest.mark.skipif(
    not (os.environ.get("COACH_LIVE_WORKOUT_ACTIVITY") and os.environ.get("COACH_LIVE_FREE_ACTIVITY")),
    reason="COACH_LIVE_WORKOUT_ACTIVITY et COACH_LIVE_FREE_ACTIVITY requis",
)
def test_activity_splits_capture(tmp_path):
    """Capture les tours bruts pour confirmer le champ d'étape et sa base.

    Écrit dans tmp_path (la fixture versionnée n'est jamais écrasée) et affiche
    les `wktStepIndex` de chaque tour : à comparer aux `stepOrder` du workout.
    """
    import json

    c = _client()
    out = {}
    for name, var in (("workout", "COACH_LIVE_WORKOUT_ACTIVITY"), ("free", "COACH_LIVE_FREE_ACTIVITY")):
        act_id = os.environ[var]
        out[name] = c._call(c._api.get_activity_splits, act_id)
        print(name, [lap.get("wktStepIndex") for lap in out[name].get("lapDTOs", [])])
    target = tmp_path / "activity_splits.json"
    target.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print("capture :", target)
