"""Dialecte libSQL : moteur distant, erreurs, fermeture."""

import subprocess
import sys
import traceback
from datetime import date

import pytest
from sqlalchemy import exc, pool, text
from sqlalchemy.engine import make_url
from sqlmodel import select

from coach.garmin.port import ActivitySummary
from coach.plan import repo as repo_mod
from coach.plan.models import Goal
from coach.plan.repo import Repo, prepare_engine
from coach.services.activities import store_summaries
from coach.storage import hrana
from coach.storage.cloud_errors import INVALID_ADDRESS_MSG, CloudUnreachable, is_auth_failure, is_cloud_failure
from coach.storage.libsql_dialect import remote_engine
from tests.plan.factories import make_activity, make_goal
from tests.storage.fake_hrana import FakeHrana

URL = "libsql://x.turso.io"
TOKEN = "jeton-secret"
INSERT = "INSERT INTO appstate VALUES ('k', '1')"


@pytest.fixture
def server(tmp_path):
    return FakeHrana(tmp_path / "c.db")


@pytest.fixture
def engine(server):
    eng = prepare_engine(remote_engine(URL, TOKEN, transport=server.transport))
    yield eng
    eng.dispose()


@pytest.fixture
def clients(monkeypatch):
    """Clients HTTP créés pendant le test."""
    made = []
    real = hrana.make_client

    def spy(transport=None):
        made.append(real(transport))
        return made[-1]

    monkeypatch.setattr(hrana, "make_client", spy)
    return made


# --- moteur ------------------------------------------------------------------------------------


@pytest.mark.parametrize("url", [URL, "https://x.turso.io/", "x.turso.io"])
def test_remote_connect_args(url):
    engine = remote_engine(url, TOKEN)
    assert str(engine.url) == "sqlite+libsql://x.turso.io?secure=true"
    assert engine.dialect.create_connect_args(engine.url) == (["https://x.turso.io"], {})
    assert engine.dialect.driver == "libsql" and engine.dialect.dbapi is hrana
    engine.dispose()


def test_always_https(server):
    dialect = remote_engine(URL, TOKEN, transport=server.transport).dialect
    assert dialect.create_connect_args(make_url("sqlite+libsql://h:8080")) == (["https://h:8080"], {})


def test_remote_engine_options():
    engine = remote_engine("libsql://example.turso.io", "tok")
    assert isinstance(engine.pool, pool.NullPool)
    assert engine.pool._pre_ping is False
    engine.dispose()


def test_one_shared_client(clients, server):
    engine = remote_engine(URL, TOKEN, transport=server.transport)
    for _ in range(3):
        with engine.connect() as c:
            c.execute(text("select 1"))
    assert len(clients) == 1


@pytest.mark.parametrize("with_transport", [True, False])
def test_dispose_closes_client(clients, server, with_transport):
    engine = remote_engine(URL, TOKEN, transport=server.transport if with_transport else None)
    assert not clients[0].is_closed
    engine.dispose()
    assert clients[0].is_closed
    engine.dispose()  # sans effet


def test_use_after_dispose_is_cloud_failure(engine):
    """Transaction en cours pendant la fermeture du moteur : panne reconnue, pas d'erreur brute de httpx."""
    with pytest.raises(exc.OperationalError) as e:
        with engine.begin() as c:
            c.execute(text(INSERT))
            engine.dispose()
            c.execute(text("select 1"))
    assert is_cloud_failure(e.value)


def test_httpx_not_loaded_at_startup():
    """Mode local : `httpx`, long à importer, n'est chargé qu'à l'ouverture d'une base distante."""
    code = "import sys, coach.api.app; sys.exit('httpx' in sys.modules)"
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0


# --- usage par le dépôt ------------------------------------------------------------------------


def test_migrations_and_rollback(engine):
    repo_mod._migrate(engine)  # rejeu idempotent (PRAGMA / ALTER)
    repo = Repo(engine)
    with repo.transaction() as db:
        db.add(make_goal())
    with pytest.raises(RuntimeError):
        with repo.transaction() as db:
            db.add(make_goal())
            db.flush()
            raise RuntimeError
    with repo.transaction() as db:
        assert len(db.exec(select(Goal)).all()) == 1
    with engine.connect() as c:
        assert c.execute(text("select count(*) from goal")).scalar() == 1


def test_repo_read_is_one_send(server, engine):
    before = server.sends
    Repo(engine).latest_snapshot()
    assert server.sends == before + 1


def test_unique_violation_wrapped(server, engine):
    repo = Repo(engine)
    repo.add(make_activity(garmin_activity_id=7))
    with pytest.raises(exc.IntegrityError) as e:
        repo.add(make_activity(garmin_activity_id=7))
    assert isinstance(e.value.orig, hrana.IntegrityError)
    assert not is_cloud_failure(e.value)
    assert repo.count_activities() == 1
    assert server.open_streams() == 0


def test_store_summaries_survives_duplicate(engine, monkeypatch):
    repo = Repo(engine)
    repo.add(make_activity(garmin_activity_id=7))
    monkeypatch.setattr(repo, "activity_by_garmin_id", lambda _: None)  # inséré juste après ce contrôle
    summary = ActivitySummary(
        garmin_id=7,
        date=date(2026, 11, 1),
        type_key="running",
        duration_s=3600,
        distance_m=10000,
        d_plus_m=0,
        avg_hr=140,
        raw={},
    )
    assert store_summaries(repo, [summary]) == 0
    assert repo.count_activities() == 1


def test_gpx_blob_roundtrip(engine):
    data = bytes(range(256)) * (3_000_000 // 256)
    repo = Repo(engine)
    with repo.transaction() as db:
        goal = make_goal()
        db.add(goal)
        db.flush()
        goal_id = goal.id
        repo.save_gpx(db, goal_id, data)
    assert repo.gpx(goal_id) == data


# --- erreurs -----------------------------------------------------------------------------------


def _raw_connect_error(engine) -> Exception:
    with pytest.raises(Exception) as e:
        engine.raw_connection()
    return e.value


def test_raw_errors_at_connect_are_classified(server):
    # panne pendant la première connexion (initialisation du dialecte)
    engine = remote_engine(URL, TOKEN, transport=server.transport)
    server.fail_next("drop_before")
    server.fail_next("drop_before")
    err = _raw_connect_error(engine)
    assert isinstance(err, hrana.CloudNetworkError)
    assert is_cloud_failure(err) and not is_auth_failure(err)
    server.fail_next("http_401")
    err = _raw_connect_error(engine)
    assert isinstance(err, hrana.CloudAuthError)
    assert is_cloud_failure(err) and is_auth_failure(err)
    with engine.connect() as c:  # le moteur se remet d'un premier échec
        assert c.execute(text("select 1")).scalar() == 1


def test_malformed_token_at_connect():
    engine = remote_engine(URL, "jeton\ncoupé")
    err = _raw_connect_error(engine)
    assert isinstance(err, hrana.CloudAuthError)
    assert is_cloud_failure(err) and is_auth_failure(err)
    with pytest.raises(exc.OperationalError) as e:
        engine.connect()
    assert is_cloud_failure(e.value) and is_auth_failure(e.value)
    assert "coupé" not in str(e.value) + repr(e.value.orig)
    engine.dispose()


@pytest.mark.parametrize(
    "failures, auth", [(["drop_before"] * 2, False), (["http_500"], False), (["http_401"], True)]
)
def test_wrapped_errors_are_classified(server, engine, failures, auth):
    for kind in failures:
        server.fail_next(kind)
    with pytest.raises(exc.OperationalError) as e:
        Repo(engine).latest_snapshot()
    assert is_cloud_failure(e.value) and is_auth_failure(e.value) is auth


def test_lost_commit_is_not_replayed(server, engine):
    with pytest.raises(exc.OperationalError) as e:
        with engine.begin() as c:
            c.execute(text(INSERT))
            server.fail_next("drop_after")
    assert is_cloud_failure(e.value)
    assert server.statements()[-2:] == [INSERT, "COMMIT"]


def test_sql_error_is_not_a_cloud_failure(engine):
    with pytest.raises(exc.DatabaseError) as e:
        with engine.connect() as c:
            c.execute(text("select * from absente"))
    assert not is_cloud_failure(e.value) and not is_auth_failure(e.value)


def test_token_never_shown(server, engine, caplog):
    caplog.set_level("DEBUG")
    shown = [repr(engine), str(engine.url), repr(engine.pool), repr(engine.dialect)]
    for kind in ("http_401", "http_500"):
        server.fail_next(kind)
        with pytest.raises(exc.OperationalError) as e:
            Repo(engine).latest_snapshot()
        shown += [repr(e.value), str(e.value), "".join(traceback.format_exception(e.value))]
    with pytest.raises(exc.DatabaseError) as e:
        with engine.connect() as c:
            c.execute(text("select * from absente"))
    shown += [str(e.value), caplog.text]
    assert TOKEN not in "".join(shown)


def test_token_in_url_not_shown():
    engine = remote_engine(f"{URL}?authToken={TOKEN}", TOKEN)
    assert TOKEN not in repr(engine)
    engine.dispose()


# --- adresse -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url", [f"libsql://{TOKEN}@x.turso.io", f"https://u:{TOKEN}@x.turso.io:443/", f"a@{TOKEN}@x.turso.io"]
)
def test_userinfo_dropped(server, url):
    engine = remote_engine(url, "tok", transport=server.transport)
    with engine.connect() as c:
        c.execute(text("select 1"))
    assert {u.removeprefix("https://").split("/")[0].split(":")[0] for u in server.urls} == {"x.turso.io"}
    assert TOKEN not in repr(engine) + "".join(server.urls)
    engine.dispose()


@pytest.mark.parametrize(
    "url",
    ["libsql://", "https:///x", "user@", "x.turso.io:abc", "x.turso.io:", "x.turso.io:0", "x.turso.io:70000",
     ":443", "x.turso.io:²", "[::1]", "[::1]:443", "x turso.io", f"libsql://u:{TOKEN}/x@y"],
)
def test_invalid_address_refused_before_client(clients, url):
    with pytest.raises(CloudUnreachable) as e:
        remote_engine(url, TOKEN)
    assert clients == []
    assert str(e.value) == INVALID_ADDRESS_MSG
    assert TOKEN not in str(e.value) + repr(e.value)
    assert e.value.__context__ is None
