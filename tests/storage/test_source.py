import pytest

from coach.config import Settings, db_path
from coach.storage import source as source_mod
from coach.storage.source import LocalSource, TursoSource, source_from_settings


def test_default_source_is_local(tmp_path, monkeypatch):
    monkeypatch.setenv("COACH_HOME", str(tmp_path))
    src = source_from_settings(Settings())
    assert isinstance(src, LocalSource)
    assert src.kind == "local"
    assert src.path == db_path()


def test_turso_source_from_settings():
    src = source_from_settings(Settings(storage_mode="turso", turso_url="libsql://x.turso.io", turso_token="tok"))
    assert isinstance(src, TursoSource)
    assert src.kind == "turso"
    assert (src.url, src.token) == ("libsql://x.turso.io", "tok")


@pytest.mark.parametrize("url", ["libsql://x.turso.io", "https://x.turso.io"])
def test_turso_source_engine_url(monkeypatch, url):
    monkeypatch.setattr(source_mod, "prepare_engine", lambda engine: engine)  # pas de réseau
    calls = []
    real = source_mod.remote_engine
    monkeypatch.setattr(source_mod, "remote_engine", lambda u, t: calls.append((u, t)) or real(u, t))
    engine = TursoSource(url, "tok").engine()
    assert str(engine.url).startswith("sqlite+libsql://x.turso.io")
    assert calls == [("x.turso.io", "tok")]  # URL normalisée, jeton transmis (connect_args côté remote_engine)


def test_turso_without_token_raises():
    with pytest.raises(ValueError):
        TursoSource("libsql://x.turso.io", "")
    with pytest.raises(ValueError):
        source_from_settings(Settings(storage_mode="turso", turso_url="libsql://x.turso.io"))


def test_local_source_engine_creates_db(tmp_path):
    engine = LocalSource(tmp_path / "c.db").engine()
    assert (tmp_path / "c.db").exists()
    engine.dispose()


def test_turso_network_failure_is_cloud_unreachable(monkeypatch):
    from coach.storage.cloud_errors import CloudUnreachable

    def unreachable(engine):
        raise ValueError("Hrana: `http error: `error trying to connect: dns error``")

    monkeypatch.setattr(source_mod, "prepare_engine", unreachable)
    with pytest.raises(CloudUnreachable):
        TursoSource("libsql://x.turso.io", "tok").engine()
