"""Copie, vérification et effacement d'une base."""

import datetime as dt

import pytest
from sqlalchemy import create_engine, delete, func, insert, select
from sqlmodel import SQLModel

import coach.storage.libsql_dialect  # noqa: F401  (enregistre le dialecte)
from coach.plan import repo as repo_mod
from coach.plan.models import Activity, Cycle, Goal, Session
from coach.plan.repo import Repo, make_engine, prepare_engine
from coach.storage import transfer
from coach.storage.transfer import CopyMismatch, copy_all, is_empty, verify_copy, wipe
from tests.plan.factories import make_activity, make_cycle, make_db_session, make_goal


def _fill(engine) -> Repo:
    repo = Repo(engine)
    with repo.transaction() as db:
        cycle = make_cycle()
        db.add(cycle)
        goal = make_goal()
        db.add(goal)
        db.flush()
        db.add(make_db_session(cycle.id))
        db.add(make_db_session(cycle.id))
        db.add(make_activity(garmin_activity_id=1))
        db.add(make_activity(garmin_activity_id=2))
        repo.save_gpx(db, goal.id, b"\x00\x01<gpx>\xff</gpx>")
    repo.set_state("history", {"n": 3})
    return repo


def _count(engine, model) -> int:
    with engine.connect() as c:
        return c.execute(select(func.count()).select_from(model.__table__)).scalar()


@pytest.fixture
def src(tmp_path):
    eng = prepare_engine(make_engine(tmp_path / "src.db"))
    _fill(eng)
    return eng


@pytest.fixture
def dst(tmp_path):
    return prepare_engine(make_engine(tmp_path / "dst.db"))


def test_copy_and_verify_roundtrip(src, dst):
    assert is_empty(dst)
    copy_all(src, dst)
    verify_copy(src, dst)
    assert not is_empty(dst)
    assert _count(dst, Session) == 2 and _count(dst, Activity) == 2
    assert Repo(dst).gpx(1) == b"\x00\x01<gpx>\xff</gpx>"
    assert Repo(dst).get_state("history") == {"n": 3}
    assert Repo(dst).get_state("copy_complete") is not None


def test_copy_replaces_existing_rows(src, dst):
    with Repo(dst).transaction() as db:
        db.add(make_goal(distance_km=10))
        db.add(make_goal(distance_km=11))
        db.add(make_goal(distance_km=12))
    Repo(dst).set_state("history", {"old": True})
    copy_all(src, dst)
    verify_copy(src, dst)
    assert _count(dst, Goal) == 1
    assert Repo(dst).get_state("history") == {"n": 3}


def test_interrupted_copy_counts_as_empty(src, dst, monkeypatch):
    copy_all(src, dst)
    verify_copy(src, dst)
    assert not is_empty(dst)

    def boom(*a, **k):
        raise RuntimeError("coupure")

    monkeypatch.setattr(transfer, "_insert_rows", boom)
    with pytest.raises(RuntimeError):
        copy_all(src, dst)
    assert is_empty(dst)


def test_verify_detects_mismatch(src, dst):
    copy_all(src, dst)
    with dst.begin() as c:
        c.execute(delete(Activity.__table__).where(Activity.__table__.c.garmin_activity_id == 1))
    with pytest.raises(CopyMismatch):
        verify_copy(src, dst)


def test_wipe_empties(src, dst):
    copy_all(src, dst)
    verify_copy(src, dst)
    wipe(dst)
    assert is_empty(dst)
    for table in SQLModel.metadata.sorted_tables:
        with dst.connect() as c:
            assert c.execute(select(func.count()).select_from(table)).scalar() == 0


def test_copy_to_libsql_file(src, tmp_path):
    dst = prepare_engine(create_engine(f"sqlite+libsql:///{tmp_path / 'l.db'}"))
    copy_all(src, dst)
    verify_copy(src, dst)
    assert not is_empty(dst)
    assert Repo(dst).gpx(1) == b"\x00\x01<gpx>\xff</gpx>"
    assert Repo(dst).get_state("history") == {"n": 3}


def test_source_marker_not_copied_and_failed_verify_stays_empty(src, dst):
    Repo(src).set_state("copy_complete", {"at": "old"})
    copy_all(src, dst)
    assert is_empty(dst)
    with Repo(src).transaction() as db:
        db.add(make_goal(distance_km=5))
    with pytest.raises(CopyMismatch):
        verify_copy(src, dst)
    assert is_empty(dst)


def test_parent_child_ids_preserved(src, dst):
    copy_all(src, dst)
    with src.connect() as s, dst.connect() as d:
        for model in (Cycle, Session):
            t = model.__table__
            assert s.execute(select(t).order_by(t.c.id)).all() == d.execute(select(t).order_by(t.c.id)).all()
