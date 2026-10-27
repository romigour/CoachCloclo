import logging
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from coach.api.app import create_app
from coach.api.deps import hash_pin, verify_pin
from coach.config import load_settings, save_settings
from coach.garmin.port import FakeGarminClient, GarminAuthRequired, Metrics
from coach.llm.provider import FakeLLMProvider, LLMError, LLMUsageLimit
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
        self.bad = False
        self.seen: list[tuple] = []

    def start_login(self, email, password, tokenstore):
        self.seen.append(("start", email, password))
        if self.bad:
            raise GarminAuthRequired("refusé")
        return ("needs_mfa", {"secret": "state"}) if self.mfa else ("ok", object())

    def finish_login(self, state, code, tokenstore):
        self.seen.append(("finish", state, code))
        return object()


class LimitedLLM:
    def complete(self, system, prompt):
        raise LLMUsageLimit("limite")


class BrokenLLM:
    """Erreur LLM générique (ex. jeton OAuth du CLI expiré, réponse illisible)."""

    def complete(self, system, prompt):
        raise LLMError("Réponse illisible du CLI claude (code 1) : OAuth token has expired")


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
            extra_hosts={"testserver"},
            **kw,
        )
        return TestClient(app, headers={"X-Coach": "1"})

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
    r = client.post(f"/api/sessions/{sid}/export", json={"date": "2026-11-03"})  # avant aujourd'hui
    assert r.status_code == 422 and "passée" in r.json()["detail"]
    r = client.post(f"/api/sessions/{sid}/export", json={"date": "2026-11-05"})
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


def test_activities_of_plan_week(make_client, repo):
    from datetime import date

    client = make_client(llm=FakeLLMProvider([valid_plan_json(14, 3)]))
    assert client.get("/api/activities?week=1").json() == []  # pas d'objectif
    goal = _create_goal(client).json()
    monday = date.fromisoformat(client.get("/api/plan").json()["goal"]["plan_start"])
    from datetime import timedelta

    inside = repo.add(Activity(garmin_activity_id=11, date=monday + timedelta(days=6), type_key="running",
                               duration_s=3100.0, distance_m=10200.0, d_plus_m=50.0, avg_hr=150.0))
    first = repo.add(Activity(garmin_activity_id=12, date=monday, type_key="running"))
    repo.add(Activity(garmin_activity_id=13, date=monday + timedelta(days=7), type_key="running"))
    repo.add(Activity(garmin_activity_id=14, date=monday - timedelta(days=1), type_key="running"))
    rows = client.get("/api/activities?week=1").json()
    assert [r["id"] for r in rows] == [first.id, inside.id]
    assert rows[1] == {
        "id": inside.id, "date": (monday + timedelta(days=6)).isoformat(), "type_key": "running",
        "duration_s": 3100.0, "distance_m": 10200.0, "d_plus_m": 50.0, "avg_hr": 150.0,
        "session_id": None, "match_source": None,
    }
    assert len(client.get("/api/activities?week=2").json()) == 1
    assert client.get("/api/activities").status_code == 422  # week obligatoire
    assert goal["id"]


def test_activities_respects_host_and_pin(make_client):
    client = make_client()
    assert client.get("/api/activities?week=1", headers={"Host": "evil.example"}).status_code == 400
    save_settings(load_settings().model_copy(update={"pin_hash": hash_pin("1234")}))
    lan = make_client(lan=True)
    assert lan.get("/api/activities?week=1").json()["code"] == "pin_required"
    lan.post("/api/auth/pin", json={"pin": "1234"})
    assert lan.get("/api/activities?week=1").status_code == 200


def test_llm_limit_maps_to_429_with_code(make_client):
    client = make_client(llm=LimitedLLM())
    goal = _create_goal(client).json()
    r = client.post(f"/api/goals/{goal['id']}/generate")
    assert r.status_code == 429
    assert r.json()["code"] == "llm_limit"


def test_generic_llm_error_maps_to_502_on_generate(make_client):
    client = make_client(llm=BrokenLLM())
    goal = _create_goal(client).json()
    r = client.post(f"/api/goals/{goal['id']}/generate")
    assert r.status_code == 502
    assert r.json() == {
        "code": "llm_error",
        "detail": "Réponse illisible du CLI claude (code 1) : OAuth token has expired",
    }


def test_generic_llm_error_maps_to_502_on_sync(make_client, fake_garmin):
    from datetime import date

    from coach.garmin.port import ActivitySummary

    client = make_client(llm=FakeLLMProvider([valid_plan_json(14, 3)]))
    goal = _create_goal(client).json()
    client.post(f"/api/goals/{goal['id']}/generate")
    client.post(f"/api/goals/{goal['id']}/accept")
    fake_garmin._activities = [
        ActivitySummary(garmin_id=1, date=date(2026, 11, 3), type_key="running",
                        duration_s=2700, distance_m=9000, raw={})
    ]
    client.app.state.llm_factory = lambda: BrokenLLM()
    r = client.post("/api/sync")
    assert r.status_code == 502 and r.json()["code"] == "llm_error"


@pytest.mark.parametrize(
    "field,value", [("sessions_per_week", "1"), ("sessions_per_week", "8"), ("distance_km", "0")]
)
def test_invalid_goal_values_return_422(make_client, field, value):
    r = _create_goal(make_client(), **{field: value})
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "invalid"
    assert body["detail"] and all(set(e) == {"loc", "msg"} for e in body["detail"])
    assert any(field in e["loc"] for e in body["detail"])


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
    with pytest.raises(ValueError, match="coach start --lan"):
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


def test_csrf_requires_header(make_client):
    client = make_client()
    r = client.post("/api/proposals/1/accept", headers={"X-Coach": ""})
    assert r.status_code == 403 and r.json()["code"] == "csrf"
    assert client.get("/api/status", headers={"X-Coach": ""}).status_code == 200


def test_csrf_rejects_foreign_origin_and_fetch_site(make_client):
    client = make_client()
    r = client.post("/api/proposals/1/reject", headers={"Origin": "http://evil.example"})
    assert r.status_code == 403
    r = client.post("/api/proposals/1/reject", headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
    r = client.post("/api/proposals/1/reject", headers={"Origin": "http://testserver"})
    assert r.status_code == 422  # passe le filtre, erreur métier


def test_host_check(make_client):
    client = make_client()
    assert client.get("/api/status", headers={"Host": "evil.example"}).status_code == 400
    assert client.get("/api/status", headers={"Host": "localhost:8765"}).status_code == 200
    assert client.get("/api/status", headers={"Host": "[::1]:8765"}).status_code == 200
    assert client.get("/api/status", headers={"Host": "192.168.1.5:8765"}).status_code == 400


def test_lan_host_allows_ip_literal(make_client):
    save_settings(load_settings().model_copy(update={"pin_hash": hash_pin("1234")}))
    client = make_client(lan=True)
    r = client.post("/api/auth/pin", json={"pin": "1234"}, headers={"Host": "192.168.1.5:8765"})
    assert r.status_code == 200
    assert client.get("/api/status", headers={"Host": "evil.example"}).status_code == 400


def test_pin_attempts_are_atomic(make_client):
    save_settings(load_settings().model_copy(update={"pin_hash": hash_pin("1234")}))
    client = make_client(lan=True, clock=lambda: 0.0)
    n = 16
    barrier = threading.Barrier(n)
    codes: list[int] = []

    def attempt():
        barrier.wait()
        codes.append(client.post("/api/auth/pin", json={"pin": "bad"}).status_code)

    threads = [threading.Thread(target=attempt) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert codes.count(401) == 5 and codes.count(429) == n - 5


def test_validation_error_does_not_echo_secrets(make_client):
    client = make_client()
    r = client.put("/api/settings", json={"llm_mode": "bogus", "anthropic_api_key": "sk-secret-123"})
    assert r.status_code == 422 and r.json()["code"] == "invalid"
    assert "sk-secret-123" not in r.text and "bogus" not in r.text
    r = client.post("/api/garmin/login", json={"email": 123, "password": "S3cr3t-pw"})
    assert r.status_code == 422 and "S3cr3t-pw" not in r.text
    r = client.post(
        "/api/garmin/login",
        content='{"password": "S3cr3t-pw", ',
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 422 and "S3cr3t-pw" not in r.text


def test_gpx_too_large(make_client):
    big = b"x" * (10 * 1024 * 1024 + 1)
    r = make_client().post("/api/goals", data=GOAL_FORM, files={"gpx": ("r.gpx", big, "application/gpx+xml")})
    assert r.status_code == 413 and r.json()["code"] == "too_large"


def test_status_garmin_unavailable(make_client):
    from coach.garmin.port import GarminUnavailable

    def boom():
        raise GarminUnavailable("down")

    client = make_client()
    client.app.state.garmin_factory = boom
    assert client.get("/api/status").json()["garmin"] == "unavailable"


def test_wrong_garmin_password(make_client):
    login = FakeLogin(False)
    login.bad = True
    r = make_client(login=login).post("/api/garmin/login", json={"email": "a", "password": "p"})
    assert r.status_code == 401
    assert r.json() == {"code": "garmin_login_failed", "detail": "Identifiants Garmin refusés"}
