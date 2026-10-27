import pytest


@pytest.fixture
def coach_home(tmp_path, monkeypatch):
    monkeypatch.setenv("COACH_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def repo(tmp_path):
    from coach.plan.repo import Repo, make_engine

    return Repo(make_engine(tmp_path / "t.db"))
