"""Essai réel contre une base Turso (libSQL) : migrations, transaction, latence.

Lancer : `uv run pytest -m live tests/storage -v` avec une base Turso de TEST :
    COACH_TURSO_URL   = libsql://<base>-<org>.turso.io   (ou https://...)
    COACH_TURSO_TOKEN = jeton d'accès de la base
Sans ces variables, les tests sont ignorés (skip). Ne pas lancer en CI.

Format : dialecte maison `coach.storage.libsql_dialect` (paquet `libsql`, roues Windows) :
  - URL SQLAlchemy : `sqlite+libsql://<hôte>?secure=true` (secure -> https, sinon http) ;
    l'hôte est celui de COACH_TURSO_URL sans le schéma `libsql://`.
  - Jeton : PAS dans l'URL mais `create_engine(url, connect_args={"auth_token": token})`.
  - Non vérifié hors réseau : que `libsql.connect("https://<hôte>", auth_token=...)` accepte le mode distant pur."""

import os
from concurrent.futures import ThreadPoolExecutor
import time
from datetime import date, timedelta

import pytest
from sqlmodel import SQLModel, delete, select

from coach.storage.libsql_dialect import remote_engine
from coach.plan import repo as repo_mod
from coach.plan.models import Activity, Goal
from coach.plan.repo import Repo
from tests.plan.factories import make_activity, make_goal

URL = os.environ.get("COACH_TURSO_URL")
TOKEN = os.environ.get("COACH_TURSO_TOKEN")

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not (URL and TOKEN), reason="COACH_TURSO_URL / COACH_TURSO_TOKEN absents"),
]

_BASE_ID = 9_000_000_000  # ids d'activités d'essai, nettoyés après chaque test


def _remote_engine():
    """Moteur sur la base distante : même logique que `make_engine` (création + migrations)."""
    engine = remote_engine(URL, TOKEN)
    SQLModel.metadata.create_all(engine)
    repo_mod._migrate(engine)
    return engine


@pytest.fixture
def engine():
    eng = _remote_engine()
    yield eng
    with Repo(eng).transaction() as db:
        db.exec(delete(Activity).where(Activity.garmin_activity_id >= _BASE_ID))


def test_turso_migrations(engine):
    repo_mod._migrate(engine)  # second passage : PRAGMA table_info / ALTER TABLE idempotents
    repo_mod._migrate(engine)


def test_turso_transaction_rollback(engine):
    repo = Repo(engine)
    with repo.transaction() as db:
        before = len(db.exec(select(Goal)).all())
    with pytest.raises(RuntimeError):
        with repo.transaction() as db:
            db.add(make_goal())
            db.flush()
            raise RuntimeError("annulation")
    with repo.transaction() as db:
        assert len(db.exec(select(Goal)).all()) == before


def test_turso_stats_latency(engine):
    repo = Repo(engine)
    with repo.transaction() as db:
        db.add_all(
            make_activity(garmin_activity_id=_BASE_ID + i, date=date(2026, 1, 1) + timedelta(days=i % 300))
            for i in range(1500)
        )
    start = time.perf_counter()
    repo.all_activities()
    repo.races()
    elapsed = time.perf_counter() - start
    print(f"all_activities + races : {elapsed:.2f} s")
    assert elapsed < 2



def test_turso_concurrent_reads(engine):
    repo = Repo(engine)
    with repo.transaction() as db:
        db.add_all(make_activity(garmin_activity_id=_BASE_ID + i) for i in range(50))
    with ThreadPoolExecutor(8) as ex:
        results = list(ex.map(lambda _: len(repo.all_activities()), range(32)))
    assert len(set(results)) == 1 and results[0] >= 50


def test_turso_lock_two_holders(engine):
    """Sémantique de rowcount distante (INSERT ... ON CONFLICT, UPDATE conditionnel) : libre, pris, refusé, expiré."""
    from datetime import datetime, timezone

    from coach.storage.lock import held_elsewhere, release, try_acquire

    repo = Repo(engine)
    a, b = "essai-live-A", "essai-live-B"
    ttl = timedelta(minutes=2)
    release(repo, a)
    release(repo, b)
    now = datetime.now(timezone.utc)
    try:
        for _ in range(2):  # deux tours : l'état laissé par le premier ne doit rien fausser
            assert try_acquire(repo, a, ttl, now)  # libre -> pris
            assert held_elsewhere(repo, b, now)
            assert try_acquire(repo, a, ttl, now)  # prolongation par le détenteur
            assert not try_acquire(repo, b, ttl, now)  # refusé
            later = now + ttl + timedelta(seconds=1)
            assert try_acquire(repo, b, ttl, later)  # expiré -> accordé
            assert not try_acquire(repo, a, ttl, later)
            release(repo, b)
            assert not held_elsewhere(repo, a, later)
    finally:
        release(repo, a)
        release(repo, b)


def test_turso_copy_roundtrip(tmp_path):
    """Copie vérifiée local -> Turso puis retour. ATTENTION : vide la base de TEST distante."""
    from coach.plan.repo import make_engine
    from coach.storage.source import LocalSource, TursoSource
    from coach.storage.switch import disable_cloud
    from coach.storage.transfer import copy_all, is_empty, verify_copy, wipe
    from tests.plan.factories import make_cycle, make_db_session

    local = make_engine(tmp_path / "coach.db")
    with Repo(local).transaction() as db:
        cycle = make_cycle()
        db.add(cycle)
        db.flush()
        db.add(make_db_session(cycle.id))
        db.add_all(make_activity(garmin_activity_id=_BASE_ID + i) for i in range(200))
    cloud = TursoSource(URL, TOKEN).engine()
    try:
        wipe(cloud)
        assert is_empty(cloud)
        start = time.perf_counter()
        copy_all(local, cloud)
        verify_copy(local, cloud)
        print(f"copie de 200 activités vers Turso : {time.perf_counter() - start:.2f} s")
        assert not is_empty(cloud)
        (tmp_path / "back").mkdir()
        back = disable_cloud(cloud, LocalSource(tmp_path / "back" / "coach.db"))
        assert len(Repo(back).all_activities()) == 200
        back.dispose()
    finally:
        wipe(cloud)
        cloud.dispose()
        local.dispose()


def test_turso_copy_roundtrip_realistic(tmp_path):
    """Volume réaliste : ~2000 activités avec leurs tours et un GPX de ~3 Mo.

    Mesure copie + vérification vers Turso (une seule transaction distante, INSERT par lots de
    `transfer.BATCH` lignes). ATTENTION : vide la base de TEST distante."""
    import json

    from coach.plan.models import ActivityLaps
    from coach.plan.repo import make_engine
    from coach.storage import transfer
    from coach.storage.source import LocalSource, TursoSource
    from coach.storage.switch import disable_cloud
    from coach.storage.transfer import copy_all, is_empty, verify_copy, wipe
    from tests.plan.factories import make_cycle, make_db_session

    n = 2000
    laps = json.dumps([{"index": i, "duration_s": 300, "distance_m": 1000, "avg_hr": 150} for i in range(10)])
    point = '<trkpt lat="45.000000" lon="6.000000"><ele>1000.0</ele></trkpt>\n'
    gpx = ("<gpx><trk><trkseg>\n" + point * (3_000_000 // len(point)) + "</trkseg></trk></gpx>").encode()
    local = make_engine(tmp_path / "coach.db")
    repo = Repo(local)
    with repo.transaction() as db:
        cycle = make_cycle()
        db.add(cycle)
        goal = make_goal()
        db.add(goal)
        db.flush()
        db.add(make_db_session(cycle.id))
        activities = [
            make_activity(garmin_activity_id=_BASE_ID + i, date=date(2020, 1, 1) + timedelta(days=i))
            for i in range(n)
        ]
        db.add_all(activities)
        db.flush()
        db.add_all(ActivityLaps(activity_id=a.id, laps_json=laps) for a in activities)
        repo.save_gpx(db, goal.id, gpx)
    cloud = TursoSource(URL, TOKEN).engine()
    try:
        wipe(cloud)
        start = time.perf_counter()
        copy_all(local, cloud)
        verify_copy(local, cloud)
        elapsed = time.perf_counter() - start
        print(f"copie + vérification de {n} activités (tours, GPX {len(gpx) / 1e6:.1f} Mo, lots de {transfer.BATCH}) : {elapsed:.2f} s")
        assert not is_empty(cloud)
        assert Repo(cloud).gpx(goal.id) == gpx
        (tmp_path / "back").mkdir()
        start = time.perf_counter()
        back = disable_cloud(cloud, LocalSource(tmp_path / "back" / "coach.db"))
        print(f"retour en local : {time.perf_counter() - start:.2f} s")
        assert len(Repo(back).all_activities()) == n
        assert Repo(back).gpx(goal.id) == gpx
        back.dispose()
    finally:
        wipe(cloud)
        cloud.dispose()
        local.dispose()
