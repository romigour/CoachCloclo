import logging
import threading
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from coach.api.app import create_app
from coach.analysis.zones import Zones, compute_zones
from coach.api.deps import hash_pin, valid_pin, verify_pin
from coach.config import load_settings, save_settings
from coach.version import app_version
from coach.garmin.port import FakeGarminClient, GarminAuthRequired, LapSummary, Metrics
from coach.llm.provider import FakeLLMProvider, LLMError, LLMUsageLimit
from coach.plan.models import Activity, AthleteSnapshot, Race
from coach.services.history import HistoryState, save_state
from tests.llm.factories import valid_plan_json
from tests.plan.factories import make_activity, make_db_session, make_goal

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


@pytest.fixture(autouse=True)
def _history_done(_home):
    """Historique déjà importé : POST /api/sync ne lance pas d'import en arrière-plan."""
    save_state(HistoryState(status="done"))


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


def test_post_goal_with_target_time(make_client):
    r = _create_goal(make_client(), target_time="1:50")
    assert r.status_code == 200
    assert (r.json()["target_time_s"], r.json()["target_source"]) == (6600, "user")


def test_post_goal_empty_target_time_is_claude_mode(make_client):
    r = _create_goal(make_client(), target_time="")
    assert (r.json()["target_time_s"], r.json()["target_source"]) == (None, "claude")


def test_post_goal_bad_target_time(make_client):
    assert _create_goal(make_client(), target_time="abc").status_code == 422


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


LAP = LapSummary(index=0, duration_s=600, distance_m=1800, avg_hr=140, step_order=1, raw={"x": 1})


def _db_session(repo):
    """Séance persistée (un échauffement Z2 de 10 min) sans activité."""
    goal = repo.add(make_goal())
    return repo.add(make_db_session(goal.id))


def _zones() -> Zones:
    return compute_zones(threshold_pace_s_km=300, pred_10k_s=None, garmin_hr_zones=None, hr_max=190, hr_rest=50)


class CountingGarmin(FakeGarminClient):
    """FakeGarminClient qui note les identifiants dont on lit les tours."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.laps_calls: list[int] = []

    def activity_laps(self, garmin_id):
        self.laps_calls.append(garmin_id)
        return super().activity_laps(garmin_id)


def test_comparison_reasons_and_payload(make_client, repo):
    session = _db_session(repo)
    client = make_client()
    url = f"/api/sessions/{session.id}/comparison"
    assert client.get(url).json() == {"available": False, "reason": "no_activity"}

    act = repo.add(make_activity(session_id=session.id))
    assert client.get(url).json() == {"available": False, "reason": "no_laps"}

    repo.save_laps(act.id, [LAP])
    repo.add(AthleteSnapshot(date=date(2026, 11, 1), zones_json=_zones().model_dump_json()))
    r = client.get(url)
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True and body["followed_workout"] is True
    assert body["steps"][0]["verdict"] is not None
    assert len(body["laps"]) == 1 and "raw" not in body["laps"][0]


def test_comparison_unknown_session_is_404(make_client):
    r = make_client().get("/api/sessions/999/comparison")
    assert r.status_code == 404 and r.json()["code"] == "not_found"


def test_comparison_without_snapshot_has_no_verdicts(make_client, repo):
    session = _db_session(repo)
    act = repo.add(make_activity(session_id=session.id))
    repo.save_laps(act.id, [LAP])
    r = make_client().get(f"/api/sessions/{session.id}/comparison")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True and body["followed_workout"] is True
    assert body["steps"][0]["verdict"] is None


def test_zones_null_without_snapshot(make_client):
    assert make_client().get("/api/zones").json() is None


def test_zones_from_latest_snapshot(make_client, repo):
    repo.add(AthleteSnapshot(date=date(2026, 11, 1), zones_json=_zones().model_dump_json()))
    body = make_client().get("/api/zones").json()
    assert body["pace"]["VMA"] == [264, 279]
    assert body["hr"]["Z2"] == [134, 148]


def test_manual_match_fetches_laps(make_client, repo, fake_garmin):
    session = _db_session(repo)
    act = repo.add(make_activity(garmin_activity_id=7))
    fake_garmin._laps[7] = [LAP]
    r = make_client().post(f"/api/activities/{act.id}/match", json={"session_id": session.id})
    assert r.status_code == 200 and r.json() == {"status": "ok"}
    assert len(repo.laps(act.id)) == 1


def test_manual_match_ok_when_garmin_logged_out(make_client, repo):
    session = _db_session(repo)
    act = repo.add(make_activity(garmin_activity_id=7))
    r = make_client(garmin="auth").post(f"/api/activities/{act.id}/match", json={"session_id": session.id})
    assert r.status_code == 200 and r.json() == {"status": "ok"}
    assert repo.laps(act.id) is None


def test_manual_match_ok_when_laps_fail(make_client, repo):
    session = _db_session(repo)
    act = repo.add(make_activity(garmin_activity_id=7))
    garmin = FakeGarminClient(laps={7: [LAP]}, fail_on={"activity_laps"})
    r = make_client(garmin=garmin).post(f"/api/activities/{act.id}/match", json={"session_id": session.id})
    assert r.status_code == 200 and r.json() == {"status": "ok"}
    assert repo.laps(act.id) is None


def test_rematched_activity_keeps_its_laps(make_client, repo):
    goal = repo.add(make_goal())
    first = repo.add(make_db_session(goal.id))
    second = repo.add(make_db_session(goal.id, order=2))
    act = repo.add(make_activity(garmin_activity_id=7, session_id=first.id))
    repo.save_laps(act.id, [LAP])
    garmin = CountingGarmin(laps={7: [LAP]})
    client = make_client(garmin=garmin)
    r = client.post(f"/api/activities/{act.id}/match", json={"session_id": second.id})
    assert r.status_code == 200
    assert garmin.laps_calls == []
    body = client.get(f"/api/sessions/{second.id}/comparison").json()
    assert body["available"] is True


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


def test_free_activities_of_last_days(make_client, repo):
    from datetime import date, timedelta

    today = date.today()
    client = make_client()
    recent = repo.add(Activity(garmin_activity_id=21, date=today - timedelta(days=2), type_key="running",
                               duration_s=1800.0))
    oldest = repo.add(Activity(garmin_activity_id=22, date=today - timedelta(days=14), type_key="trail_running"))
    repo.add(Activity(garmin_activity_id=23, date=today - timedelta(days=15), type_key="running"))
    repo.add(Activity(garmin_activity_id=24, date=today, type_key="running", session_id=7))
    repo.add(Activity(garmin_activity_id=25, date=today, type_key="cycling"))
    rows = client.get("/api/activities/free?days=14").json()
    assert [r["id"] for r in rows] == [recent.id, oldest.id]
    assert rows[0]["duration_s"] == 1800.0 and rows[0]["session_id"] is None
    assert client.get("/api/activities/free?days=0").status_code == 422


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
    session = client.get("/api/plan").json()["weeks"][0]["sessions"][0]
    assert client.post(f"/api/sessions/{session['id']}/export", json={"date": "2026-11-05"}).status_code == 200
    fake_garmin._activities = [
        ActivitySummary(garmin_id=1, date=date(2026, 11, 4), type_key="running",
                        duration_s=600, distance_m=2000, raw={})
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


# --- statistiques, compétitions, import ---------------------------------------------------------


class FakeRunner:
    def __init__(self, result: bool = True, running: bool = False):
        self.result = result
        self.running = running
        self.calls = 0

    def start(self) -> bool:
        self.calls += 1
        return self.result


def _add_activity(repo, garmin_id: int, day: str, raw: str = "{}") -> int:
    from datetime import date

    with repo.transaction() as db:
        a = Activity(garmin_activity_id=garmin_id, date=date.fromisoformat(day),
                     type_key="running", raw_json=raw)
        db.add(a)
        db.flush()
        return a.id


def test_stats_activities_merges_races(make_client, repo):
    a1 = _add_activity(repo, 1, "2026-01-02")
    a2 = _add_activity(repo, 2, "2026-01-01")
    with repo.transaction() as db:
        db.add(Race(activity_id=a1, name="Marathon"))
    rows = make_client().get("/api/stats/activities").json()["activities"]
    assert [r["id"] for r in rows] == [a2, a1]
    assert rows[0]["race"] is None
    assert rows[1]["race"]["name"] == "Marathon"


def test_put_race_validates_rank(make_client, repo):
    a = _add_activity(repo, 1, "2026-01-01")
    client = make_client()
    r = client.put(f"/api/races/{a}", json={"overall_rank": 50, "overall_total": 10})
    assert r.status_code == 422 and r.json()["code"] == "invalid"
    r = client.put(f"/api/races/{a}", json={"official_time_s": 0})
    assert r.status_code == 422
    r = client.put(f"/api/races/{a}", json={"official_time_s": 3600, "name": "10 km"})
    assert r.status_code == 200
    assert r.json()["race"]["official_time_s"] == 3600


def test_put_race_unknown_activity_404(make_client):
    r = make_client().put("/api/races/999", json={"name": "x"})
    assert r.status_code == 404 and r.json()["code"] == "not_found"


def test_delete_race_unknown_activity_404(make_client):
    assert make_client().delete("/api/races/999").status_code == 404


def test_delete_race_excludes_detected_race(make_client, repo):
    a = _add_activity(repo, 1, "2026-01-01", '{"eventType": {"typeKey": "race"}}')
    client = make_client()
    assert client.get("/api/stats/activities").json()["activities"][0]["race"] is not None
    r = client.delete(f"/api/races/{a}")
    assert r.status_code == 200 and r.json() == {"status": "ok"}
    assert client.get("/api/stats/activities").json()["activities"][0]["race"] is None


def test_delete_race_requires_csrf_header(make_client, repo):
    a = _add_activity(repo, 1, "2026-01-01")
    client = make_client()
    r = client.delete(f"/api/races/{a}", headers={"X-Coach": "0"})
    assert r.status_code == 403


def test_history_import_conflict(make_client):
    client = make_client()
    client.app.state.history = FakeRunner(result=False)
    r = client.post("/api/history/import")
    assert r.status_code == 409 and r.json()["code"] == "history_running"


def test_history_import_started(make_client):
    client = make_client()
    client.app.state.history = FakeRunner(result=True)
    assert client.post("/api/history/import").json() == {"status": "started"}


def test_status_has_activities_and_history(make_client, repo):
    client = make_client()
    body = client.get("/api/status").json()
    assert body["has_activities"] is False
    assert body["history"] == {"status": "done", "imported": 0, "error": None}
    _add_activity(repo, 1, "2026-01-01")
    save_state(HistoryState(status="error", imported=5, error="boum"))
    body = client.get("/api/status").json()
    assert body["has_activities"] is True
    assert body["history"] == {"status": "error", "imported": 5, "error": "boum"}


def test_status_reports_running_when_runner_running(make_client):
    client = make_client()
    save_state(HistoryState(status="idle"))
    client.app.state.history = FakeRunner(running=True)
    assert client.get("/api/status").json()["history"]["status"] == "running"


def test_sync_starts_history_import_once(make_client):
    save_state(HistoryState())  # idle
    client = make_client()
    runner = FakeRunner()
    client.app.state.history = runner
    assert client.post("/api/sync").status_code == 200
    assert runner.calls == 1
    save_state(HistoryState(status="done"))
    client.post("/api/sync")
    assert runner.calls == 1


def test_records_endpoint(make_client, repo):
    from datetime import date

    from coach.plan.models import PersonalRecord

    repo.replace_records([PersonalRecord(kind="5k", value=1200.0, garmin_activity_id=7, date=date(2026, 1, 1))])
    r = make_client().get("/api/stats/records").json()
    assert r == {"records": [{"kind": "5k", "value": 1200.0, "garmin_activity_id": 7, "date": "2026-01-01"}]}


def test_stats_activities_tolerates_nan_in_raw_json(make_client, repo):
    _add_activity(repo, 1, "2026-01-01", '{"maxHR": NaN, "vO2MaxValue": Infinity}')
    r = make_client().get("/api/stats/activities")
    assert r.status_code == 200
    assert r.json()["activities"][0]["max_hr"] is None


def test_put_race_rank_message_without_pydantic_prefix(make_client, repo):
    a = _add_activity(repo, 1, "2026-01-01")
    r = make_client().put(f"/api/races/{a}", json={"overall_rank": 50, "overall_total": 10})
    assert r.status_code == 422
    assert r.json()["detail"][0]["msg"].startswith("Le classement")


def _with_pin():
    save_settings(load_settings().model_copy(update={"pin_hash": hash_pin("1234")}))


def test_lan_loopback_needs_no_pin(make_client):
    _with_pin()
    app = make_client(lan=True).app
    pc = TestClient(app, client=("127.0.0.1", 50000), headers={"X-Coach": "1"})
    assert pc.get("/api/status").status_code == 200


def test_lan_other_client_needs_pin(make_client):
    _with_pin()
    r = make_client(lan=True).get("/api/status")
    assert r.status_code == 401 and r.json()["code"] == "pin_required"


def test_lan_toggle_at_runtime(make_client):
    _with_pin()
    client = make_client(lan=False)
    assert client.get("/api/status", headers={"Host": "192.168.1.12:8765"}).status_code == 400
    client.app.state.lan = True
    assert client.get("/api/status").status_code == 401
    assert client.get("/api/status", headers={"Host": "192.168.1.12:8765"}).status_code == 401


def test_lan_off_rejects_ip_host(make_client):
    _with_pin()
    client = make_client(lan=True)
    client.app.state.lan = False
    r = client.get("/api/status", headers={"Host": "192.168.1.12:8765"})
    assert r.status_code == 400 and r.json()["code"] == "bad_host"


def test_version_endpoint(make_client):
    _with_pin()
    r = make_client(lan=True).get("/api/version")
    assert r.status_code == 200 and r.json() == {"version": app_version()}


@pytest.mark.parametrize("pin,ok", [("1234", True), ("123456789012", True), ("123", False),
                                    ("1234567890123", False), ("12a4", False), ("", False)])
def test_valid_pin(pin, ok):
    assert valid_pin(pin) is ok


def _create_trail_goal(client) -> int:
    gpx = (FIXTURES / "climb.gpx").read_bytes()
    r = client.post("/api/goals", data=GOAL_FORM, files={"gpx": ("route.gpx", gpx, "application/gpx+xml")})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_race_plan_routes(make_client):
    client = make_client()
    gid = _create_trail_goal(client)
    url = f"/api/goals/{gid}/race-plan"

    r = client.get(url)
    assert r.status_code == 200
    assert r.json()["plan"]["segments"]

    r = client.put(url, json={"aid_stations": [{"name": "A", "km": 10, "kind": "eau", "cutoff": "8h"}]})
    assert r.status_code == 422
    assert any("cutoff" in e["loc"] for e in r.json()["detail"])

    r = client.put(url, json={"start_time": "07:30"})
    assert r.status_code == 200
    assert r.json()["settings"]["start_time"] == "07:30"
    assert r.json()["target_time_s"] is None

    assert client.post(f"{url}/refresh").status_code == 200
    assert client.post(f"{url}/reimport").status_code == 200

    r = client.post(f"{url}/export")
    assert r.status_code == 200
    assert r.json()["workout_id"] is not None


def test_race_plan_archived_goal_422(make_client):
    client = make_client()
    first = _create_trail_goal(client)
    _create_trail_goal(client)
    r = client.get(f"/api/goals/{first}/race-plan")
    assert r.status_code == 422
