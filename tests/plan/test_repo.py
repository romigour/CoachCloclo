from datetime import date

import pytest

from coach.llm.schemas import RepeatSpec, StepSpec
from coach.plan.models import Activity, AthleteSnapshot, Proposal, Session
from tests.llm.factories import make_session
from tests.plan.factories import make_db_session, make_goal


def test_session_spec_roundtrip(repo):
    spec = make_session(week_index=2)
    s = repo.add(Session.from_spec(spec, goal_id=1))
    assert repo.session(s.id).to_spec() == spec
    assert s.status == "todo" and s.scheduled_date is None


def test_session_spec_roundtrip_with_repeat(repo):
    spec = make_session(
        type="VMA",
        steps=[
            StepSpec(kind="warmup", duration_s=600, zone="Z2"),
            RepeatSpec(
                repeat=5,
                steps=[
                    StepSpec(kind="active", duration_s=120, zone="Z5"),
                    StepSpec(kind="recovery", duration_s=90, zone="Z1"),
                ],
            ),
        ],
    )
    s = repo.add(Session.from_spec(spec, goal_id=1))
    assert repo.session(s.id).to_spec() == spec


def test_single_pending_proposal(repo):
    repo.add(Proposal(status="pending", analysis="a", changes_json="[]"))
    assert repo.pending_proposal().analysis == "a"


def test_no_pending_proposal(repo):
    repo.add(Proposal(status="rejected", analysis="a"))
    assert repo.pending_proposal() is None


def test_active_goal_ignores_archived(repo):
    assert repo.active_goal() is None
    repo.add(make_goal(status="archived"))
    assert repo.active_goal() is None
    g = repo.add(make_goal())
    assert repo.active_goal().id == g.id


def test_sessions_ordered_and_filtered(repo):
    for week, order in [(2, 1), (1, 2), (1, 1)]:
        repo.add(make_db_session(1, week_index=week, order=order))
    repo.add(make_db_session(2, week_index=1, order=1))
    assert [(s.week_index, s.order) for s in repo.sessions(1)] == [(1, 1), (1, 2), (2, 1)]
    assert [s.order for s in repo.sessions(1, week_index=1)] == [1, 2]


def test_session_missing_raises(repo):
    with pytest.raises(KeyError):
        repo.session(999)


def test_update_persists(repo):
    s = repo.add(make_db_session(1))
    s.status = "exported"
    s.garmin_workout_id = 42
    repo.update(s)
    got = repo.session(s.id)
    assert got.status == "exported" and got.garmin_workout_id == 42


def test_activities(repo):
    repo.add(Activity(garmin_activity_id=1, date=date(2026, 11, 1), type_key="running"))
    repo.add(Activity(garmin_activity_id=2, date=date(2026, 11, 5), type_key="running"))
    assert [a.garmin_activity_id for a in repo.activities_since(date(2026, 11, 2))] == [2]
    assert repo.activity_by_garmin_id(1).date == date(2026, 11, 1)
    assert repo.activity_by_garmin_id(3) is None


def test_latest_snapshot(repo):
    assert repo.latest_snapshot() is None
    repo.add(AthleteSnapshot(date=date(2026, 10, 1), vo2max=50))
    repo.add(AthleteSnapshot(date=date(2026, 10, 20), vo2max=52))
    assert repo.latest_snapshot().vo2max == 52


def test_transaction_commits(repo):
    with repo.transaction() as db:
        db.add(Proposal(analysis="x"))
    assert repo.pending_proposal() is not None


def test_transaction_rolls_back(repo):
    with pytest.raises(RuntimeError):
        with repo.transaction() as db:
            db.add(Proposal(analysis="x"))
            db.flush()
            raise RuntimeError("boom")
    assert repo.pending_proposal() is None


def test_upsert_race_creates_then_updates(repo):
    from coach.plan.models import Race

    repo.upsert_race(5, {"official_time_s": 3000})
    repo.upsert_race(5, {"official_time_s": 2950})
    races = repo.races()
    assert len(races) == 1 and isinstance(races[0], Race)
    assert races[0].official_time_s == 2950


def test_exclude_race_keeps_fields(repo):
    repo.upsert_race(5, {"name": "10 km de Rennes"})
    repo.exclude_race(5)
    race = repo.races()[0]
    assert race.excluded is True and race.name == "10 km de Rennes"
    assert repo.upsert_race(5, {"official_time_s": 3000}).excluded is False
    assert repo.races()[0].name == "10 km de Rennes"


def test_exclude_race_creates_when_absent(repo):
    repo.exclude_race(9)
    assert repo.races()[0].excluded is True


def test_replace_records_replaces_all(repo):
    from coach.plan.models import PersonalRecord

    repo.replace_records([PersonalRecord(kind="5k", value=1500.0), PersonalRecord(kind="10k", value=3100.0)])
    repo.replace_records([PersonalRecord(kind="half", value=7000.0)])
    assert [r.kind for r in repo.records()] == ["half"]


def test_has_activities(repo):
    assert repo.has_activities() is False
    repo.add(Activity(garmin_activity_id=1, date=date(2026, 1, 1), type_key="running"))
    assert repo.has_activities() is True
    assert len(repo.all_activities()) == 1
    assert repo.activity(repo.all_activities()[0].id).garmin_activity_id == 1
    with pytest.raises(KeyError):
        repo.activity(999)
