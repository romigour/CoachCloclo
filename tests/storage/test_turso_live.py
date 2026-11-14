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
