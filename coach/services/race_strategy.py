"""Stratégie du jour J : création, réglages et lecture du plan de course."""

from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from coach.analysis.gpx import _NO_ELE, ProfilePoint, profile, waypoints
from coach.analysis.race_plan import AidStation, RaceBasis, RacePlan, RaceSettings, build_race_plan
from coach.garmin.port import GarminPort
from coach.plan.models import Goal, RaceStrategy
from coach.plan.repo import Repo
from coach.services import CoachError
from coach.services.context import zones_from_metrics
from coach.services.plans import _get_goal

MAX_PROFILE_POINTS = 500
_NO_FILE = "Fichier GPX introuvable : découpage sans profil"


class RaceView(BaseModel):
    """Réglages et plan calculé d'un objectif, tels que l'API les renvoie."""

    goal_id: int
    goal_type: Literal["route", "trail"]
    race_date: date
    settings: RaceSettings
    basis_date: date
    profile: list[tuple[float, float]] | None
    plan: RacePlan
    workout_id: int | None
    export_error: str | None


def _read_gpx(goal: Goal) -> bytes | None:
    if not goal.gpx_path:
        return None
    path = Path(goal.gpx_path)
    return path.read_bytes() if path.is_file() else None


def _capture_basis(garmin: GarminPort) -> RaceBasis:
    m = garmin.metrics()
    return RaceBasis(
        captured_on=garmin.today(),
        pred_5k_s=m.pred_5k_s,
        pred_10k_s=m.pred_10k_s,
        pred_half_s=m.pred_half_s,
        pred_marathon_s=m.pred_marathon_s,
        threshold_pace_s_km=m.threshold_pace_s_km,
        hr=zones_from_metrics(m).hr,
    )


def _stations_from_gpx(goal: Goal) -> list[AidStation]:
    """Ravitos pré-remplis depuis les waypoints du GPX (trail uniquement)."""
    data = _read_gpx(goal)
    if goal.type != "trail" or data is None:
        return []
    return [AidStation(km=w.km, name=w.name, kind="complet", stop_min=3) for w in waypoints(data)]


def _downsample(points: list[ProfilePoint]) -> list[tuple[float, float]]:
    """Au plus MAX_PROFILE_POINTS points, régulièrement espacés, premier et dernier compris."""
    n = len(points)
    if n <= MAX_PROFILE_POINTS:
        idx = range(n)
    else:
        idx = [round(i * (n - 1) / (MAX_PROFILE_POINTS - 1)) for i in range(MAX_PROFILE_POINTS)]
    return [(points[i].km, points[i].ele_m) for i in idx]


def _compute(strategy: RaceStrategy, goal: Goal, today: date) -> tuple[RacePlan, list[ProfilePoint] | None]:
    settings = RaceSettings.model_validate_json(strategy.settings_json)
    basis = RaceBasis.model_validate_json(strategy.basis_json)
    data = _read_gpx(goal)
    prof = profile(data) if data is not None else None
    distance = prof[-1].km if prof else goal.distance_km
    for st in settings.aid_stations:
        if st.km >= distance:
            raise CoachError(f"Le ravito « {st.name} » (km {st.km:g}) dépasse la distance du parcours ({distance:g} km)")
    try:
        plan = build_race_plan(
            distance_km=distance,
            trail=goal.type == "trail",
            profile=prof,
            basis=basis,
            settings=settings,
            today=today,
        )
    except ValueError as exc:
        raise CoachError(str(exc)) from exc
    if goal.gpx_path and data is None:
        plan.warnings.append(_NO_FILE)
    elif data is not None and prof is None:
        plan.warnings.append(_NO_ELE)
    return plan, prof


def _view(strategy: RaceStrategy, goal: Goal, today: date) -> RaceView:
    plan, prof = _compute(strategy, goal, today)
    return RaceView(
        goal_id=goal.id,
        goal_type=goal.type,
        race_date=goal.race_date,
        settings=RaceSettings.model_validate_json(strategy.settings_json),
        basis_date=RaceBasis.model_validate_json(strategy.basis_json).captured_on,
        profile=_downsample(prof) if prof else None,
        plan=plan,
        workout_id=strategy.garmin_workout_id,
        export_error=strategy.export_error,
    )


def _get_or_create(repo: Repo, garmin: GarminPort, goal: Goal) -> RaceStrategy:
    strategy = repo.race_strategy(goal.id)
    if strategy is not None:
        return strategy
    settings = RaceSettings(aid_stations=_stations_from_gpx(goal))
    return repo.add(
        RaceStrategy(
            goal_id=goal.id,
            settings_json=settings.model_dump_json(),
            basis_json=_capture_basis(garmin).model_dump_json(),
        )
    )


def get_race_view(repo: Repo, garmin: GarminPort, goal_id: int) -> RaceView:
    """Stratégie de l'objectif actif, créée à la première lecture."""
    goal = _get_goal(repo, goal_id)
    return _view(_get_or_create(repo, garmin, goal), goal, garmin.today())


def save_settings(repo: Repo, garmin: GarminPort, goal_id: int, settings: RaceSettings) -> RaceView:
    """Enregistre les réglages (ravitos triés par km) après vérification contre le plan."""
    goal = _get_goal(repo, goal_id)
    strategy = _get_or_create(repo, garmin, goal)
    settings = settings.model_copy(update={"aid_stations": sorted(settings.aid_stations, key=lambda s: s.km)})
    strategy.settings_json = settings.model_dump_json()
    _compute(strategy, goal, garmin.today())  # refuse les réglages incohérents avant d'enregistrer
    strategy = repo.update(strategy)
    return _view(strategy, goal, garmin.today())



def refresh_basis(repo: Repo, garmin: GarminPort, goal_id: int) -> RaceView:
    """Recapture la base de calcul depuis Garmin."""
    goal = _get_goal(repo, goal_id)
    strategy = _get_or_create(repo, garmin, goal)
    strategy.basis_json = _capture_basis(garmin).model_dump_json()
    return _view(repo.update(strategy), goal, garmin.today())


def reimport_stations(repo: Repo, garmin: GarminPort, goal_id: int) -> RaceView:
    """Remplace les ravitos par les waypoints du GPX."""
    goal = _get_goal(repo, goal_id)
    strategy = _get_or_create(repo, garmin, goal)
    settings = RaceSettings.model_validate_json(strategy.settings_json)
    settings.aid_stations = _stations_from_gpx(goal)
    strategy.settings_json = settings.model_dump_json()
    return _view(repo.update(strategy), goal, garmin.today())


def race_plan_for(repo: Repo, goal: Goal, today: date) -> RacePlan | None:
    """Plan de course de l'objectif, ou None s'il n'a pas de stratégie."""
    strategy = repo.race_strategy(goal.id)
    return None if strategy is None else _compute(strategy, goal, today)[0]
