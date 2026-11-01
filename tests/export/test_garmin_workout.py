import json
from pathlib import Path

import pytest

from coach.analysis.zones import compute_zones
from coach.export.garmin_workout import flat_steps, session_to_workout_json
from coach.llm.schemas import RepeatSpec, StepSpec
from tests.llm.factories import make_session

FIXTURES = Path(__file__).parent.parent / "fixtures" / "garmin"
ZONES = compute_zones(
    threshold_pace_s_km=240,
    pred_10k_s=None,
    garmin_hr_zones=[100, 120, 140, 160, 175],
    hr_max=190,
    hr_rest=50,
)
INTERVALS_SESSION = make_session(
    type="VMA",
    target_kind="pace",
    steps=[
        StepSpec(kind="warmup", duration_s=900),
        RepeatSpec(
            repeat=6,
            steps=[
                StepSpec(kind="active", distance_m=400, zone="VMA"),
                StepSpec(kind="recovery", distance_m=200),
            ],
        ),
        StepSpec(kind="cooldown", duration_s=600),
    ],
)
EF_HR_SESSION = make_session(steps=[StepSpec(kind="active", duration_s=1800, zone="Z2")])


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def shape(steps: list[dict]) -> list[dict]:
    """Structure comparable : types et clés d'identifiants, sans les valeurs numériques."""
    out = []
    for s in steps:
        item = {
            "type": s["type"],
            "stepType": s["stepType"]["stepTypeKey"],
            "endCondition": s.get("endCondition", {}).get("conditionTypeKey"),
            "target": s.get("targetType", {}).get("workoutTargetTypeKey"),
            "iterations": s.get("numberOfIterations"),
        }
        if "workoutSteps" in s:
            item["steps"] = shape(s["workoutSteps"])
        out.append(item)
    return out


def first_active(workout: dict) -> dict:
    def walk(steps):
        for s in steps:
            if "workoutSteps" in s:
                yield from walk(s["workoutSteps"])
            elif s["stepType"]["stepTypeKey"] == "interval":
                yield s

    return next(walk(workout["workoutSegments"][0]["workoutSteps"]))


def test_intervals_match_reference_structure():
    out = session_to_workout_json(INTERVALS_SESSION, ZONES, name="S3 – VMA")
    ref = load_fixture("workout_intervals.json")
    assert shape(out["workoutSegments"][0]["workoutSteps"]) == shape(ref["workoutSegments"][0]["workoutSteps"])


def test_root_and_global_step_order():
    out = session_to_workout_json(INTERVALS_SESSION, ZONES, name="S3 – VMA")
    assert out["workoutName"] == "S3 – VMA"
    assert out["sportType"] == {"sportTypeId": 1, "sportTypeKey": "running"}
    assert len(out["workoutSegments"]) == 1 and out["workoutSegments"][0]["segmentOrder"] == 1
    steps = out["workoutSegments"][0]["workoutSteps"]
    assert steps[0]["stepOrder"] == 1
    assert steps[1]["stepOrder"] == 2
    assert [c["stepOrder"] for c in steps[1]["workoutSteps"]] == [3, 4]
    assert steps[2]["stepOrder"] == 5


def test_end_condition_values():
    steps = session_to_workout_json(INTERVALS_SESSION, ZONES, name="x")["workoutSegments"][0]["workoutSteps"]
    assert steps[0]["endConditionValue"] == 900
    assert steps[1]["workoutSteps"][0]["endConditionValue"] == 400


def test_pace_target_in_m_per_s_slow_first():
    step = first_active(session_to_workout_json(INTERVALS_SESSION, ZONES, name="x"))
    assert step["targetValueOne"] == pytest.approx(1000 / 223, rel=1e-3)  # borne lente de VMA si T=240
    assert step["targetValueOne"] < step["targetValueTwo"]


def test_hr_target_uses_bpm():
    step = first_active(session_to_workout_json(EF_HR_SESSION, ZONES, name="x"))
    assert step["targetType"] == {"workoutTargetTypeId": 4, "workoutTargetTypeKey": "heart.rate.zone"}
    assert (step["targetValueOne"], step["targetValueTwo"]) == ZONES.hr["Z2"]


def test_pace_zone_without_pace_zones_raises():
    zones = ZONES.model_copy(update={"pace": None})
    with pytest.raises(ValueError):
        session_to_workout_json(INTERVALS_SESSION, zones, name="x")


def _race_plan(*, trail: bool):
    from datetime import date

    from coach.analysis.gpx import ProfilePoint
    from coach.analysis.race_plan import RaceBasis, RaceSettings, build_race_plan

    basis = RaceBasis(
        captured_on=date(2026, 11, 1),
        pred_5k_s=None,
        pred_10k_s=2880,
        pred_half_s=None,
        pred_marathon_s=None,
        threshold_pace_s_km=None,
        hr={"Z1": (100, 120), "Z2": (120, 140), "Z3": (140, 160), "Z4": (160, 175), "Z5": (175, 190)},
    )
    profile = None
    if trail:  # 1 km plat, 3 km à +10 %, 1 km plat
        profile = [ProfilePoint(km=0.0, ele_m=100.0)]
        for i in range(1, 101):
            km = i * 0.05
            profile.append(ProfilePoint(km=km, ele_m=100.0 + max(0.0, min(km, 4.0) - 1.0) * 100))
    return build_race_plan(
        distance_km=5 if trail else 10,
        trail=trail,
        profile=profile,
        basis=basis,
        settings=RaceSettings(),
        today=date(2026, 11, 2),
    )


def test_race_workout_steps():
    from coach.export.garmin_workout import race_to_workout_json

    route = race_to_workout_json(_race_plan(trail=False), name="Jour J – 10 km")
    steps = route["workoutSegments"][0]["workoutSteps"]
    assert route["workoutName"] == "Jour J – 10 km" and len(steps) == 10
    assert steps[0]["endConditionValue"] == 1000
    assert steps[0]["endCondition"]["conditionTypeKey"] == "distance"
    assert steps[0]["stepType"]["stepTypeKey"] == "interval"
    assert steps[0]["targetType"]["workoutTargetTypeKey"] == "pace.zone"
    assert steps[0]["targetValueOne"] == pytest.approx(1000 / 293)
    assert steps[0]["targetValueTwo"] == pytest.approx(1000 / 283)
    assert [s["stepOrder"] for s in steps] == list(range(1, 11))
    assert steps[0]["description"] == "Plat – viser 5 min"


def test_race_workout_trail_uses_heart_rate():
    from coach.export.garmin_workout import race_to_workout_json

    plan = _race_plan(trail=True)
    steps = race_to_workout_json(plan, name="x")["workoutSegments"][0]["workoutSteps"]
    climb = next(s for s, seg in zip(steps, plan.segments) if seg.kind == "montée")
    assert climb["targetType"]["workoutTargetTypeKey"] == "heart.rate.zone"
    assert climb["description"].startswith("Montée +")
    assert " m – viser " in climb["description"]


def test_race_workout_requires_reference_time():
    from coach.export.garmin_workout import race_to_workout_json

    plan = _race_plan(trail=False).model_copy(update={"reference_time_s": None})
    with pytest.raises(ValueError):
        race_to_workout_json(plan, name="x")


def test_race_workout_description_hours_beyond_60_min():
    from coach.export.garmin_workout import race_to_workout_json

    plan = _race_plan(trail=False)
    long = plan.segments[0].model_copy(update={"time_s": 95 * 60})
    short = plan.segments[1].model_copy(update={"time_s": 52 * 60})
    plan = plan.model_copy(update={"segments": [long, short]})
    steps = race_to_workout_json(plan, name="x")["workoutSegments"][0]["workoutSteps"]
    assert steps[0]["description"] == "Plat – viser 1 h 35"
    assert steps[1]["description"] == "Plat – viser 52 min"


def _flat_spec():
    return make_session(
        steps=[
            StepSpec(kind="warmup", duration_s=900),
            RepeatSpec(
                repeat=3,
                steps=[
                    StepSpec(kind="active", distance_m=400, zone="Z5"),
                    StepSpec(kind="recovery", distance_m=200),
                ],
            ),
            StepSpec(kind="cooldown", duration_s=600),
        ]
    )


def test_flat_steps_unrolls_repeats_with_garmin_step_orders():
    flat = flat_steps(_flat_spec())
    assert [f.step_order for f in flat] == [1, 3, 4, 3, 4, 3, 4, 5]
    assert [(f.group, f.iteration, f.position) for f in flat][:3] == [
        (1, None, 0),
        (2, 1, 0),
        (2, 1, 1),
    ]
    assert flat[-1].group == 3 and flat[-1].iteration is None


def test_flat_steps_orders_match_exported_workout():
    spec = _flat_spec()
    workout = session_to_workout_json(spec, ZONES, name="x")

    def executable_orders(steps: list[dict]) -> set[int]:
        orders: set[int] = set()
        for s in steps:
            if s["type"] == "ExecutableStepDTO":
                orders.add(s["stepOrder"])
            else:
                orders |= executable_orders(s["workoutSteps"])
        return orders

    exported = executable_orders(workout["workoutSegments"][0]["workoutSteps"])
    assert exported == {f.step_order for f in flat_steps(spec)}
