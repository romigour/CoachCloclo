import pytest


@pytest.fixture
def coach_home(tmp_path, monkeypatch):
    monkeypatch.setenv("COACH_HOME", str(tmp_path))
    return tmp_path
