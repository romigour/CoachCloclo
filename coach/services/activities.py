"""Enregistrement commun des activités Garmin (synchro et import de l'historique)."""

import json
from collections.abc import Iterable

from sqlalchemy.exc import IntegrityError

from coach.garmin.port import ActivitySummary
from coach.plan.models import Activity
from coach.plan.repo import Repo


def store_summaries(repo: Repo, summaries: Iterable[ActivitySummary]) -> int:
    """Enregistre les activités absentes de la base ; retourne le nombre ajouté.

    Chaque insertion a sa propre transaction : une insertion concurrente de la même
    activité (IntegrityError) est ignorée sans bloquer les suivantes.
    """
    n = 0
    for a in sorted(summaries, key=lambda a: (a.date, a.garmin_id)):
        if repo.activity_by_garmin_id(a.garmin_id) is not None:
            continue
        pace = a.duration_s / (a.distance_m / 1000) if a.distance_m else None
        try:
            repo.add(
                Activity(
                    garmin_activity_id=a.garmin_id,
                    date=a.date,
                    type_key=a.type_key,
                    duration_s=a.duration_s,
                    distance_m=a.distance_m,
                    d_plus_m=a.d_plus_m,
                    avg_hr=a.avg_hr,
                    avg_pace_s_km=pace,
                    raw_json=json.dumps(a.raw),
                )
            )
        except IntegrityError:
            continue
        n += 1
    return n
