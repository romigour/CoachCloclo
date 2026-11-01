from datetime import date
from pathlib import Path

import pytest

from coach.analysis.race_plan import AidStation, RaceSettings
from coach.garmin.port import FakeGarminClient, GarminUnavailable, Metrics
from coach.services import CoachError
from coach.services.plans import GoalError, GoalInput, create_goal
from coach.services.race_strategy import (
    export_race,
    get_race_view,
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
    saved = save_settings(repo, garmin, goal.id, RaceSettings(target_time_s=3600, aid_stations=stations))
    assert [s.name for s in saved.settings.aid_stations] == ["A", "B"]
    view = get_race_view(repo, garmin, goal.id)
    assert view.settings.target_time_s == 3600
    assert [s.name for s in view.settings.aid_stations] == ["A", "B"]


def test_station_beyond_gpx_distance_rejected(repo, coach_home, garmin):
    goal = make_goal(repo, garmin, distance_km=9)
    save_settings(repo, garmin, goal.id, RaceSettings(aid_stations=[AidStation(km=9.5, name="X")]))
    with pytest.raises(CoachError, match="distance"):
        save_settings(repo, garmin, goal.id, RaceSettings(aid_stations=[AidStation(km=10.5, name="X")]))


def test_target_below_stops_rejected(repo, coach_home, garmin):
    goal = make_goal(repo, garmin)
    settings = RaceSettings(target_time_s=60, aid_stations=[AidStation(km=5, name="X", stop_min=3)])
    with pytest.raises(CoachError, match="arrêts"):
        save_settings(repo, garmin, goal.id, settings)


def test_refresh_updates_basis(repo, coach_home, garmin):
    goal = make_goal(repo, garmin)
    before = get_race_view(repo, garmin, goal.id).plan.predicted_time_s
    garmin._metrics = Metrics(hr_max=190, hr_rest=50, pred_10k_s=2400)
    after = refresh_basis(repo, garmin, goal.id).plan.predicted_time_s
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
