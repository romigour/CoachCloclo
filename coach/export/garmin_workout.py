"""Conversion d'une séance planifiée en JSON de workout Garmin Connect."""

from itertools import count
from typing import get_args

from coach.analysis.race_plan import RacePlan, Segment
from coach.analysis.zones import HrZoneName, PaceZoneName, Zones
from coach.llm.schemas import RepeatSpec, SessionSpec, StepSpec

_PACE_ZONES = frozenset(get_args(PaceZoneName))

_SPORT_RUNNING = {"sportTypeId": 1, "sportTypeKey": "running"}
_STEP_TYPES = {
    "warmup": {"stepTypeId": 1, "stepTypeKey": "warmup"},
    "cooldown": {"stepTypeId": 2, "stepTypeKey": "cooldown"},
    "active": {"stepTypeId": 3, "stepTypeKey": "interval"},
    "recovery": {"stepTypeId": 4, "stepTypeKey": "recovery"},
}
_REPEAT_TYPE = {"stepTypeId": 6, "stepTypeKey": "repeat"}
_END_TIME = {"conditionTypeId": 2, "conditionTypeKey": "time"}
_END_DISTANCE = {"conditionTypeId": 3, "conditionTypeKey": "distance"}
_END_ITERATIONS = {"conditionTypeId": 7, "conditionTypeKey": "iterations"}
_TARGET_NONE = {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target"}
_TARGET_HR = {"workoutTargetTypeId": 4, "workoutTargetTypeKey": "heart.rate.zone"}
_TARGET_PACE = {"workoutTargetTypeId": 6, "workoutTargetTypeKey": "pace.zone"}


def _target(zone: str | None, zones: Zones) -> dict:
    if zone is None:
        return {"targetType": dict(_TARGET_NONE)}
    if zone in _PACE_ZONES:
        if zones.pace is None:
            raise ValueError(f"Zone d'allure « {zone} » demandée mais aucune allure disponible")
        fast, slow = zones.pace[zone]
        # Garmin attend des m/s, borne lente (vitesse la plus basse) en premier.
        return {
            "targetType": dict(_TARGET_PACE),
            "targetValueOne": 1000 / slow,
            "targetValueTwo": 1000 / fast,
        }
    low, high = zones.hr[zone]
    return {"targetType": dict(_TARGET_HR), "targetValueOne": low, "targetValueTwo": high}


def _step(step: StepSpec, order: int, zones: Zones) -> dict:
    if step.duration_s is not None:
        end, value = _END_TIME, step.duration_s
    else:
        end, value = _END_DISTANCE, step.distance_m
    return {
        "type": "ExecutableStepDTO",
        "stepOrder": order,
        "stepType": dict(_STEP_TYPES[step.kind]),
        "endCondition": dict(end),
        "endConditionValue": value,
        **_target(step.zone, zones),
    }


def session_to_workout_json(session: SessionSpec, zones: Zones, *, name: str) -> dict:
    """Construit le dict de workout prêt pour `Garmin.upload_workout`."""
    orders = count(1)

    def convert(item: StepSpec | RepeatSpec) -> dict:
        if isinstance(item, RepeatSpec):
            order = next(orders)  # le groupe précède ses enfants
            return {
                "type": "RepeatGroupDTO",
                "stepOrder": order,
                "stepType": dict(_REPEAT_TYPE),
                "numberOfIterations": item.repeat,
                "endCondition": dict(_END_ITERATIONS),
                "endConditionValue": item.repeat,
                "workoutSteps": [convert(s) for s in item.steps],
            }
        return _step(item, next(orders), zones)

    return {
        "workoutName": name,
        "sportType": dict(_SPORT_RUNNING),
        "workoutSegments": [
            {
                "segmentOrder": 1,
                "sportType": dict(_SPORT_RUNNING),
                "workoutSteps": [convert(s) for s in session.steps],
            }
        ],
    }


def _race_description(seg: Segment) -> str:
    d_plus = f" +{seg.d_plus_m} m" if seg.d_plus_m else ""
    minutes = round(seg.time_s / 60)
    duration = f"{minutes // 60} h {minutes % 60:02d}" if minutes >= 60 else f"{minutes} min"
    return f"{seg.kind.capitalize()}{d_plus} – viser {duration}"


def _race_target(seg: Segment) -> dict:
    if seg.target_low is None or seg.target_high is None:
        return {"targetType": dict(_TARGET_NONE)}
    if seg.target_kind == "pace":
        # m/s, borne lente (vitesse la plus basse) en premier.
        return {
            "targetType": dict(_TARGET_PACE),
            "targetValueOne": 1000 / seg.target_high,
            "targetValueTwo": 1000 / seg.target_low,
        }
    return {"targetType": dict(_TARGET_HR), "targetValueOne": seg.target_low, "targetValueTwo": seg.target_high}


def race_to_workout_json(plan: RacePlan, *, name: str) -> dict:
    """Workout du jour J : une étape à la distance par segment du plan de course."""
    if plan.reference_time_s is None:
        raise ValueError("Pas de temps de référence : saisis un temps visé")
    steps = [
        {
            "type": "ExecutableStepDTO",
            "stepOrder": i,
            "stepType": dict(_STEP_TYPES["active"]),
            "endCondition": dict(_END_DISTANCE),
            "endConditionValue": round((seg.end_km - seg.start_km) * 1000),
            "description": _race_description(seg),
            **_race_target(seg),
        }
        for i, seg in enumerate(plan.segments, start=1)
    ]
    return {
        "workoutName": name,
        "sportType": dict(_SPORT_RUNNING),
        "workoutSegments": [{"segmentOrder": 1, "sportType": dict(_SPORT_RUNNING), "workoutSteps": steps}],
    }
