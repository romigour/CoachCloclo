from datetime import date, timedelta
from pathlib import Path

import pytest

from coach.garmin.port import FakeGarminClient, Metrics
from coach.llm.provider import FakeLLMProvider, LLMInvalidResponse
from coach.plan.models import Goal
from coach.services import CoachError
from coach.services.context import refresh_snapshot
from coach.services.plans import GoalError, GoalInput, accept_plan, create_goal, generate_plan
from tests.llm.factories import valid_plan_json
from tests.plan.factories import make_db_session

FIXTURES = Path(__file__).parent.parent / "fixtures" / "gpx"
METRICS = Metrics(hr_max=190, hr_rest=50, threshold_pace_s_km=300)


@pytest.fixture
def fake_garmin():
    return FakeGarminClient(metrics=METRICS)


def goal_input(**overrides) -> GoalInput:
    gpx = overrides.pop("gpx", None)
    data = {
        "type": "trail",
        "distance_km": 42,
        "d_plus_m": 2000,
        "race_date": date(2027, 2, 7),  # 14 semaines depuis le 2026-11-02
        "sessions_per_week": 3,
        "gpx": gpx.read_bytes() if gpx else None,
    }
    data.update(overrides)
    return GoalInput(**data)


def _goal(repo, fake_garmin) -> Goal:
    return create_goal(repo, fake_garmin, goal_input())


def test_race_too_close_rejected(repo, fake_garmin):
    with pytest.raises(GoalError, match="au moins 14 jours"):
        create_goal(repo, fake_garmin, goal_input(race_date=fake_garmin.today() + timedelta(days=10)))


def test_race_in_past_rejected(repo, fake_garmin):
    with pytest.raises(GoalError):
        create_goal(repo, fake_garmin, goal_input(race_date=fake_garmin.today() - timedelta(days=3)))
    assert repo.active_goal() is None


def test_gpx_dplus_used_when_not_given(repo, coach_home, fake_garmin):
    g = create_goal(repo, fake_garmin, goal_input(d_plus_m=0, gpx=FIXTURES / "climb.gpx"))
    assert g.d_plus_m == pytest.approx(600, abs=30)
    assert (coach_home / "gpx" / f"{g.id}.gpx").exists()
    assert g.gpx_summary_json and g.gpx_path


def test_given_dplus_kept_with_gpx(repo, coach_home, fake_garmin):
    g = create_goal(repo, fake_garmin, goal_input(d_plus_m=1500, gpx=FIXTURES / "climb.gpx"))
    assert g.d_plus_m == 1500


def test_plan_start_is_monday(repo, fake_garmin):
    assert _goal(repo, fake_garmin).plan_start == date(2026, 11, 2)


def test_generate_plan_persists_sessions(repo, fake_garmin):
    goal = _goal(repo, fake_garmin)
    llm = FakeLLMProvider([valid_plan_json(n_weeks=14, per_week=3)])
    plan = generate_plan(repo, fake_garmin, llm, goal.id)
    sessions = repo.sessions(goal.id)
    assert len(plan.weeks) == 14
    assert len(sessions) == 42 and all(s.status == "todo" for s in sessions)
    assert repo.latest_snapshot().hr_max == 190


def test_generate_plan_invalid_twice_raises_and_persists_nothing(repo, fake_garmin):
    goal = _goal(repo, fake_garmin)
    with pytest.raises(LLMInvalidResponse):
        generate_plan(repo, fake_garmin, FakeLLMProvider(["{}", "{}"]), goal.id)
    assert repo.sessions(goal.id) == []


def test_regenerate_replaces_todo_and_resets_accepted(repo, fake_garmin):
    goal = _goal(repo, fake_garmin)
    generate_plan(repo, fake_garmin, FakeLLMProvider([valid_plan_json(14, 3)]), goal.id)
    accept_plan(repo, goal.id)
    assert repo.active_goal().plan_accepted is True
    generate_plan(repo, fake_garmin, FakeLLMProvider([valid_plan_json(14, 2)]), goal.id)
    assert len(repo.sessions(goal.id)) == 28
    assert repo.active_goal().plan_accepted is False


def test_new_goal_archives_previous(repo, fake_garmin):
    old = _goal(repo, fake_garmin)
    todo = repo.add(make_db_session(old.id, week_index=1, order=1))
    exported = make_db_session(old.id, week_index=1, order=2)
    exported.status = "exported"
    exported = repo.add(exported)
    new = _goal(repo, fake_garmin)
    assert repo.active_goal().id == new.id
    with repo.transaction() as db:
        assert db.get(Goal, old.id).status == "archived"
    remaining = [s.id for s in repo.sessions(old.id)]
    assert remaining == [exported.id] and todo.id not in remaining


def test_refresh_snapshot_without_hr_max(repo):
    with pytest.raises(CoachError, match="FC max inconnue"):
        refresh_snapshot(repo, FakeGarminClient(metrics=Metrics()))
