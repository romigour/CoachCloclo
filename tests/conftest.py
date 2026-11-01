import pytest


@pytest.fixture(autouse=True)
def _home_isolee(tmp_path_factory, monkeypatch):
    """Le vrai ~/.local/bin/claude de la machine ne doit pas fausser les tests."""
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))


@pytest.fixture
def coach_home(tmp_path, monkeypatch):
    monkeypatch.setenv("COACH_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def repo(tmp_path):
    from coach.plan.repo import Repo, make_engine

    return Repo(make_engine(tmp_path / "t.db"))
