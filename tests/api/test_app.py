import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from coach.api.app import create_app
from coach.api.deps import hash_pin, verify_pin
from coach.config import load_settings, save_settings
from coach.garmin.port import FakeGarminClient, GarminAuthRequired, Metrics
from coach.llm.provider import FakeLLMProvider, LLMUsageLimit
from coach.plan.models import Activity
from tests.llm.factories import valid_plan_json

FIXTURES = Path(__file__).parent.parent / "fixtures" / "gpx"
METRICS = Metrics(hr_max=190, hr_rest=50, threshold_pace_s_km=300)
GOAL_FORM = {
    "type": "trail",
    "distance_km": "42",
    "d_plus_m": "2000",
    "race_date": "2027-02-07",
    "sessions_per_week": "3",
}


class FakeLogin:
    """Remplace GarminClient pour la connexion (MFA obligatoire si demandé)."""

    def __init__(self, mfa: bool):
        self.mfa = mfa
        self.seen: list[tuple] = []

    def start_login(self, email, password, tokenstore):
        self.seen.append(("start", email, password))
        return ("needs_mfa", {"secret": "state"}) if self.mfa else ("ok", object())

    def finish_login(self, state, code, tokenstore):
        self.seen.append(("finish", state, code))
        return object()


class LimitedLLM:
    def complete(self, system, prompt):
        raise LLMUsageLimit("limite")


@pytest.fixture(autouse=True)
def _home(coach_home):
    return coach_home


@pytest.fixture
def fake_garmin():
    return FakeGarminClient(metrics=METRICS)


@pytest.fixture
def make_client(repo, fake_garmin):
    def build(*, lan=False, garmin=None, llm=None, login=None, **kw):
        def garmin_factory():
            if garmin == "auth":
                raise GarminAuthRequired("pas de jetons")
            return garmin or fake_garmin

        app = create_app(
            lan=lan,
            garmin_factory=garmin_factory,
            llm_factory=lambda: llm or FakeLLMProvider([]),
            repo=repo,
            login_client=login or FakeLogin(False),
            **kw,
        )
        return TestClient(app)

    return build


def _create_goal(client, **over):
    return client.post("/api/goals", data={**GOAL_FORM, **over})


def test_status_reports_auth_required(make_client):
    r = make_client(garmin="auth").get("/api/status")
    assert r.status_code == 200
    body = r.json()
    assert body["garmin"] == "auth_required"
    assert body["goal"] is None and body["pending_proposal_id"] is None
    assert body["llm_mode"] == "cli"


def test_login_mfa_flow(make_client):
    login = FakeLogin(True)
    client = make_client(login=login)
    r = client.post("/api/garmin/login", json={"email": "a@b.c", "password": "pw"})
    assert r.json()["status"] == "needs_mfa"
    login_id = r.json()["login_id"]
    assert "state" not in r.text and "secret" not in r.text
    r = client.post("/api/garmin/mfa", json={"login_id": login_id, "code": "123456"})
    assert r.json() == {"status": "ok"}
    assert login.seen[-1] == ("finish", {"secret": "state"}, "123456")
    # l'identifiant est à usage unique
    assert client.post("/api/garmin/mfa", json={"login_id": login_id, "code": "1"}).status_code == 422


def test_login_ok_without_mfa(make_client):
    r = make_client().post("/api/garmin/login", json={"email": "a@b.c", "password": "pw"})
    assert r.json() == {"status": "ok"}


def test_mfa_state_expires(make_client):
    now = [0.0]
    client = make_client(login=FakeLogin(True), clock=lambda: now[0])
    login_id = client.post("/api/garmin/login", json={"email": "a", "password": "p"}).json()["login_id"]
    now[0] = 601
    r = client.post("/api/garmin/mfa", json={"login_id": login_id, "code": "1"})
    assert r.status_code == 422 and r.json()["code"] == "mfa_expired"


def test_goal_too_close_returns_422(make_client):
    r = _create_goal(make_client(), race_date="2026-11-10")
    assert r.status_code == 422
    assert "14 jours" in r.json()["detail"]


def test_broken_gpx_returns_422(make_client):
    gpx = (FIXTURES / "broken.gpx").read_bytes()
    r = make_client().post(
        "/api/goals", data=GOAL_FORM, files={"gpx": ("route.gpx", gpx, "application/gpx+xml")}
    )
    assert r.status_code == 422
    assert r.json()["detail"]


def test_goal_with_gpx_created(make_client):
    gpx = (FIXTURES / "climb.gpx").read_bytes()
    r = make_client().post(
        "/api/goals",
        data={**GOAL_FORM, "d_plus_m": "0"},
        files={"gpx": ("route.gpx", gpx, "application/gpx+xml")},
    )
    assert r.status_code == 200
    assert r.json()["gpx_summary"] is not None


def test_generate_accept_and_plan(make_client):
    client = make_client(llm=FakeLLMProvider([valid_plan_json(14, 3)]))
    assert client.get("/api/plan").json() == {"goal": None, "weeks": []}
    goal = _create_goal(client).json()
    assert client.post(f"/api/goals/{goal['id']}/generate").status_code == 200
    assert client.post(f"/api/goals/{goal['id']}/accept").json() == {"status": "ok"}

    plan = client.get("/api/plan").json()
    assert plan["goal"]["id"] == goal["id"] and plan["goal"]["plan_accepted"] is True
    assert len(plan["weeks"]) == 14
    week1 = plan["weeks"][0]
    assert week1["week_index"] == 1 and week1["week_monday"] == "2026-11-02"
    assert [s["order"] for s in week1["sessions"]] == [1, 2, 3]
    s = week1["sessions"][0]
    assert s["status"] == "todo" and isinstance(s["steps"], list) and s["steps"][0]["kind"] == "warmup"
    assert s["suggested_day"] and s["scheduled_date"] is None and s["sync_error"] is None
    assert client.get("/api/status").json()["goal"]["id"] == goal["id"]


def test_export_check_returns_warnings(make_client):
    client = make_client(llm=FakeLLMProvider([valid_plan_json(14, 3)]))
    goal = _create_goal(client).json()
    client.post(f"/api/goals/{goal['id']}/generate")
    client.post(f"/api/goals/{goal['id']}/accept")
    sid = client.get("/api/plan").json()["weeks"][0]["sessions"][0]["id"]
    r = client.get(f"/api/sessions/{sid}/export-check", params={"date": "2026-11-03"})
    assert r.status_code == 200 and r.json() == {"warnings": []}
    r = client.get("/api/sessions/9999/export-check", params={"date": "2026-11-03"})
    assert r.status_code == 422


def test_export_and_unschedule(make_client, fake_garmin):
    client = make_client(llm=FakeLLMProvider([valid_plan_json(14, 3)]))
    goal = _create_goal(client).json()
    client.post(f"/api/goals/{goal['id']}/generate")
    client.post(f"/api/goals/{goal['id']}/accept")
    # zones nécessaires à l'export : générées par la génération (snapshot)
    sid = client.get("/api/plan").json()["weeks"][0]["sessions"][0]["id"]
    r = client.post(f"/api/sessions/{sid}/export", json={"date": "2026-11-03"})
    assert r.status_code == 200 and "warnings" in r.json()
    assert fake_garmin.schedules
    r = client.post(f"/api/sessions/{sid}/unschedule")
    assert r.status_code == 200 and not fake_garmin.schedules


def test_sync_returns_result(make_client):
    r = make_client().post("/api/sync")
    assert r.status_code == 200
    assert r.json() == {"new_activities": 0, "matched": 0, "missed": 0, "proposal_id": None}


def test_manual_match(make_client, repo):
    client = make_client(llm=FakeLLMProvider([valid_plan_json(14, 3)]))
    goal = _create_goal(client).json()
    client.post(f"/api/goals/{goal['id']}/generate")
    sid = client.get("/api/plan").json()["weeks"][0]["sessions"][0]["id"]
    from datetime import date

    act = repo.add(Activity(garmin_activity_id=1, date=date(2026, 11, 3), type_key="running"))
    assert client.post(f"/api/activities/{act.id}/match", json={"session_id": sid}).status_code == 200
    with repo.transaction() as db:
        a = db.get(Activity, act.id)
    assert a.session_id == sid and a.match_source == "manual"
    assert repo.session(sid).status == "done"
    assert client.post(f"/api/activities/{act.id}/match", json={"session_id": None}).status_code == 200
    assert repo.session(sid).status == "todo"
    assert client.post("/api/activities/999/match", json={"session_id": None}).status_code == 404


def test_llm_limit_maps_to_429_with_code(make_client):
    client = make_client(llm=LimitedLLM())
    goal = _create_goal(client).json()
    r = client.post(f"/api/goals/{goal['id']}/generate")
    assert r.status_code == 429
    assert r.json()["code"] == "llm_limit"


def test_garmin_auth_maps_to_401(make_client):
    r = make_client(garmin="auth").post("/api/sync")
    assert r.status_code == 401 and r.json()["code"] == "garmin_auth"


def test_proposals_pending_empty(make_client):
    assert make_client().get("/api/proposals/pending").json() is None
    assert make_client().post("/api/proposals/5/reject").status_code == 422


def test_lan_requires_pin(make_client):
    save_settings(load_settings().model_copy(update={"pin_hash": hash_pin("1234")}))
    client = make_client(lan=True)
    r = client.get("/api/status")
    assert r.status_code == 401 and r.json()["code"] == "pin_required"
    assert client.post("/api/auth/pin", json={"pin": "0000"}).status_code == 401
    r = client.post("/api/auth/pin", json={"pin": "1234"})
    assert r.status_code == 200
    cookie = r.headers["set-cookie"].lower()
    assert "coach_session=" in cookie and "httponly" in cookie and "samesite=strict" in cookie
    assert client.get("/api/status").status_code == 200


def test_pin_rate_limited_after_five_failures(make_client):
    save_settings(load_settings().model_copy(update={"pin_hash": hash_pin("1234")}))
    now = [0.0]
    client = make_client(lan=True, clock=lambda: now[0])
    for _ in range(5):
        assert client.post("/api/auth/pin", json={"pin": "bad"}).status_code == 401
    assert client.post("/api/auth/pin", json={"pin": "1234"}).status_code == 429
    now[0] = 61
    assert client.post("/api/auth/pin", json={"pin": "1234"}).status_code == 200


def test_lan_without_pin_refuses_to_start(make_client):
    with pytest.raises(ValueError):
        make_client(lan=True)


def test_local_mode_needs_no_pin(make_client):
    assert make_client().get("/api/status").status_code == 200


def test_pin_hash_format():
    h = hash_pin("1234")
    algo, iters, salt, digest = h.split("$")
    assert (algo, iters) == ("pbkdf2_sha256", "200000")
    assert len(bytes.fromhex(salt)) == 16 and bytes.fromhex(digest)
    assert verify_pin("1234", h) and not verify_pin("1235", h)
    assert not verify_pin("1234", "garbage")
    assert hash_pin("1234") != h


def test_settings_never_returns_api_key(make_client):
    client = make_client()
    assert client.get("/api/settings").json() == {
        "llm_mode": "cli",
        "anthropic_model": "claude-sonnet-5-5",
        "has_api_key": False,
    }
    r = client.put(
        "/api/settings",
        json={"llm_mode": "api", "anthropic_api_key": "sk-secret-123", "anthropic_model": "m1"},
    )
    assert r.json() == {"llm_mode": "api", "anthropic_model": "m1", "has_api_key": True}
    assert "sk-secret-123" not in r.text
    got = client.get("/api/settings")
    assert got.json()["has_api_key"] is True and "sk-secret-123" not in got.text
    assert load_settings().anthropic_api_key == "sk-secret-123"
    # sans clé dans la requête : inchangée ; chaîne vide : effacée
    client.put("/api/settings", json={"llm_mode": "api"})
    assert load_settings().anthropic_api_key == "sk-secret-123"
    r = client.put("/api/settings", json={"llm_mode": "cli", "anthropic_api_key": ""})
    assert r.json()["has_api_key"] is False and load_settings().anthropic_api_key is None


def test_password_not_logged(make_client, caplog):
    caplog.set_level(logging.DEBUG)
    login = FakeLogin(False)
    client = make_client(login=login)
    client.post("/api/garmin/login", json={"email": "a@b.c", "password": "S3cr3t-pw-xyz"})
    assert login.seen[0][2] == "S3cr3t-pw-xyz"
    assert "S3cr3t-pw-xyz" not in caplog.text
    assert all("S3cr3t-pw-xyz" not in r.getMessage() for r in caplog.records)
