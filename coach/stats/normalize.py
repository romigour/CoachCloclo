"""Normalisation des activités Garmin en lignes JSON pour la page Stats."""

import json
from typing import Literal

from coach.plan.models import Activity, Race

Family = Literal["run", "trail", "bike", "swim", "strength", "walk", "other"]

FAMILIES: dict[str, Family] = {
    **dict.fromkeys(
        ["running", "treadmill_running", "track_running", "street_running",
         "indoor_running", "virtual_run"], "run"),
    **dict.fromkeys(["trail_running", "ultra_run"], "trail"),
    **dict.fromkeys(
        ["cycling", "road_biking", "mountain_biking", "gravel_cycling",
         "indoor_cycling", "virtual_ride", "e_bike_fitness"], "bike"),
    **dict.fromkeys(["lap_swimming", "open_water_swimming", "swimming"], "swim"),
    **dict.fromkeys(
        ["strength_training", "indoor_cardio", "hiit", "yoga", "pilates"], "strength"),
    **dict.fromkeys(["walking", "hiking", "casual_walking"], "walk"),
}

_RACE_FIELDS = (
    "name", "official_time_s", "overall_rank", "overall_total",
    "category", "category_rank", "category_total",
)


def sport_family(type_key: str) -> Family:
    """Famille de sport d'un `typeKey` Garmin (inconnu : « other »)."""
    return FAMILIES.get(type_key, "other")


def race_view(race: Race) -> dict:
    """Les 7 champs de saisie d'une course."""
    return {f: getattr(race, f) for f in _RACE_FIELDS}


def _raw(activity: Activity) -> dict:
    """JSON brut de l'activité ; illisible ou non-objet : `{}`."""
    try:
        raw = json.loads(activity.raw_json)
    except (TypeError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _positive(value):
    """Valeur numérique strictement positive, sinon `None`."""
    return value if isinstance(value, (int, float)) and value > 0 else None


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def stat_row(activity: Activity, race: Race | None) -> dict:
    """Ligne normalisée d'une activité (consommée par le front)."""
    raw = _raw(activity)
    zones = [raw.get(f"hrTimeInZone_{i}") for i in range(1, 6)]
    event = raw.get("eventType")
    is_race = isinstance(event, dict) and event.get("typeKey") == "race"
    if race is not None and not race.excluded:
        race_out = race_view(race)
    elif race is None and is_race:
        race_out = race_view(Race(activity_id=activity.id))
    else:
        race_out = None
    return {
        "id": activity.id,
        "garmin_id": activity.garmin_activity_id,
        "date": activity.date.isoformat(),
        "start": raw.get("startTimeLocal"),
        "name": raw.get("activityName"),
        "family": sport_family(activity.type_key),
        "type_key": activity.type_key,
        "duration_s": _positive(activity.duration_s),
        "distance_m": _positive(activity.distance_m),
        "d_plus_m": activity.d_plus_m,
        "avg_hr": activity.avg_hr,
        "max_hr": raw.get("maxHR"),
        "vo2max": raw.get("vO2MaxValue"),
        "hr_zones_s": zones if all(_is_num(z) for z in zones) else None,
        "race": race_out,
    }
