"""Tours des activités : récupération à la synchro et comparaison avec la séance prévue."""

import logging
from typing import Literal

from coach.analysis.laps import StepComparison, compare_session
from coach.analysis.zones import Zones
from coach.garmin.port import (
    GarminAuthRequired,
    GarminPort,
    GarminRateLimited,
    GarminUnavailable,
)
from coach.plan.models import Activity, Session
from coach.plan.repo import Repo

log = logging.getLogger(__name__)


def fetch_laps(repo: Repo, garmin: GarminPort, activity: Activity) -> bool:
    """Lit et enregistre les tours ; en cas d'erreur Garmin, ne stocke rien (nouvel essai à la synchro suivante)."""
    try:
        laps = garmin.activity_laps(activity.garmin_activity_id)
    except (GarminUnavailable, GarminRateLimited, GarminAuthRequired) as exc:
        log.warning("Tours de l'activité %s non récupérés : %s", activity.garmin_activity_id, exc)
        return False
    repo.save_laps(activity.id, laps)
    return True


def fetch_missing_laps(repo: Repo, garmin: GarminPort) -> int:
    """Récupère les tours des activités rattachées à une séance qui n'en ont pas encore."""
    return sum(
        fetch_laps(repo, garmin, a)
        for a in repo.all_activities()
        if a.session_id is not None and repo.laps(a.id) is None
    )


def latest_zones(repo: Repo) -> Zones | None:
    """Zones du dernier instantané Garmin, `None` s'il n'y en a pas encore."""
    snap = repo.latest_snapshot()
    return None if snap is None else Zones.model_validate_json(snap.zones_json)


def session_comparison(
    repo: Repo, session: Session, zones: Zones | None
) -> StepComparison | Literal["no_activity", "no_laps"]:
    """Compare les tours de l'activité rattachée à la séance, ou dit pourquoi c'est impossible."""
    activity = repo.activity_of_session(session.id)
    if activity is None:
        return "no_activity"
    laps = repo.laps(activity.id)
    if laps is None:
        return "no_laps"
    return compare_session(session.to_spec(), laps, zones)
