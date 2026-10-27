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
    home = Path(os.environ.get("COACH_HOME") or user_data_dir("coach"))
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
        "workoutName": "Coach test (à supprimer)",
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
        if sid is not None:
            c.unschedule(sid)
        if wid is not None:
            c.delete_workout(wid)
