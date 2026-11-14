import socket
import threading

import pytest
from fastapi.testclient import TestClient

from coach.api.app import create_app
from coach.api.deps import hash_pin, verify_pin
from coach.config import load_settings, save_settings
from coach.desktop import context
from coach.desktop.context import Desktop, lan_addresses
from coach.desktop.updater import UpdateBusy, UpdateError
from coach.garmin.port import FakeGarminClient, GarminAuthRequired
from coach.llm.provider import FakeLLMProvider
from coach.services.history import HistoryState, save_state
from tests.api.test_app import METRICS

H = {"X-Coach": "1"}


class FakeUpdater:
    def __init__(self):
        self.calls = []
        self.check_error = None
        self.install_error = None

    def view(self):
        return {"state": "idle", "current": "1.0.0"}

    def check(self):
        self.calls.append("check")
        if self.check_error:
            raise self.check_error

    def start_install(self, on_exit):
        self.calls.append(("start_install", on_exit))
        if self.install_error:
            raise self.install_error


class FakeClaude:
    def __init__(self):
        self.calls = []

    def status(self):
        return {"claude_cli": True, "claude_auth": False, "claude_step": "idle", "claude_error": None}

    def start_install(self):
        self.calls.append("install")

    def start_login(self):
        self.calls.append("login")


@pytest.fixture(autouse=True)
def _home(coach_home, repo):
    save_state(repo, HistoryState(status="done"))
    return coach_home


@pytest.fixture
def updater():
    return FakeUpdater()


@pytest.fixture
def claude():
    return FakeClaude()


@pytest.fixture
def lan_calls():
    return []


@pytest.fixture
def lan_done():
    return threading.Event()


@pytest.fixture
def desktop(updater, claude, lan_calls, lan_done):
    def set_lan(enabled):
        lan_calls.append(enabled)
        lan_done.set()

    return Desktop(
        updater=updater,
        claude=claude,
        set_lan=set_lan,
        request_exit=lambda: None,
        lan_addresses=lambda: ["http://192.168.1.5:8765"],
    )


@pytest.fixture
def build(repo, desktop):
    def make(*, lan=False, with_desktop=True, garmin_auth=False):
        def garmin_factory():
            if garmin_auth:
                raise GarminAuthRequired("pas de jetons")
            return FakeGarminClient(metrics=METRICS)

        return create_app(
            lan=lan,
            garmin_factory=garmin_factory,
            llm_factory=lambda: FakeLLMProvider([]),
            repo=repo,
            extra_hosts={"testserver"},
            desktop=desktop if with_desktop else None,
        )

    return make


@pytest.fixture
def app(build):
    return build()


@pytest.fixture
def pc(app):
    return TestClient(app, client=("127.0.0.1", 50000), headers=H)


@pytest.fixture
def phone_with_pin_cookie(build):
    save_settings(load_settings().model_copy(update={"pin_hash": hash_pin("1234")}))
    client = TestClient(build(lan=True), headers=H)
    assert client.post("/api/auth/pin", json={"pin": "1234"}).status_code == 200
    return client


def test_desktop_routes_absent_without_desktop(build):
    assert TestClient(build(with_desktop=False)).get("/api/update").status_code == 404


def test_setup_status(pc):
    body = pc.get("/api/setup/status").json()
    assert body["claude_cli"] is True and body["claude_step"] == "idle"
    assert body["garmin"] == "ok" and body["llm_mode"] == "cli"
    assert "claude_auth" in body


def test_setup_status_garmin_auth_required(build):
    client = TestClient(build(garmin_auth=True), client=("127.0.0.1", 50000))
    assert client.get("/api/setup/status").json()["garmin"] == "auth_required"


@pytest.mark.parametrize(
    "path",
    ["/api/setup/claude/install", "/api/setup/claude/login", "/api/update/check", "/api/update/install", "/api/lan"],
)
def test_phone_cannot_act(phone_with_pin_cookie, updater, claude, path):
    r = phone_with_pin_cookie.post(path, json={"enabled": False})
    assert r.status_code == 403 and r.json()["code"] == "local_only"
    assert updater.calls == [] and claude.calls == []


def test_claude_actions_start(pc, claude):
    assert pc.post("/api/setup/claude/install").json() == {"status": "started"}
    assert pc.post("/api/setup/claude/login").json() == {"status": "started"}
    assert claude.calls == ["install", "login"]


def test_update_view_and_check(pc, updater):
    assert pc.get("/api/update").json()["current"] == "1.0.0"
    assert pc.post("/api/update/check").json()["state"] == "idle"
    assert updater.calls == ["check"]


def test_update_install_starts_and_exits(pc, updater, desktop):
    r = pc.post("/api/update/install")
    assert r.status_code == 202 and r.json() == {"status": "started"}
    assert updater.calls == [("start_install", desktop.request_exit)]


def test_update_install_conflict(pc, updater):
    updater.install_error = UpdateBusy("déjà en cours")
    r = pc.post("/api/update/install")
    assert r.status_code == 409 and r.json()["code"] == "update_running"


def test_update_install_without_update(pc, updater):
    updater.install_error = UpdateError("Aucune mise à jour disponible")
    r = pc.post("/api/update/install")
    assert r.status_code == 409 and r.json()["code"] == "no_update"
    assert r.json()["detail"] == "Aucune mise à jour disponible"


def test_update_check_error(pc, updater):
    updater.check_error = UpdateError("réseau")
    r = pc.post("/api/update/check")
    assert r.status_code == 502 and r.json()["code"] == "update_check_failed"


def test_lan_enable_requires_pin(pc, lan_calls):
    r = pc.post("/api/lan", json={"enabled": True})
    assert r.status_code == 422 and r.json()["code"] == "pin_required_to_enable"
    assert not load_settings().lan_enabled and lan_calls == []


def test_lan_enable_with_pin(pc, app, lan_calls, lan_done):
    r = pc.post("/api/lan", json={"enabled": True, "pin": "1234"})
    assert r.status_code == 200
    assert r.json() == {"enabled": True, "has_pin": True, "addresses": ["http://192.168.1.5:8765"], "local": True}
    s = load_settings()
    assert s.lan_enabled and verify_pin("1234", s.pin_hash)
    assert app.state.lan is True
    assert lan_done.wait(5) and lan_calls == [True]


def test_lan_invalid_pin(pc, app, lan_calls):
    r = pc.post("/api/lan", json={"enabled": True, "pin": "12"})
    assert r.status_code == 422 and r.json()["code"] == "invalid_pin"
    s = load_settings()
    assert not s.lan_enabled and s.pin_hash is None
    assert app.state.lan is False and lan_calls == []


def test_lan_disable_clears_sessions(pc, app, lan_calls, lan_done):
    save_settings(load_settings().model_copy(update={"pin_hash": hash_pin("1234")}))
    app.state.lan = True
    app.state.sessions.add("tok")
    r = pc.post("/api/lan", json={"enabled": False})
    assert r.status_code == 200 and r.json()["enabled"] is False
    assert app.state.sessions == set() and app.state.lan is False
    assert lan_done.wait(5) and lan_calls == [False]


def test_lan_pin_change_clears_sessions_and_lock(pc, app, lan_done):
    save_settings(load_settings().model_copy(update={"pin_hash": hash_pin("1234"), "lan_enabled": True}))
    app.state.lan = True
    app.state.sessions.add("tok")
    app.state.pin_failures = 3
    app.state.pin_locked_until = 1e12
    r = pc.post("/api/lan", json={"enabled": True, "pin": "5678"})
    assert r.status_code == 200
    assert app.state.sessions == set()
    assert app.state.pin_failures == 0 and app.state.pin_locked_until == 0.0
    assert lan_done.wait(5)


def test_lan_enable_without_new_pin_keeps_sessions(pc, app, lan_done):
    save_settings(load_settings().model_copy(update={"pin_hash": hash_pin("1234")}))
    app.state.sessions.add("tok")
    assert pc.post("/api/lan", json={"enabled": True}).status_code == 200
    assert app.state.sessions == {"tok"}
    assert lan_done.wait(5)


def test_lan_view_from_phone_is_read_only(phone_with_pin_cookie):
    body = phone_with_pin_cookie.get("/api/lan").json()
    assert body["local"] is False and body["enabled"] is True and body["has_pin"] is True


def test_lan_toggle_keeps_history_runner(pc, app, lan_done):
    before = app.state.history
    pc.post("/api/lan", json={"enabled": True, "pin": "1234"})
    assert app.state.history is before
    assert lan_done.wait(5)


def test_lan_addresses_filters(monkeypatch):
    monkeypatch.setattr(context, "_primary_ip", lambda: None)
    infos = [
        (socket.AF_INET, 0, 0, "", (ip, 0))
        for ip in ["127.0.0.1", "169.254.3.4", "192.168.1.20", "8.8.8.8", "10.0.0.2", "192.168.1.20"]
    ]
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: infos)
    assert lan_addresses(8765) == ["http://10.0.0.2:8765", "http://192.168.1.20:8765"]


def test_lan_addresses_keeps_only_primary_interface(monkeypatch):
    # WSL et Hyper-V ajoutent des cartes virtuelles en 172.x injoignables depuis le téléphone
    monkeypatch.setattr(context, "_primary_ip", lambda: "192.168.1.73")
    infos = [(socket.AF_INET, 0, 0, "", (ip, 0)) for ip in ["192.168.1.73", "172.25.48.1", "172.27.240.1"]]
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: infos)
    assert lan_addresses(8765) == ["http://192.168.1.73:8765"]


def test_lan_addresses_ignores_public_primary(monkeypatch):
    monkeypatch.setattr(context, "_primary_ip", lambda: "8.8.4.4")
    infos = [(socket.AF_INET, 0, 0, "", ("192.168.1.20", 0))]
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: infos)
    assert lan_addresses(8765) == ["http://192.168.1.20:8765"]
