"""Dialecte libSQL : enregistrement, arguments de connexion, fichier local."""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlmodel import SQLModel, select

import coach.storage.libsql_dialect  # noqa: F401  (enregistre le dialecte)
from coach.plan import repo as repo_mod
from coach.plan.models import Goal
from coach.plan.repo import Repo
from tests.plan.factories import make_goal


def test_remote_connect_args():
    engine = create_engine(
        "sqlite+libsql://example.turso.io?secure=true", connect_args={"auth_token": "x"}
    )
    args, kwargs = engine.dialect.create_connect_args(make_url("sqlite+libsql://example.turso.io?secure=true"))
    assert args == ["https://example.turso.io"] and kwargs == {}
    assert engine.dialect.driver == "libsql"


def test_insecure_http():
    d = create_engine("sqlite+libsql://h:8080").dialect
    assert d.create_connect_args(make_url("sqlite+libsql://h:8080"))[0] == ["http://h:8080"]


@pytest.fixture
def engine(tmp_path):
    eng = create_engine(f"sqlite+libsql:///{tmp_path / 'c.db'}")
    SQLModel.metadata.create_all(eng)
    repo_mod._migrate(eng)
    return eng


def test_local_file_migrations_and_rollback(engine):
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
