import sqlite3
from datetime import date

import pytest

from coach.garmin.port import LapSummary
from coach.llm.schemas import RepeatSpec, StepSpec
from coach.plan.models import Activity, AthleteSnapshot, Goal, Proposal, Session
from coach.plan.repo import Repo, make_engine
from tests.llm.factories import make_session
from tests.plan.factories import make_activity, make_db_session, make_goal


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


def test_laps_absent_then_saved_then_replaced(repo):
    assert repo.laps(1) is None
    repo.save_laps(1, [LapSummary(index=0, duration_s=60, distance_m=200, raw={"x": 1})])
    assert repo.laps(1)[0].distance_m == 200 and repo.laps(1)[0].raw == {}
    repo.save_laps(1, [])
    assert repo.laps(1) == []


def test_activity_of_session(repo):
    a = repo.add(make_activity(session_id=7))
    assert repo.activity_of_session(7).id == a.id and repo.activity_of_session(8) is None


def _old_schema_db(path):
    """Base à l'ancien schéma : table goal sans les colonnes du temps visé, stratégie avec temps."""
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE goal (id INTEGER PRIMARY KEY, created_at DATETIME, type VARCHAR, distance_km FLOAT,
            d_plus_m INTEGER, race_date DATE, sessions_per_week INTEGER, gpx_path VARCHAR,
            gpx_summary_json VARCHAR, status VARCHAR, plan_start DATE, plan_accepted BOOLEAN);
        INSERT INTO goal VALUES (1, '2026-11-01', 'route', 21.1, 0, '2027-02-07', 4, NULL, NULL, 'active', '2026-11-02', 1);
        INSERT INTO goal VALUES (2, '2026-10-01', 'route', 10, 0, '2026-12-07', 3, NULL, NULL, 'archived', '2026-10-05', 1);
        CREATE TABLE racestrategy (id INTEGER PRIMARY KEY, goal_id INTEGER, settings_json VARCHAR,
            basis_json VARCHAR, garmin_workout_id INTEGER, garmin_schedule_id INTEGER,
            pending_old_workout_id INTEGER, pending_old_schedule_id INTEGER, export_error VARCHAR);
        INSERT INTO racestrategy (goal_id, settings_json, basis_json) VALUES (1, '{"target_time_s": 6600}', '{}');
    """)
    con.commit()
    con.close()


def test_migration_adds_columns_and_copies_strategy_target(tmp_path):
    path = tmp_path / "old.db"
    _old_schema_db(path)
    repo = Repo(make_engine(path))
    goal = repo.active_goal()
    assert goal.target_time_s == 6600 and goal.target_source == "user"
    with repo.transaction() as db:
        archived = db.get(Goal, 2)
    assert archived.target_time_s is None and archived.target_source is None


def test_migration_survives_corrupt_strategy_row(tmp_path):
    path = tmp_path / "old.db"
    _old_schema_db(path)
    con = sqlite3.connect(path)
    con.execute("INSERT INTO racestrategy (goal_id, settings_json, basis_json) VALUES (2, 'pas du json', '{}')")
    con.execute("INSERT INTO racestrategy (goal_id, settings_json, basis_json) VALUES (3, '[1]', '{}')")
    con.commit()
    con.close()
    repo = Repo(make_engine(path))
    assert repo.active_goal().target_time_s == 6600


def test_migration_is_idempotent(tmp_path):
    path = tmp_path / "old.db"
    _old_schema_db(path)
    repo = Repo(make_engine(path))
    goal = repo.active_goal()
    goal.target_time_s = 7000
    repo.update(goal)
    assert Repo(make_engine(path)).active_goal().target_time_s == 7000


def test_new_goal_has_no_target(repo):
    g = repo.add(make_goal())
    assert g.target_time_s is None and g.target_source is None
