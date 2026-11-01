"""Stratégie du jour J : création, réglages et lecture du plan de course."""

import hashlib
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from coach.analysis.gpx import _NO_ELE, ProfilePoint, profile, waypoints
from coach.analysis.race_plan import AidStation, RaceBasis, RacePlan, RaceSettings, build_race_plan
from coach.export.garmin_workout import race_to_workout_json
from coach.garmin.port import GarminAuthRequired, GarminPort, GarminRateLimited, GarminUnavailable
from coach.llm.prompts import race_text
from coach.plan.models import Goal, RaceStrategy
from coach.plan.repo import Repo
from coach.services import CoachError
from coach.services.context import zones_from_metrics
from coach.services.plans import _get_goal

MAX_PROFILE_POINTS = 500
_GARMIN_ERRORS = (GarminUnavailable, GarminAuthRequired, GarminRateLimited)
_NO_FILE = "Fichier GPX introuvable : découpage sans profil"
_IGNORED = "Ravito « {} » au-delà de la distance : ignoré"
_TOO_FAST = "Temps visé invraisemblable : allure moyenne plus rapide que 2:30/km (format attendu h:mm, ex. 3:45)"
_MIN_PACE_S_KM = 150
_NAME_MAX = 60


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
    export_stale: bool  # plan modifié (réglages ou base) depuis le dernier envoi à la montre


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
    return [
        AidStation(km=w.km, name=(w.name or "").strip()[:_NAME_MAX] or "Ravito", kind="complet", stop_min=3)
        for w in waypoints(data)
    ]


def _fmt_km(km: float) -> str:
    """Kilométrage à la française, deux décimales au plus : 10.0872 → « 10,09 »."""
    return f"{round(km, 2):g}".replace(".", ",")


def _fingerprint(strategy: RaceStrategy) -> str:
    """Empreinte des réglages et de la base : change dès que le plan envoyé est périmé."""
    return hashlib.sha256(f"{strategy.settings_json}|{strategy.basis_json}".encode()).hexdigest()


def _downsample(points: list[ProfilePoint]) -> list[tuple[float, float]]:
    """Au plus MAX_PROFILE_POINTS points, régulièrement espacés, premier et dernier compris."""
    n = len(points)
    if n <= MAX_PROFILE_POINTS:
        idx = range(n)
    else:
        idx = [round(i * (n - 1) / (MAX_PROFILE_POINTS - 1)) for i in range(MAX_PROFILE_POINTS)]
    return [(points[i].km, points[i].ele_m) for i in idx]


def _compute(
    strategy: RaceStrategy, goal: Goal, today: date, *, strict: bool = False
) -> tuple[RacePlan, list[ProfilePoint] | None]:
    """Plan de course ; un ravito au-delà de la distance est refusé (`strict`) ou ignoré avec un avertissement."""
    settings = RaceSettings.model_validate_json(strategy.settings_json)
    basis = RaceBasis.model_validate_json(strategy.basis_json)
    data = _read_gpx(goal)
    prof = profile(data) if data is not None else None
    distance = prof[-1].km if prof else goal.distance_km
    beyond = [st for st in settings.aid_stations if st.km >= distance]
    if strict and beyond:
        st = beyond[0]
        raise CoachError(
            f"Le ravito « {st.name} » (km {_fmt_km(st.km)}) dépasse la distance du parcours ({_fmt_km(distance)} km)"
        )
    if beyond:
        kept = [st for st in settings.aid_stations if st.km < distance]
        settings = settings.model_copy(update={"aid_stations": kept})
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
    if strict and settings.target_time_s is not None and settings.target_time_s < _MIN_PACE_S_KM * distance:
        raise CoachError(_TOO_FAST)
    plan.warnings.extend(_IGNORED.format(st.name) for st in beyond)
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
        export_stale=strategy.garmin_workout_id is not None and strategy.exported_hash != _fingerprint(strategy),
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
    _compute(strategy, goal, garmin.today(), strict=True)  # refuse les réglages incohérents avant d'enregistrer
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


def race_line_for_prompt(repo: Repo, goal: Goal, today: date) -> str | None:
    """Ligne « Stratégie jour J » pour Claude ; None sans stratégie ni si elle est devenue incohérente."""
    try:
        plan = race_plan_for(repo, goal, today)
    except CoachError:
        return None  # une stratégie cassée ne doit jamais empêcher la génération ni la synchro
    return None if plan is None else race_text(plan)


# --- export vers la montre -------------------------------------------------------------------

_NO_REFERENCE = "Pas de temps de référence : saisis un temps visé"


def _cleanup_old(repo: Repo, garmin: GarminPort, strategy: RaceStrategy) -> RaceStrategy:
    """Supprime les anciens ids Garmin en attente ; chaque id est effacé dès qu'il est traité."""
    if strategy.pending_old_schedule_id is not None:
        garmin.unschedule(strategy.pending_old_schedule_id)
        strategy.pending_old_schedule_id = None
        strategy = repo.update(strategy)
    if strategy.pending_old_workout_id is not None:
        garmin.delete_workout(strategy.pending_old_workout_id)
        strategy.pending_old_workout_id = None
        strategy = repo.update(strategy)
    return strategy


def _upload_and_schedule(garmin: GarminPort, workout: dict, d: date) -> tuple[int, int]:
    """Upload puis planifie ; si la planification échoue, supprime le workout téléversé."""
    workout_id = garmin.upload_workout(workout)
    try:
        return workout_id, garmin.schedule(workout_id, d)
    except Exception:
        try:
            garmin.delete_workout(workout_id)
        except _GARMIN_ERRORS:
            pass  # meilleur effort : on remonte l'erreur d'origine
        raise


def export_race(repo: Repo, garmin: GarminPort, goal_id: int) -> RaceView:
    """Envoie le plan sur la montre, programmé le jour de la course ; remplace l'export précédent.

    Le nouveau workout est envoyé et programmé avant de retirer l'ancien ; si ce retrait échoue,
    ses ids sont gardés dans `pending_old_*` et retentés au prochain export.
    """
    goal = _get_goal(repo, goal_id)
    strategy = _get_or_create(repo, garmin, goal)
    plan, _ = _compute(strategy, goal, garmin.today())
    if plan.reference_time_s is None:
        raise CoachError(_NO_REFERENCE)
    workout = race_to_workout_json(plan, name=f"Jour J – {goal.distance_km:g} km")
    try:
        strategy = _cleanup_old(repo, garmin, strategy)
        workout_id, schedule_id = _upload_and_schedule(garmin, workout, goal.race_date)
    except _GARMIN_ERRORS as e:
        strategy.export_error = f"Export Garmin échoué : {e}"
        repo.update(strategy)
        raise
    strategy.pending_old_workout_id = strategy.garmin_workout_id
    strategy.pending_old_schedule_id = strategy.garmin_schedule_id
    strategy.garmin_workout_id, strategy.garmin_schedule_id = workout_id, schedule_id
    strategy.export_error = None
    strategy.exported_hash = _fingerprint(strategy)
    strategy = repo.update(strategy)
    try:
        strategy = _cleanup_old(repo, garmin, strategy)
    except _GARMIN_ERRORS:
        pass  # ids conservés dans pending_old_* : retentés au prochain export
    return _view(strategy, goal, garmin.today())
