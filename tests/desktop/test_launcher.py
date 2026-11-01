import socket
import sys

import pytest

from coach.api.app import create_app
from coach.config import Settings, save_settings
from coach.desktop import instance, launcher
from coach.desktop.logs import teardown_logging
from coach.desktop.server import AppServer
from coach.garmin.port import FakeGarminClient, Metrics
from coach.llm.provider import FakeLLMProvider


@pytest.fixture(autouse=True)
def _nettoyage(monkeypatch):
    # dépend de monkeypatch : le nettoyage passe avant la restauration de sys.stdout
    yield
    teardown_logging()


@pytest.fixture
def fatals(monkeypatch):
    messages: list[str] = []
    monkeypatch.setattr(launcher, "fatal", lambda m, log=None: messages.append(m))
    return messages


@pytest.fixture
def opened(monkeypatch):
    urls: list[str] = []
    monkeypatch.setattr(launcher.webbrowser, "open", lambda u: urls.append(u))
    return urls


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_smoke_mode_returns_zero(coach_home, monkeypatch, opened):
    monkeypatch.setattr(instance, "PORTS", (free_port(),))
    assert launcher.main(["--smoke"]) == 0
    assert (coach_home / "logs" / "coachcloclo.log").exists()
    assert opened == []


def test_smoke_mode_lu_dans_sys_argv(coach_home, monkeypatch, opened):
    """main() sans argument lit sys.argv (python -m coach.desktop --smoke, exécutable gelé)."""
    monkeypatch.setattr(instance, "PORTS", (free_port(),))
    monkeypatch.setattr(sys, "argv", ["coach", "--smoke"])
    assert launcher.main() == 0
    assert opened == []


def test_second_instance_opens_browser(coach_home, monkeypatch, opened, fatals):
    metrics = Metrics(hr_max=190, hr_rest=50, threshold_pace_s_km=300)
    app = create_app(
        lan=False,
        garmin_factory=lambda: FakeGarminClient(metrics=metrics),
        llm_factory=lambda: FakeLLMProvider([]),
    )
    port = free_port()
    srv = AppServer(app, port)
    srv.start("127.0.0.1")
    try:
        monkeypatch.setattr(instance, "acquire_mutex", lambda: None)
        instance.write_state(port, 1)
        assert launcher.main([]) == 0
    finally:
        srv.stop()
    assert opened == [f"http://127.0.0.1:{port}"]
    assert fatals == []


def test_second_instance_stuck(coach_home, monkeypatch, opened, fatals):
    monkeypatch.setattr(instance, "acquire_mutex", lambda: None)
    instance.write_state(free_port(), 1)
    assert launcher.main([]) == 1
    assert "bloqué" in fatals[0]
    assert opened == []


def test_no_free_port(coach_home, monkeypatch, fatals):
    monkeypatch.setattr(instance, "port_free", lambda p: False)
    assert launcher.main(["--smoke"]) == 1
    assert "Aucun port libre" in fatals[0]


class FauxServeur:
    instances: list = []

    def __init__(self, app, port):
        self.app, self.port = app, port
        self.starts: list[str] = []
        self.restarts: list[str] = []
        FauxServeur.instances.append(self)

    def start(self, host):
        self.starts.append(host)

    def restart(self, host):
        self.restarts.append(host)

    def stop(self):
        pass


@pytest.fixture
def faux_serveur(monkeypatch):
    FauxServeur.instances = []
    monkeypatch.setattr(launcher, "AppServer", FauxServeur)
    return FauxServeur


def test_lan_not_started_without_pin(coach_home, monkeypatch, faux_serveur):
    save_settings(Settings(lan_enabled=True, pin_hash=None))
    monkeypatch.setattr(instance, "PORTS", (free_port(),))
    launcher.main(["--smoke"])
    assert faux_serveur.instances[0].starts == ["127.0.0.1"]


def test_lan_started_with_pin(coach_home, monkeypatch, faux_serveur):
    save_settings(Settings(lan_enabled=True, pin_hash="x"))
    monkeypatch.setattr(instance, "PORTS", (free_port(),))
    launcher.main(["--smoke"])
    assert faux_serveur.instances[0].starts == ["0.0.0.0"]


def test_set_lan_follows_current_state(coach_home, monkeypatch, faux_serveur):
    captured = {}
    real = launcher.create_app

    def spy(**kw):
        captured["app"] = real(**kw)
        captured["desktop"] = kw["desktop"]
        return captured["app"]

    monkeypatch.setattr(launcher, "create_app", spy)
    monkeypatch.setattr(instance, "PORTS", (free_port(),))
    launcher.main(["--smoke"])
    captured["app"].state.lan = True
    captured["desktop"].set_lan(False)  # l'argument est ignoré : l'état courant prime
    captured["app"].state.lan = False
    captured["desktop"].set_lan(True)
    assert faux_serveur.instances[0].restarts == ["0.0.0.0", "127.0.0.1"]


def test_set_lan_swallows_errors(coach_home, monkeypatch, faux_serveur):
    captured = {}
    real = launcher.create_app
    monkeypatch.setattr(
        launcher, "create_app", lambda **kw: captured.setdefault("d", kw["desktop"]) and real(**kw)
    )
    monkeypatch.setattr(instance, "PORTS", (free_port(),))
    launcher.main(["--smoke"])
    faux_serveur.instances[0].restart = lambda h: (_ for _ in ()).throw(RuntimeError("boum"))
    captured["d"].set_lan(True)  # ne doit pas lever


def test_unexpected_exception_is_fatal(coach_home, monkeypatch, fatals):
    def boom(*a, **k):
        raise RuntimeError("panne")

    monkeypatch.setattr(launcher, "load_settings", boom)
    monkeypatch.setattr(instance, "PORTS", (free_port(),))
    assert launcher.main(["--smoke"]) == 1
    assert fatals == ["panne"]
