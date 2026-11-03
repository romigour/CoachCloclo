from datetime import date, timedelta
from pathlib import Path

import pytest

from coach.analysis.race_plan import AidStation, RaceSettings
from coach.garmin.port import FakeGarminClient, GarminUnavailable, Metrics
from coach.services import CoachError
from coach.services.plans import GoalError, GoalInput, create_goal
from coach.services.race_strategy import (
    export_race,
    get_race_view,
    race_line_for_prompt,
    race_plan_for,
    refresh_basis,
    reimport_stations,
    save_settings,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "gpx"
METRICS = Metrics(hr_max=190, hr_rest=50, pred_10k_s=2880)


class CountingGarmin(FakeGarminClient):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.metrics_reads = 0

    def metrics(self):
        self.metrics_reads += 1
        return super().metrics()


@pytest.fixture
def garmin():
    return CountingGarmin(metrics=METRICS)


def make_goal(repo, garmin, *, kind="trail", distance_km=10, gpx="trail_wpt.gpx"):
    data = GoalInput(
        type=kind,
        distance_km=distance_km,
        d_plus_m=300,
        race_date=date(2027, 2, 7),
        sessions_per_week=3,
        gpx=(FIXTURES / gpx).read_bytes() if gpx else None,
    )
    return create_goal(repo, garmin, data)


def set_target(repo, goal, seconds, source="user"):
    goal.target_time_s, goal.target_source = seconds, source
    return repo.update(goal)


def test_first_read_creates_with_waypoints(repo, coach_home, garmin):
    goal = make_goal(repo, garmin)
    view = get_race_view(repo, garmin, goal.id)
    assert view.settings.aid_stations[0].name == "Ravito Col"
    assert view.settings.aid_stations[0].kind == "complet"
    assert view.settings.aid_stations[0].stop_min == 3
    assert view.basis_date == garmin.today()
    assert view.goal_type == "trail"
    assert view.profile and len(view.profile) <= 500
    get_race_view(repo, garmin, goal.id)
    assert garmin.metrics_reads == 1


def test_route_goal_has_no_stations(repo, coach_home, garmin):
    goal = make_goal(repo, garmin, kind="route")
    assert get_race_view(repo, garmin, goal.id).settings.aid_stations == []


def test_save_then_read(repo, coach_home, garmin):
    goal = make_goal(repo, garmin)
    get_race_view(repo, garmin, goal.id)
    stations = [AidStation(km=7, name="B"), AidStation(km=3, name="A")]
    saved = save_settings(repo, garmin, goal.id, RaceSettings(aid_stations=stations))
    assert [s.name for s in saved.settings.aid_stations] == ["A", "B"]
    view = get_race_view(repo, garmin, goal.id)
    assert [s.name for s in view.settings.aid_stations] == ["A", "B"]


def test_station_beyond_gpx_distance_rejected(repo, coach_home, garmin):
    goal = make_goal(repo, garmin, distance_km=9)
    save_settings(repo, garmin, goal.id, RaceSettings(aid_stations=[AidStation(km=9.5, name="X")]))
    with pytest.raises(CoachError, match="distance"):
        save_settings(repo, garmin, goal.id, RaceSettings(aid_stations=[AidStation(km=10.5, name="X")]))


def test_target_below_stops_rejected(repo, coach_home, garmin):
    goal = make_goal(repo, garmin)
    set_target(repo, goal, 60)
    settings = RaceSettings(aid_stations=[AidStation(km=5, name="X", stop_min=3)])
    with pytest.raises(CoachError, match="arrêts"):
        save_settings(repo, garmin, goal.id, settings)


def test_refresh_updates_basis(repo, coach_home, garmin):
    goal = make_goal(repo, garmin)
    before = get_race_view(repo, garmin, goal.id).plan.reference_time_s  # sans temps visé : repli sur la prédiction
    garmin._metrics = Metrics(hr_max=190, hr_rest=50, pred_10k_s=2400)
    after = refresh_basis(repo, garmin, goal.id).plan.reference_time_s
    assert after != before


def test_reimport_replaces_stations(repo, coach_home, garmin):
    goal = make_goal(repo, garmin)
    save_settings(repo, garmin, goal.id, RaceSettings(aid_stations=[AidStation(km=2, name="Perso")]))
    view = reimport_stations(repo, garmin, goal.id)
    assert [s.name for s in view.settings.aid_stations] == ["Ravito Col"]


def test_missing_gpx_file_warns(repo, coach_home, garmin):
    goal = make_goal(repo, garmin)
    Path(goal.gpx_path).unlink()
    view = get_race_view(repo, garmin, goal.id)
    assert "Fichier GPX introuvable : découpage sans profil" in view.plan.warnings
    assert view.profile is None


def test_archived_goal_rejected(repo, coach_home, garmin):
    first = make_goal(repo, garmin)
    make_goal(repo, garmin)
    with pytest.raises(GoalError):
        get_race_view(repo, garmin, first.id)


def test_race_plan_for_none_without_strategy(repo, coach_home, garmin):
    goal = make_goal(repo, garmin)
    assert race_plan_for(repo, goal, garmin.today()) is None
    get_race_view(repo, garmin, goal.id)
    assert race_plan_for(repo, goal, garmin.today()) is not None


def test_export_schedules_on_race_day(repo, coach_home, garmin):
    goal = make_goal(repo, garmin)
    view = export_race(repo, garmin, goal.id)
    assert view.workout_id in garmin.workouts
    assert garmin.schedules[next(iter(garmin.schedules))] == (view.workout_id, goal.race_date)
    assert garmin.workouts[view.workout_id]["workoutName"] == "Jour J – 10 km"
    assert view.export_error is None


def test_reexport_replaces_old(repo, coach_home, garmin):
    goal = make_goal(repo, garmin)
    first = export_race(repo, garmin, goal.id)
    second = export_race(repo, garmin, goal.id)
    assert second.workout_id != first.workout_id
    assert list(garmin.workouts) == [second.workout_id]
    assert len(garmin.schedules) == 1


def test_reexport_old_already_deleted(repo, coach_home, garmin):
    goal = make_goal(repo, garmin)
    first = export_race(repo, garmin, goal.id)
    garmin.fail_on = {"delete_workout"}
    second = export_race(repo, garmin, goal.id)
    assert repo.race_strategy(goal.id).pending_old_workout_id == first.workout_id
    garmin.fail_on = set()
    third = export_race(repo, garmin, goal.id)
    strategy = repo.race_strategy(goal.id)
    assert strategy.pending_old_workout_id is None and strategy.pending_old_schedule_id is None
    assert list(garmin.workouts) == [third.workout_id] and second.workout_id not in garmin.workouts


def test_export_failure_keeps_old(repo, coach_home, garmin):
    goal = make_goal(repo, garmin)
    first = export_race(repo, garmin, goal.id)
    garmin.fail_on = {"upload_workout"}
    with pytest.raises(GarminUnavailable):
        export_race(repo, garmin, goal.id)
    strategy = repo.race_strategy(goal.id)
    assert strategy.export_error and strategy.garmin_workout_id == first.workout_id
    assert list(garmin.workouts) == [first.workout_id]


def test_export_without_reference_time(repo, coach_home, garmin):
    goal = make_goal(repo, garmin)
    garmin._metrics = Metrics(hr_max=190, hr_rest=50)
    refresh_basis(repo, garmin, goal.id)
    with pytest.raises(CoachError, match="Pas de temps de référence"):
        export_race(repo, garmin, goal.id)


def test_race_line_for_prompt(repo, coach_home, garmin):
    goal = make_goal(repo, garmin)
    assert race_line_for_prompt(repo, goal, garmin.today()) is None
    get_race_view(repo, garmin, goal.id)
    assert race_line_for_prompt(repo, goal, garmin.today()).startswith("Stratégie jour J")


def test_race_line_for_prompt_ignores_broken_strategy(repo, coach_home, garmin):
    goal = make_goal(repo, garmin)
    get_race_view(repo, garmin, goal.id)
    strategy = repo.race_strategy(goal.id)
    strategy.settings_json = RaceSettings(aid_stations=[AidStation(km=5, name="X", stop_min=3)]).model_dump_json()
    repo.update(strategy)
    goal = set_target(repo, goal, 60)
    with pytest.raises(CoachError):
        race_plan_for(repo, goal, garmin.today())
    assert race_line_for_prompt(repo, goal, garmin.today()) is None


LONG_NAME = "Ravitaillement complet - Refuge de la Croix du Bonhomme (barriere 14h30)"


def test_long_waypoint_name_truncated(repo, coach_home, garmin):
    gpx = (FIXTURES / "trail_wpt.gpx").read_bytes().replace(b"Ravito Col", LONG_NAME.encode())
    data = GoalInput(type="trail", distance_km=10, d_plus_m=300, race_date=date(2027, 2, 7),
                     sessions_per_week=3, gpx=gpx)
    goal = create_goal(repo, garmin, data)
    assert get_race_view(repo, garmin, goal.id).settings.aid_stations[0].name == LONG_NAME[:60]
    assert reimport_stations(repo, garmin, goal.id).settings.aid_stations[0].name == LONG_NAME[:60]


def test_station_beyond_distance_message_in_french(repo, coach_home, garmin):
    goal = make_goal(repo, garmin)
    with pytest.raises(CoachError) as exc:
        save_settings(repo, garmin, goal.id, RaceSettings(aid_stations=[AidStation(km=10.5, name="X")]))
    assert "(km 10,5)" in str(exc.value) and "(10,01 km)" in str(exc.value)


def test_station_beyond_distance_ignored_on_read(repo, coach_home, garmin):
    goal = make_goal(repo, garmin, distance_km=9)
    save_settings(repo, garmin, goal.id, RaceSettings(aid_stations=[AidStation(km=9.5, name="X")]))
    Path(goal.gpx_path).unlink()
    view = get_race_view(repo, garmin, goal.id)
    assert "Ravito « X » au-delà de la distance : ignoré" in view.plan.warnings
    assert view.plan.aid_passages == [] and [s.name for s in view.settings.aid_stations] == ["X"]
    with pytest.raises(CoachError, match="dépasse"):
        save_settings(repo, garmin, goal.id, view.settings)


def test_export_stale_after_changes(repo, coach_home, garmin):
    goal = make_goal(repo, garmin)
    assert get_race_view(repo, garmin, goal.id).export_stale is False
    view = export_race(repo, garmin, goal.id)
    assert view.export_stale is False
    assert get_race_view(repo, garmin, goal.id).export_stale is False
    assert save_settings(repo, garmin, goal.id, view.settings).export_stale is False  # réglages identiques
    assert save_settings(repo, garmin, goal.id, RaceSettings(start_time="07:00")).export_stale is True
    assert export_race(repo, garmin, goal.id).export_stale is False
    garmin._metrics = Metrics(hr_max=190, hr_rest=50, pred_10k_s=2400)
    assert refresh_basis(repo, garmin, goal.id).export_stale is True


def test_view_uses_goal_target(repo, coach_home, garmin):
    goal = set_target(repo, make_goal(repo, garmin), 3600, "claude")
    view = get_race_view(repo, garmin, goal.id)
    assert view.plan.target_time_s == 3600 and view.plan.reference_time_s == 3600
    assert (view.target_time_s, view.target_source) == (3600, "claude")


def test_old_settings_with_target_still_load(repo, coach_home, garmin):
    goal = set_target(repo, make_goal(repo, garmin), 3600)
    get_race_view(repo, garmin, goal.id)
    strategy = repo.race_strategy(goal.id)
    strategy.settings_json = '{"target_time_s": 999, "start_time": "08:00"}'
    repo.update(strategy)
    view = get_race_view(repo, garmin, goal.id)
    assert view.plan.target_time_s == 3600 and view.target_time_s == 3600


def test_export_stale_after_goal_date_change(repo, coach_home, garmin):
    goal = make_goal(repo, garmin)
    assert export_race(repo, garmin, goal.id).export_stale is False
    goal.race_date += timedelta(days=7)
    repo.update(goal)
    assert get_race_view(repo, garmin, goal.id).export_stale is True


def test_export_stale_after_goal_target_change(repo, coach_home, garmin):
    goal = make_goal(repo, garmin)
    assert export_race(repo, garmin, goal.id).export_stale is False
    set_target(repo, goal, 3600)
    assert get_race_view(repo, garmin, goal.id).export_stale is True
