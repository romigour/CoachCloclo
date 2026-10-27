"""Contexte athlète : instantané des métriques Garmin et historique récent."""

from datetime import timedelta

from coach.analysis.zones import Zones, compute_zones
from coach.garmin.port import GarminPort
from coach.plan.models import Activity, AthleteSnapshot
from coach.plan.repo import Repo
from coach.services import CoachError

HISTORY_DAYS = 56


def refresh_snapshot(repo: Repo, garmin: GarminPort) -> tuple[AthleteSnapshot, Zones]:
    """Lit les métriques Garmin, calcule les zones et enregistre un instantané."""
    m = garmin.metrics()
    try:
        zones = compute_zones(
            threshold_pace_s_km=m.threshold_pace_s_km,
            pred_10k_s=m.pred_10k_s,
            garmin_hr_zones=m.hr_zones,
            hr_max=m.hr_max,
            hr_rest=m.hr_rest,
        )
    except ValueError as exc:
        raise CoachError(f"{exc} : synchronise ta montre avec Garmin Connect") from exc
    snapshot = repo.add(
        AthleteSnapshot(
            date=garmin.today(),
            vo2max=m.vo2max,
            hr_max=m.hr_max,
            hr_rest=m.hr_rest,
            threshold_hr=m.threshold_hr,
            threshold_pace_s_km=m.threshold_pace_s_km,
            zones_json=zones.model_dump_json(),
        )
    )
    return snapshot, zones


def recent_history(garmin: GarminPort) -> list[Activity]:
    """Activités des 8 dernières semaines, transitoires (non enregistrées)."""
    today = garmin.today()
    out = []
    for a in garmin.activities(today - timedelta(days=HISTORY_DAYS), today):
        pace = a.duration_s / (a.distance_m / 1000) if a.distance_m else None
        out.append(
            Activity(
                garmin_activity_id=a.garmin_id,
                date=a.date,
                type_key=a.type_key,
                duration_s=a.duration_s,
                distance_m=a.distance_m,
                d_plus_m=a.d_plus_m,
                avg_hr=a.avg_hr,
                avg_pace_s_km=pace,
            )
        )
    return out
