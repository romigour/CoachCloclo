"""Copie, vérification et effacement d'une base."""

import datetime as dt

import pytest
from sqlalchemy import delete, func, insert, literal_column, select
from sqlmodel import SQLModel

from coach.plan import repo as repo_mod
from coach.plan.models import Activity, Cycle, GarminLock, Goal, Session
from coach.plan.repo import Repo, make_engine, prepare_engine
from coach.services.context import long_history
from coach.storage import transfer
from coach.storage.libsql_dialect import remote_engine
from coach.storage.transfer import CopyMismatch, copy_all, is_empty, verify_copy, wipe
from tests.plan.factories import make_activity, make_cycle, make_db_session, make_goal
from tests.storage.fake_hrana import FakeHrana


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


def test_copy_to_remote(src, tmp_path):
    transport = FakeHrana(tmp_path / "l.db").transport
    dst = prepare_engine(remote_engine("libsql://x.turso.io", "tok", transport=transport))
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


def test_garmin_lock_neither_copied_nor_counted(src, dst):
    now = dt.datetime.now(dt.timezone.utc)
    with Repo(src).transaction() as db:
        db.add(GarminLock(holder="pc-source", expires_at=now))
    with Repo(dst).transaction() as db:
        db.add(GarminLock(holder="pc-destination", expires_at=now))
    copy_all(src, dst)
    verify_copy(src, dst)  # 1 verrou de chaque côté, mais pas comparés
    with dst.connect() as c:
        assert c.execute(select(GarminLock.__table__.c.holder)).scalars().all() == ["pc-destination"]
    with dst.begin() as c:
        c.execute(delete(GarminLock.__table__))
    verify_copy(src, dst)  # nombre de verrous différent : pas une copie incomplète


# --- source distante : lecture par pages --------------------------------------------------------


@pytest.fixture
def remote(tmp_path):
    server = FakeHrana(tmp_path / "remote.db")
    engine = prepare_engine(remote_engine("libsql://x.turso.io", "tok", transport=server.transport))
    yield server, engine
    engine.dispose()


def _fill_file(path, rows: int, raw: str) -> None:
    """Remplit directement le fichier du faux serveur."""
    eng = make_engine(path)
    repo = _fill(eng)
    with repo.transaction() as db:
        for i in range(rows):
            # ids espacés, dates mélangées : l'ordre des ids n'est pas celui des dates
            day = dt.date(2026, 1, 1) - dt.timedelta(days=i % 50)
            db.add(make_activity(id=10 + 3 * i, garmin_activity_id=100 + i, date=day, raw_json=raw))
        for i in range(4):
            repo.save_gpx(db, 100 + i, bytes(range(256)) * 2400)
    for key in ("z", "a", "m"):  # clé textuelle : ordre d'insertion, pas ordre alphabétique
        repo.set_state(key, {"k": key * 400_000})
    eng.dispose()


def _dump(engine) -> dict:
    with engine.connect() as c:
        return {
            t.name: [tuple(r) for r in c.execute(select(t).order_by(literal_column("rowid")))]
            for t in SQLModel.metadata.sorted_tables
        }


@pytest.mark.parametrize("rows, raw", [(1300, "{}"), (30, '{"é": "' + "x" * 200_000 + '"}')], ids=["many", "heavy"])
def test_copy_from_remote_is_paged(remote, tmp_path, monkeypatch, rows, raw):
    server, src = remote
    _fill_file(tmp_path / "remote.db", rows, raw)
    local_src = make_engine(tmp_path / "remote.db")
    by_file, by_pages = make_engine(tmp_path / "f.db"), make_engine(tmp_path / "p.db")
    inserted = []
    real = transfer._insert_rows

    def spy(conn, table, batch):
        inserted.extend((table.name, tuple(r.values())) for r in batch)
        real(conn, table, batch)

    monkeypatch.setattr(transfer, "_insert_rows", spy)
    copy_all(local_src, by_file)
    from_file, inserted = inserted, []
    server.response_sizes.clear()
    copy_all(src, by_pages)
    assert max(n for n, _ in server.response_sizes) <= 500
    assert max(size for _, size in server.response_sizes) < 3_000_000
    assert inserted == from_file  # mêmes lignes, même ordre
    assert _dump(by_pages) == _dump(by_file)
    verify_copy(src, by_pages)


def test_rows_changed_between_pages_are_refused(remote, tmp_path, monkeypatch):
    """Une autre machine écrit pendant la lecture d'une table en plusieurs pages."""
    _, src = remote
    _fill_file(tmp_path / "remote.db", 1300, "{}")
    real = transfer._insert_rows

    def insert_then_write(conn, table, rows):
        real(conn, table, rows)
        if table.name == "activity":
            other = make_engine(tmp_path / "remote.db")
            with other.begin() as c:
                c.execute(delete(Activity.__table__).where(Activity.__table__.c.id == 3001))
            other.dispose()

    monkeypatch.setattr(transfer, "_insert_rows", insert_then_write)
    dst = make_engine(tmp_path / "d.db")
    with pytest.raises(CopyMismatch):
        copy_all(src, dst)
    assert is_empty(dst)


def test_all_activities_paged_when_remote(remote, tmp_path):
    server, src = remote
    raw = '{"x": "' + "y" * 5_000 + '"}'
    _fill_file(tmp_path / "remote.db", 1300, raw)
    server.response_sizes.clear()
    got = Repo(src).all_activities()
    assert max(n for n, _ in server.response_sizes) <= 500
    assert max(size for _, size in server.response_sizes) < 3_000_000
    want = Repo(make_engine(tmp_path / "remote.db")).all_activities()
    assert [a.model_dump() for a in got] == [a.model_dump() for a in want]
    assert len(got) == 1302


def test_all_activities_empty_remote(remote):
    assert Repo(remote[1]).all_activities() == []


def test_long_history_never_reads_raw_json(remote, tmp_path):
    server, src = remote
    _fill_file(tmp_path / "remote.db", 20, "{}")
    seen = len(server.statements())
    got = long_history(Repo(src), dt.date(2026, 2, 1))
    assert got == long_history(Repo(make_engine(tmp_path / "remote.db")), dt.date(2026, 2, 1))
    assert not [s for s in server.statements()[seen:] if "raw_json" in s]
