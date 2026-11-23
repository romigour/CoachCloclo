"""FC repos fiable : cache des nuits lues sur Garmin et saisie manuelle de l'athlète."""

from datetime import date, timedelta

from coach.analysis.rest_hr import WINDOW_DAYS, NightRecord, RestHr, choose_rest_hr, nights_average
from coach.garmin.port import GarminPort, GarminRateLimited, GarminUnavailable
from coach.plan.repo import Repo

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
