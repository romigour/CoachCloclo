"""Bascule local <-> cloud : la « base cloud » est une seconde base SQLite."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, OperationalError

from coach.plan.models import Activity, Goal, Session
from coach.plan.repo import Repo, SchemaTooNew, make_engine
from coach.storage import switch
from coach.storage.cloud_errors import CloudUnreachable, is_cloud_failure
from coach.storage.source import LocalSource
from coach.storage.switch import (
    NeedsConfirmation,
    delete_local_files,
    disable_cloud,
    enable_cloud,
    probe,
    wipe_cloud,
)
from coach.storage.transfer import is_empty
from tests.plan.factories import make_activity, make_cycle, make_db_session, make_goal

HRANA_DNS = "Hrana: `http error: `error trying to connect: dns error: hôte inconnu``"
HRANA_401 = "Hrana: `api error: `status=401 Unauthorized, body=`` "
HRANA_SQL = 'Hrana: `stream error: `Error { message: "SQLite error: no such table: x", code: "SQLITE_UNKNOWN" }``'


class FakeSource:
    """Source de test : un fichier SQLite, ou une erreur à l'ouverture."""

    kind = "turso"

    def __init__(self, path=None, fail: Exception | None = None):
        self.path = path
        self.fail = fail

    def engine(self):
        if self.fail is not None:
            raise self.fail
        return make_engine(self.path)


def _fill(engine, n_activities: int = 2) -> None:
    repo = Repo(engine)
    with repo.transaction() as db:
        cycle = make_cycle()
        db.add(cycle)
        db.add(make_goal())
        db.flush()
        db.add(make_db_session(cycle.id))
        for i in range(n_activities):
            db.add(make_activity(garmin_activity_id=100 + i))


def _count(engine, model) -> int:
    with engine.connect() as c:
        return c.execute(select(func.count()).select_from(model.__table__)).scalar()


@pytest.fixture
def local(tmp_path):
    eng = make_engine(tmp_path / "coach.db")
    _fill(eng)
    yield eng
    eng.dispose()


# --- probe -------------------------------------------------------------------------------------


def test_probe_reads_and_writes(tmp_path):
    engine = probe(FakeSource(tmp_path / "cloud.db"))
    assert Repo(engine).get_state("probe") is not None


@pytest.mark.parametrize("error", [ValueError(HRANA_DNS), OperationalError("x", {}, Exception("réseau"))])
def test_probe_network_failure_is_cloud_unreachable(error):
    with pytest.raises(CloudUnreachable):
        probe(FakeSource(fail=error))


def test_probe_bad_token_message():
    with pytest.raises(CloudUnreachable, match="[Jj]eton"):
        probe(FakeSource(fail=ValueError(HRANA_401)))


def test_probe_lets_schema_too_new_through():
    with pytest.raises(SchemaTooNew):
        probe(FakeSource(fail=SchemaTooNew("schéma 2 > 1")))


def test_probe_programming_error_is_not_masked():
    with pytest.raises(ValueError, match="bug"):
        probe(FakeSource(fail=ValueError("bug")))


def test_cloud_failure_classification():
    assert is_cloud_failure(ValueError(HRANA_DNS))
    assert is_cloud_failure(ValueError(HRANA_401))
    assert is_cloud_failure(OperationalError("x", {}, Exception("réseau")))
    assert is_cloud_failure(CloudUnreachable("x"))
    assert not is_cloud_failure(ValueError(HRANA_SQL))  # erreur SQL, pas réseau
    assert not is_cloud_failure(ValueError("bug"))
    assert not is_cloud_failure(IntegrityError("x", {}, Exception("unique")))


# --- enable_cloud ------------------------------------------------------------------------------


def test_enable_on_empty_cloud_copies(local, tmp_path):
    result = enable_cloud(local, FakeSource(tmp_path / "cloud.db"), replace_local=False)
    assert not isinstance(result, NeedsConfirmation)
    assert not is_empty(result)
    assert _count(result, Activity) == 2 and _count(result, Session) == 1


def test_enable_on_nonempty_cloud_needs_confirmation(local, tmp_path):
    cloud = make_engine(tmp_path / "cloud.db")
    _fill(cloud, n_activities=5)
    enable_cloud(cloud, FakeSource(tmp_path / "other.db"), replace_local=False)  # marqueur : base « non vide »
    source = FakeSource(tmp_path / "other.db")
    assert isinstance(enable_cloud(local, source, replace_local=False), NeedsConfirmation)
    adopted = enable_cloud(local, source, replace_local=True)
    assert _count(adopted, Activity) == 5  # les données du cloud, jamais celles de ce PC


def test_enable_copy_failure_propagates(local, tmp_path, monkeypatch):
    def boom(src, dst):
        raise switch.CopyMismatch("activity")

    monkeypatch.setattr(switch, "verify_copy", boom)
    with pytest.raises(switch.CopyMismatch):
        enable_cloud(local, FakeSource(tmp_path / "cloud.db"), replace_local=False)
    assert is_empty(make_engine(tmp_path / "cloud.db"))


# --- disable_cloud -----------------------------------------------------------------------------


def test_disable_copies_back_atomically(tmp_path):
    cloud = make_engine(tmp_path / "cloud.db")
    _fill(cloud, n_activities=3)
    home = tmp_path / "home"
    home.mkdir()
    (home / "coach.db-journal").write_bytes(b"journal perime")  # ne doit pas être rejoué sur la nouvelle base
    engine = disable_cloud(cloud, LocalSource(home / "coach.db"))
    assert _count(engine, Activity) == 3
    assert _count(cloud, Activity) == 3  # cloud intact
    assert sorted(p.name for p in home.iterdir()) == ["coach.db"]
    engine.dispose()


def test_disable_replaces_existing_local_file(tmp_path):
    cloud = make_engine(tmp_path / "cloud.db")
    _fill(cloud, n_activities=4)
    old = make_engine(tmp_path / "coach.db")
    _fill(old, n_activities=1)
    old.dispose()
    engine = disable_cloud(cloud, LocalSource(tmp_path / "coach.db"))
    assert _count(engine, Activity) == 4
    engine.dispose()


def test_disable_failure_keeps_existing_local(tmp_path, monkeypatch):
    cloud = make_engine(tmp_path / "cloud.db")
    _fill(cloud)
    old = make_engine(tmp_path / "coach.db")
    _fill(old, n_activities=1)
    old.dispose()

    def boom(src, dst):
        raise switch.CopyMismatch("activity")

    monkeypatch.setattr(switch, "verify_copy", boom)
    with pytest.raises(switch.CopyMismatch):
        disable_cloud(cloud, LocalSource(tmp_path / "coach.db"))
    check = make_engine(tmp_path / "coach.db")
    assert _count(check, Activity) == 1
    check.dispose()


# --- wipe et suppression -----------------------------------------------------------------------


def test_wipe_cloud(local):
    wipe_cloud(local)
    assert is_empty(local)
    assert _count(local, Goal) == 0


def test_delete_local_files(tmp_path):
    engine = make_engine(tmp_path / "coach.db")
    engine.dispose()
    (tmp_path / "gpx").mkdir()
    (tmp_path / "gpx" / "1.gpx").write_text("<gpx/>")
    (tmp_path / "history.json").write_text("{}")
    (tmp_path / "settings.json").write_text("{}")
    delete_local_files(tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["settings.json"]
    delete_local_files(tmp_path)  # idempotent
