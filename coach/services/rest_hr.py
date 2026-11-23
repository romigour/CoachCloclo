"""FC repos fiable : cache des nuits lues sur Garmin et saisie manuelle de l'athlète."""

import logging
from datetime import date, timedelta

from coach.analysis.rest_hr import WINDOW_DAYS, NightRecord, RestHr, choose_rest_hr, nights_average
from coach.analysis.zones import Zones, hr_zones
from coach.garmin.port import GarminAuthRequired, GarminPort, GarminRateLimited, GarminUnavailable
from coach.plan.models import AthleteSnapshot
from coach.plan.repo import Repo

_log = logging.getLogger(__name__)

# AppState : {"YYYY-MM-DD": {"hr_rest": int | None, "slept": bool}}
NIGHTS_KEY = "rest_nights"
# AppState : {"value": int | None}
MANUAL_KEY = "rest_hr_manual"


def load_manual(repo: Repo) -> int | None:
    """FC repos saisie par l'athlète, s'il y en a une."""
    state = repo.get_state(MANUAL_KEY)
    return state.get("value") if state else None


def save_manual(repo: Repo, value: int | None) -> None:
    """Enregistre la FC repos saisie ; None revient au calcul automatique."""
    repo.set_state(MANUAL_KEY, {"value": value})


def _records(cache: dict) -> list[NightRecord]:
    return sorted(
        (NightRecord(day=date.fromisoformat(day), hr_rest=v["hr_rest"], slept=v["slept"]) for day, v in cache.items()),
        key=lambda r: r.day,
    )


def cached_nights(repo: Repo) -> list[NightRecord]:
    """Nuits en cache, de la plus ancienne à la plus récente."""
    return _records(repo.get_state(NIGHTS_KEY) or {})


def refresh_nights(repo: Repo, garmin: GarminPort) -> list[NightRecord]:
    """Complète le cache des nuits de la fenêtre et renvoie ses nuits.

    Lit les jours absents du cache, plus aujourd'hui et hier toujours (leur nuit peut remonter tard).
    Un jour où Garmin est indisponible ou limite les appels est sauté, sans être mis en cache ;
    GarminAuthRequired remonte. Le cache ne garde que les jours de la fenêtre.
    """
    today = garmin.today()
    days = [today - timedelta(days=i) for i in range(WINDOW_DAYS)]
    old = repo.get_state(NIGHTS_KEY) or {}
    cache = {d.isoformat(): old[d.isoformat()] for d in days if d.isoformat() in old}
    for day in days:
        key = day.isoformat()
        if key in cache and day < today - timedelta(days=1):
            continue
        try:
            night = garmin.night_rest(day)
        except (GarminUnavailable, GarminRateLimited):
            continue  # jour sauté : relu à la prochaine synchro
        cache[key] = {"hr_rest": night.hr_rest, "slept": night.slept}
    repo.set_state(NIGHTS_KEY, cache)
    return _records(cache)


def resolve_rest_hr(repo: Repo, nights: list[NightRecord], today: date, garmin_value: int | None) -> RestHr:
    """FC repos retenue : saisie manuelle, moyenne des nuits, dernière moyenne enregistrée, valeur Garmin."""
    last = repo.latest_nights_snapshot()
    return choose_rest_hr(
        manual=load_manual(repo),
        nights=nights_average(nights, today),
        last_nights_value=last.hr_rest if last else None,
        garmin_value=garmin_value,
    )


def rest_hr_view(repo: Repo, today: date) -> dict:
    """FC repos retenue (dernier instantané), saisie manuelle et moyenne automatique des nuits en cache."""
    last = repo.latest_snapshot()
    auto = nights_average(cached_nights(repo), today)
    return {
        "value": last.hr_rest if last else None,
        "source": last.hr_rest_source if last else None,
        "nights": last.hr_rest_nights if last else None,
        "manual": load_manual(repo),
        "auto_value": auto[0] if auto else None,
        "auto_nights": auto[1] if auto else None,
    }


def apply_manual(repo: Repo, garmin: GarminPort, value: int | None) -> dict:
    """Enregistre la saisie, recalcule tout de suite la FC repos et les zones FC, puis renvoie à la montre
    les séances concernées.

    Sans instantané, la saisie est seulement enregistrée (`applied` faux). Sinon un nouvel instantané
    reprend le dernier, sans lecture Garmin des métriques ni des nuits (nuits du cache). Un échec Garmin
    du renvoi ne fait pas échouer la saisie.
    """
    # import local : rezone → garmin_export → context importe ce module
    from coach.services.rezone import resend_for_zones

    save_manual(repo, value)
    today = garmin.today()
    last = repo.latest_snapshot()
    if last is None:
        return {**rest_hr_view(repo, today), "resent": 0, "failed": [], "applied": False}
    # pas de lecture Garmin : la valeur Garmin est celle du dernier instantané qui la tenait de Garmin
    garmin_snap = repo.latest_garmin_rest_snapshot()
    garmin_value = garmin_snap.hr_rest if garmin_snap else None
    rest = resolve_rest_hr(repo, cached_nights(repo), today, garmin_value)
    if rest.value is None:
        # aucune valeur Garmin connue : on garde la dernière FC repos
        rest = RestHr(value=last.hr_rest, source="garmin")
    zones = Zones.model_validate_json(last.zones_json)
    if last.hr_max is not None and rest.value is not None:
        zones = zones.model_copy(update={"hr": hr_zones(last.hr_max, rest.value)})
    repo.add(
        AthleteSnapshot(
            date=today,
            vo2max=last.vo2max,
            hr_max=last.hr_max,
            hr_rest=rest.value,
            threshold_hr=last.threshold_hr,
            threshold_pace_s_km=last.threshold_pace_s_km,
            zones_json=zones.model_dump_json(),
            hr_rest_source=rest.source,
            hr_rest_nights=rest.nights,
        )
    )
    resent, failed = 0, []
    try:
        r = resend_for_zones(repo, garmin, zones, today)
        resent, failed = r.resent, r.failed
    except (GarminUnavailable, GarminAuthRequired, GarminRateLimited):
        _log.exception("Renvoi des séances après saisie de la FC repos échoué")
    return {**rest_hr_view(repo, today), "resent": resent, "failed": failed, "applied": True}
