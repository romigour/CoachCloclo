"""Contexte athlète : instantané des métriques Garmin et historique récent."""

from datetime import date, timedelta

from coach.analysis.long_history import MONTHS, LongHistory, kept_records, monthly_volume, past_races, window_start
from coach.analysis.zones import Zones, compute_zones
from coach.garmin.port import GarminPort, Metrics
from coach.plan.constraints import PlanConstraints
from coach.plan.models import Activity, AthleteSnapshot, Cycle, Goal
from coach.plan.repo import Repo
from coach.services import CoachError

HISTORY_DAYS = 56


def zones_from_metrics(m: Metrics) -> Zones:
    """Calcule les zones depuis les métriques Garmin ; CoachError si elles sont insuffisantes."""
    try:
        return compute_zones(
            threshold_pace_s_km=m.threshold_pace_s_km,
            pred_10k_s=m.pred_10k_s,
            garmin_hr_zones=m.hr_zones,
            hr_max=m.hr_max,
            hr_rest=m.hr_rest,
        )
    except ValueError as exc:
        raise CoachError(f"{exc} : synchronise ta montre avec Garmin Connect") from exc


def refresh_snapshot(repo: Repo, garmin: GarminPort) -> tuple[AthleteSnapshot, Zones]:
    """Lit les métriques Garmin, calcule les zones et enregistre un instantané."""
    m = garmin.metrics()
    zones = zones_from_metrics(m)
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


def load_constraints(repo: Repo, cycle: Cycle, today: date, goals: list[Goal] | None = None) -> PlanConstraints:
    """Contraintes de disponibilité du cycle, imprévus enregistrés et jours de course compris.

    Les jours de course sont ceux des objectifs du cycle (`goals_in`), sauf si `goals` est fourni
    (objectifs du cycle après un changement pas encore enregistré).
    """
    events = repo.events(cycle.id) if cycle.id is not None else []
    if goals is None:
        goals = repo.goals_in(cycle)
    return PlanConstraints.of(cycle, today, events, goals)


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


def long_history(repo: Repo, today: date) -> LongHistory | None:
    """Historique long lu en base (import de l'historique) ; None si la base n'a aucune activité."""
    if not repo.has_activities():
        return None
    activities = repo.all_activities()
    # pas de mois avant la plus ancienne activité en base : sans import complet (synchro seule),
    # ils passeraient pour des mois d'arrêt
    oldest = min(a.date for a in activities)
    span = (today.year - oldest.year) * 12 + today.month - oldest.month + 1
    months = max(1, min(MONTHS, span))
    start = window_start(today, months)
    return LongHistory(
        months=monthly_volume([a for a in activities if a.date >= start], today, months),
        races=past_races(repo.races(), {a.id: a for a in activities}),
        records=kept_records(repo.records()),
    )
