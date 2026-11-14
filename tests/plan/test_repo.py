import sqlite3
from datetime import date

import pytest

from coach.garmin.port import LapSummary
from coach.llm.schemas import RepeatSpec, StepSpec
from coach.plan.models import Activity, AthleteSnapshot, Event, Goal, Proposal, Session
from coach.plan.repo import Repo, make_engine
from tests.llm.factories import make_session
from tests.plan.factories import make_activity, make_cycle, make_db_session, make_goal


def test_session_spec_roundtrip(repo):
    spec = make_session(week_index=2)
    s = repo.add(Session.from_spec(spec, cycle_id=1))
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
    s = repo.add(Session.from_spec(spec, cycle_id=1))
    assert repo.session(s.id).to_spec() == spec


def test_single_pending_proposal(repo):
    repo.add(Proposal(status="pending", analysis="a", changes_json="[]"))
    assert repo.pending_proposal().analysis == "a"


def test_no_pending_proposal(repo):
    repo.add(Proposal(status="rejected", analysis="a"))
    assert repo.pending_proposal() is None


def test_upcoming_goals_ignores_archived_and_sorts_by_date(repo):
    assert repo.upcoming_goals() == []
    repo.add(make_goal(status="archived"))
    assert repo.upcoming_goals() == []
    late = repo.add(make_goal(race_date=date(2027, 5, 30)))
    soon = repo.add(make_goal(race_date=date(2027, 1, 31)))
    assert [g.id for g in repo.upcoming_goals()] == [soon.id, late.id]


def test_active_cycle_ignores_done(repo):
    assert repo.active_cycle() is None
    repo.add(make_cycle(status="done"))
    assert repo.active_cycle() is None
    c = repo.add(make_cycle())
    assert repo.active_cycle().id == c.id


def test_goals_in_and_horizon(repo):
    cycle = repo.add(make_cycle(plan_start=date(2026, 11, 1), end_date=date(2027, 1, 31)))
    a = repo.add(make_goal(race_date=date(2026, 12, 15)))
    b = repo.add(make_goal(race_date=date(2027, 1, 31)))
    c = repo.add(make_goal(race_date=date(2027, 5, 30)))
    repo.add(make_goal(race_date=date(2026, 12, 20), status="archived"))
    assert [g.id for g in repo.goals_in(cycle)] == [a.id, b.id]
    assert [g.id for g in repo.horizon_goals(cycle)] == [c.id]


def test_new_goal_priority_defaults_to_principal(repo):
    assert repo.add(make_goal()).priority == "principal"


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
    goal = repo.upcoming_goals()[0]
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
    assert repo.upcoming_goals()[0].target_time_s == 6600


def test_migration_is_idempotent(tmp_path):
    path = tmp_path / "old.db"
    _old_schema_db(path)
    repo = Repo(make_engine(path))
    goal = repo.upcoming_goals()[0]
    goal.target_time_s = 7000
    repo.update(goal)
    assert Repo(make_engine(path)).upcoming_goals()[0].target_time_s == 7000


def test_new_goal_has_no_target(repo):
    g = repo.add(make_goal())
    assert g.target_time_s is None and g.target_source is None


_SEVEN_DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def test_goal_defaults_to_all_days(repo):
    goal = repo.add(make_goal())
    assert goal.available_days() == _SEVEN_DAYS
    assert goal.long_run_day is None


def test_migrate_adds_availability_to_old_goal(tmp_path):
    # base 0.5.0 : table goal avec le temps visé mais sans available_days_json / long_run_day
    path = tmp_path / "v050.db"
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE goal (id INTEGER PRIMARY KEY, created_at DATETIME, type VARCHAR, distance_km FLOAT,
            d_plus_m INTEGER, race_date DATE, sessions_per_week INTEGER, gpx_path VARCHAR,
            gpx_summary_json VARCHAR, status VARCHAR, plan_start DATE, plan_accepted BOOLEAN,
            target_time_s INTEGER, target_source VARCHAR);
        INSERT INTO goal VALUES (1, '2026-11-01', 'route', 21.1, 0, '2027-02-07', 4, NULL, NULL, 'active',
            '2026-11-02', 1, 6600, 'user');
    """)
    con.commit()
    con.close()
    repo = Repo(make_engine(path))
    goal = repo.upcoming_goals()[0]
    assert goal.available_days() == _SEVEN_DAYS
    assert goal.long_run_day is None
    assert goal.target_time_s == 6600


def test_migrate_availability_is_idempotent(tmp_path):
    make_engine(tmp_path / "t.db")
    make_engine(tmp_path / "t.db")  # pas d'exception


def test_events_most_recent_first(repo):
    old = repo.add(Event(cycle_id=1, kind="unavailable", start_date=date(2026, 11, 2), end_date=date(2026, 11, 4)))
    new = repo.add(Event(cycle_id=1, kind="unavailable", start_date=date(2026, 11, 9), end_date=date(2026, 11, 10)))
    same = repo.add(Event(cycle_id=1, kind="fatigue", start_date=date(2026, 11, 9), end_date=date(2026, 11, 9)))
    repo.add(Event(cycle_id=2, kind="fatigue", start_date=date(2026, 12, 1), end_date=date(2026, 12, 1)))
    assert [e.id for e in repo.events(1)] == [same.id, new.id, old.id]


def test_event_days_roundtrip(repo):
    e = repo.add(Event(cycle_id=1, kind="light_week", start_date=date(2026, 11, 2), days_json='["mardi", "jeudi"]'))
    assert repo.events(1)[0].days() == ["mardi", "jeudi"]
    assert e.id and Event(cycle_id=1, kind="injury", start_date=date(2026, 11, 2)).days() is None


def test_open_injury(repo):
    assert repo.open_injury(1) is None
    repo.add(Event(cycle_id=1, kind="unavailable", start_date=date(2026, 11, 2), end_date=date(2026, 11, 3)))
    injury = repo.add(Event(cycle_id=1, kind="injury", start_date=date(2026, 11, 5)))
    assert repo.open_injury(1).id == injury.id
    assert repo.open_injury(2) is None
    injury.end_date = date(2026, 11, 12)
    repo.update(injury)
    assert repo.open_injury(1) is None


def test_migrate_adds_sport_and_include_bike_to_0_5_0_db(tmp_path):
    path = tmp_path / "v050.db"
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE goal (id INTEGER PRIMARY KEY, created_at DATETIME, type VARCHAR, distance_km FLOAT,
            d_plus_m INTEGER, race_date DATE, sessions_per_week INTEGER, gpx_path VARCHAR,
            gpx_summary_json VARCHAR, status VARCHAR, plan_start DATE, plan_accepted BOOLEAN,
            target_time_s INTEGER, target_source VARCHAR);
        INSERT INTO goal VALUES (1, '2026-11-01', 'route', 21.1, 0, '2027-02-07', 4, NULL, NULL, 'active',
            '2026-11-02', 1, 6600, 'user');
        CREATE TABLE session (id INTEGER PRIMARY KEY, goal_id INTEGER, week_index INTEGER, "order" INTEGER,
            suggested_day VARCHAR, chaining_note VARCHAR, type VARCHAR, target_kind VARCHAR, title VARCHAR,
            description VARCHAR, steps_json VARCHAR, est_duration_min FLOAT, est_distance_km FLOAT,
            status VARCHAR, scheduled_date DATE, garmin_workout_id INTEGER, garmin_schedule_id INTEGER,
            sync_error VARCHAR, pending_old_workout_id INTEGER, pending_old_schedule_id INTEGER,
            pending_removal BOOLEAN);
        INSERT INTO session VALUES (1, 1, 1, 1, 'mardi', NULL, 'EF', 'hr', 't', 'd', '[]', NULL, NULL,
            'todo', NULL, NULL, NULL, NULL, NULL, NULL, 0);
    """)
    con.commit()
    con.close()
    repo = Repo(make_engine(path))
    assert repo.upcoming_goals()[0].include_bike is False
    assert repo.sessions(1)[0].sport == "run"


_OLD_SESSION_EVENT = """
    CREATE TABLE session (id INTEGER PRIMARY KEY, goal_id INTEGER, week_index INTEGER, "order" INTEGER,
        suggested_day VARCHAR, chaining_note VARCHAR, type VARCHAR, target_kind VARCHAR, title VARCHAR,
        description VARCHAR, steps_json VARCHAR, est_duration_min FLOAT, est_distance_km FLOAT,
        status VARCHAR, scheduled_date DATE, garmin_workout_id INTEGER, garmin_schedule_id INTEGER,
        sync_error VARCHAR, pending_old_workout_id INTEGER, pending_old_schedule_id INTEGER,
        pending_removal BOOLEAN);
    CREATE TABLE event (id INTEGER PRIMARY KEY, goal_id INTEGER, created_at DATETIME, kind VARCHAR,
        start_date DATE, end_date DATE, max_sessions INTEGER, days_json VARCHAR, session_id INTEGER,
        note VARCHAR);
"""


def _old_db_with_plan(path):
    """Ancienne base : objectif actif 7 (plan accepté, 4 séances/sem, sortie longue le dimanche) et archivé 3."""
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE goal (id INTEGER PRIMARY KEY, created_at DATETIME, type VARCHAR, distance_km FLOAT,
            d_plus_m INTEGER, race_date DATE, sessions_per_week INTEGER, gpx_path VARCHAR,
            gpx_summary_json VARCHAR, status VARCHAR, plan_start DATE, plan_accepted BOOLEAN,
            target_time_s INTEGER, target_source VARCHAR, available_days_json VARCHAR NOT NULL DEFAULT '[]',
            long_run_day VARCHAR, include_bike BOOLEAN NOT NULL DEFAULT 0);
        INSERT INTO goal VALUES (7, '2026-11-01', 'trail', 42, 2000, '2027-01-31', 4, NULL, NULL, 'active',
            '2026-11-02', 1, NULL, NULL, '["mardi", "dimanche"]', 'dimanche', 1);
        INSERT INTO goal VALUES (3, '2026-06-01', 'route', 10, 0, '2026-09-06', 3, NULL, NULL, 'archived',
            '2026-07-01', 1, NULL, NULL, '[]', NULL, 0);
        """
        + _OLD_SESSION_EVENT
        + """
        INSERT INTO session VALUES (1, 7, 1, 1, 'mardi', NULL, 'EF', 'hr', 't', 'd', '[]', NULL, NULL,
            'exported', NULL, NULL, NULL, NULL, NULL, NULL, 0);
        INSERT INTO event (id, goal_id, created_at, kind, start_date) VALUES (1, 7, '2026-11-05', 'injury', '2026-11-05');
        """
    )
    con.commit()
    con.close()


def test_migration_moves_goal_plan_to_cycle(tmp_path):
    path = tmp_path / "old.db"
    _old_db_with_plan(path)
    repo = Repo(make_engine(path))
    cycle = repo.active_cycle()
    assert cycle.id == 7 and cycle.plan_accepted and cycle.sessions_per_week == 4
    assert cycle.end_date == date(2027, 1, 31) and cycle.long_run_day == "dimanche"
    assert cycle.include_bike and cycle.available_days() == ["mardi", "dimanche"]
    assert [s.status for s in repo.sessions(7)] == ["exported"]
    assert repo.open_injury(7) is not None
    assert repo.upcoming_goals()[0].priority == "principal"


def test_migration_archived_goal_gets_done_cycle(tmp_path):
    path = tmp_path / "old.db"
    _old_db_with_plan(path)
    repo = Repo(make_engine(path))
    with repo.transaction() as db:
        from coach.plan.models import Cycle

        done = db.get(Cycle, 3)
    assert done.status == "done" and done.end_date == date(2026, 9, 6)


def test_migration_cycle_is_idempotent(tmp_path):
    path = tmp_path / "old.db"
    _old_db_with_plan(path)
    make_engine(path)
    engine = make_engine(path)
    with engine.connect() as conn:
        from sqlalchemy import text

        assert conn.execute(text("SELECT COUNT(*) FROM cycle")).scalar() == 2
    assert [s.status for s in Repo(engine).sessions(7)] == ["exported"]


def _count_cycles(engine):
    from sqlalchemy import text

    with engine.connect() as conn:
        return conn.execute(text("SELECT COUNT(*) FROM cycle")).scalar()


def test_migration_does_not_backfill_cycles_on_later_startups(tmp_path):
    path = tmp_path / "old.db"
    _old_db_with_plan(path)
    repo = Repo(make_engine(path))
    before = repo.active_cycle().id
    repo.add(make_goal(race_date=date(2027, 5, 30)))  # objectif secondaire : pas de cycle propre
    engine = make_engine(path)
    assert _count_cycles(engine) == 2
    assert Repo(engine).active_cycle().id == before


def test_migration_keeps_only_latest_active_goal_active(tmp_path):
    path = tmp_path / "old.db"
    _old_db_with_plan(path)
    con = sqlite3.connect(path)
    con.execute(
        "INSERT INTO goal VALUES (5, '2026-08-01', 'route', 10, 0, '2026-11-30', 3, NULL, NULL, 'active', "
        "'2026-08-05', 1, NULL, NULL, '[]', NULL, 0)"
    )
    con.commit()
    con.close()
    repo = Repo(make_engine(path))
    assert repo.active_cycle().id == 7
    assert [g.id for g in repo.upcoming_goals()] == [7]
    with repo.transaction() as db:
        from coach.plan.models import Cycle

        assert db.get(Goal, 5).status == "archived" and db.get(Cycle, 5).status == "done"


def test_migration_archived_goal_sessions_keep_done_cycle(tmp_path):
    path = tmp_path / "old.db"
    _old_db_with_plan(path)
    con = sqlite3.connect(path)
    con.execute(
        "INSERT INTO session VALUES (2, 3, 1, 1, 'mardi', NULL, 'EF', 'hr', 't', 'd', '[]', NULL, NULL, "
        "'done', NULL, NULL, NULL, NULL, NULL, NULL, 0)"
    )
    con.commit()
    con.close()
    repo = Repo(make_engine(path))
    assert [s.status for s in repo.sessions(3)] == ["done"]
    with repo.transaction() as db:
        from coach.plan.models import Cycle

        assert db.get(Cycle, 3).status == "done"


def test_migration_adds_proposal_estimates(tmp_path):
    """Les propositions d'avant les estimations reçoivent une liste vide ; migration rejouable."""
    path = tmp_path / "proposals.db"
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE proposal (id INTEGER PRIMARY KEY, created_at DATETIME, analysis VARCHAR,
            changes_json VARCHAR, status VARCHAR);
        INSERT INTO proposal VALUES (1, '2026-11-01', 'a', '[]', 'pending');
    """)
    con.commit()
    con.close()
    Repo(make_engine(path))
    repo = Repo(make_engine(path))
    assert repo.pending_proposal().estimates_json == "[]"


def test_state_roundtrip(repo):
    repo.set_state("sync", {"a": 1})
    assert repo.get_state("sync") == {"a": 1}
    assert repo.get_state("x") is None


def test_gpx_roundtrip(repo):
    assert repo.gpx(1) is None
    with repo.transaction() as db:
        repo.save_gpx(db, 1, b"<gpx/>")
    assert repo.gpx(1) == b"<gpx/>"


def test_make_engine_writes_schema_version(tmp_path):
    from coach.plan.repo import SCHEMA_VERSION

    repo = Repo(make_engine(tmp_path / "v.db"))
    assert repo.get_state("schema_version") == {"v": SCHEMA_VERSION}


def make_engine_raw(path):
    from sqlmodel import create_engine

    return create_engine(f"sqlite:///{path}")


def test_make_engine_refuses_newer_schema(tmp_path):
    from coach.plan.repo import SCHEMA_VERSION, SchemaTooNew

    path = tmp_path / "new.db"
    repo = Repo(make_engine(path))
    repo.set_state("schema_version", {"v": SCHEMA_VERSION + 1})
    with pytest.raises(SchemaTooNew):
        make_engine(path)
    assert Repo(make_engine_raw(path)).get_state("schema_version") == {"v": SCHEMA_VERSION + 1}


def test_check_schema_version_on_libsql_engine(tmp_path):
    import coach.storage.libsql_dialect  # noqa: F401  (enregistre le dialecte)
    from sqlmodel import create_engine

    from coach.plan.repo import SCHEMA_VERSION, SchemaTooNew, _check_schema_version

    engine = create_engine(f"sqlite+libsql:///{tmp_path / 'l.db'}")
    _check_schema_version(engine)  # base neuve : version écrite
    repo = Repo(engine)
    assert repo.get_state("schema_version") == {"v": SCHEMA_VERSION}
    repo.set_state("schema_version", {"v": SCHEMA_VERSION + 1})
    with pytest.raises(SchemaTooNew):
        _check_schema_version(engine)
    assert repo.get_state("schema_version") == {"v": SCHEMA_VERSION + 1}
