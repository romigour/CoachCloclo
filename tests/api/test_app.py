import logging
import sqlite3
import threading
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func
from sqlalchemy import select as sa_select
from sqlalchemy.exc import OperationalError

from coach.api.app import create_app
from coach.analysis.zones import Zones, compute_zones
from coach.api.deps import hash_pin, valid_pin, verify_pin
from coach.config import db_path, load_settings, save_settings
from coach.version import app_version
from coach.garmin.port import FakeGarminClient, GarminAuthRequired, LapSummary, Metrics
from coach.llm.provider import FakeLLMProvider, LLMError, LLMUsageLimit
from coach.plan.models import Activity, AthleteSnapshot, Race
from coach.services.history import HistoryState, save_state
from tests.llm.factories import valid_plan_json
from coach.plan.repo import Repo, SchemaTooNew, make_engine
from coach.storage import switch as switch_mod
from coach.storage.cloud_errors import CloudUnreachable
from coach.storage.source import LocalSource
from tests.plan.factories import make_activity, make_cycle, make_db_session
from tests.services.test_sync import adjustment_json

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
def _history_done(_home, repo):
    """Historique déjà importé : POST /api/sync ne lance pas d'import en arrière-plan."""
    save_state(repo, HistoryState(status="done"))


@pytest.fixture
def fake_garmin():
    return FakeGarminClient(metrics=METRICS)


@pytest.fixture
def make_client(repo, fake_garmin):
    def build(*, lan=False, garmin=None, llm=None, login=None, db=None, **kw):
        def garmin_factory():
            if garmin == "auth":
                raise GarminAuthRequired("pas de jetons")
            return garmin or fake_garmin

        app = create_app(
            lan=lan,
            garmin_factory=garmin_factory,
            llm_factory=lambda: llm or FakeLLMProvider([]),
            repo=db or repo,
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
    assert (r.json()["proposal_id"], r.json()["needs_generation"]) == (None, True)
    assert (r.json()["goal"]["target_time_s"], r.json()["goal"]["target_source"]) == (6600, "user")


def test_post_goal_empty_target_time_is_claude_mode(make_client):
    r = _create_goal(make_client(), target_time="")
    assert (r.json()["goal"]["target_time_s"], r.json()["goal"]["target_source"]) == (None, "claude")


def test_post_goal_bad_target_time(make_client):
    assert _create_goal(make_client(), target_time="abc").status_code == 422


def test_status_reports_auth_required(make_client):
    r = make_client(garmin="auth").get("/api/status")
    assert r.status_code == 200
    body = r.json()
    assert body["garmin"] == "auth_required"
    assert body["cycle"] is None and body["next_goal"] is None and body["goals"] == []
    assert body["pending_proposal_id"] is None
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
    assert r.json()["goal"]["gpx_summary"] is not None


def test_generate_accept_and_plan(make_client):
    client = make_client(llm=FakeLLMProvider([valid_plan_json(14, 3)]))
    assert client.get("/api/plan").json() == {
        "cycle": None, "goals": [], "horizon": [], "open_injury": None, "weeks": []
    }
    goal = _create_goal(client).json()["goal"]
    assert client.post("/api/cycle/generate").status_code == 200
    assert client.post("/api/cycle/accept").json() == {"status": "ok"}

    plan = client.get("/api/plan").json()
    assert [g["id"] for g in plan["goals"]] == [goal["id"]] and plan["horizon"] == []
    assert plan["cycle"]["plan_accepted"] is True and plan["cycle"]["end_date"] == goal["race_date"]
    assert len(plan["weeks"]) == 14
    week1 = plan["weeks"][0]
    assert week1["week_index"] == 1 and week1["week_monday"] == "2026-11-02"
    assert [s["order"] for s in week1["sessions"]] == [1, 2, 3]
    s = week1["sessions"][0]
    assert s["status"] == "todo" and isinstance(s["steps"], list) and s["steps"][0]["kind"] == "warmup"
    assert s["suggested_day"] and s["scheduled_date"] is None and s["sync_error"] is None
    status = client.get("/api/status").json()
    assert status["next_goal"]["id"] == goal["id"] and status["next_goal"]["priority"] == "principal"
    assert [g["id"] for g in status["goals"]] == [goal["id"]] and status["cycle"]["id"] == plan["cycle"]["id"]


def _accepted_goal(client) -> dict:
    goal = _create_goal(client).json()["goal"]
    client.post("/api/cycle/generate")
    client.post("/api/cycle/accept")
    return goal


def test_patch_goal(make_client):
    client = make_client(llm=FakeLLMProvider([valid_plan_json(14, 3), adjustment_json()]))
    goal = _accepted_goal(client)
    # course avancée au samedi, même semaine : la semaine de la course garde ses 2 séances
    r = client.patch(f"/api/goals/{goal['id']}", json={"race_date": "2027-02-06", "target_time": "5:15"})
    assert r.status_code == 200
    body = r.json()
    assert body["goal"]["target_time_s"] == 18900 and body["goal"]["target_source"] == "user"
    assert body["goal"]["race_date"] == "2027-02-06"
    assert isinstance(body["proposal_id"], int) and body["needs_generation"] is False
    assert client.get("/api/proposals/pending").json()["id"] == body["proposal_id"]


def test_patch_goal_invalid(make_client):
    client = make_client(llm=FakeLLMProvider([valid_plan_json(14, 3)]))
    goal = _accepted_goal(client)
    for body in ({"race_date": "2020-01-01"}, {}, {"target_time": "abc"}, {"race_date": "pas une date"}):
        r = client.patch(f"/api/goals/{goal['id']}", json=body)
        assert r.status_code == 422 and r.json()["code"] == "invalid"


def test_export_check_returns_warnings(make_client):
    client = make_client(llm=FakeLLMProvider([valid_plan_json(14, 3)]))
    goal = _create_goal(client).json()["goal"]
    client.post("/api/cycle/generate")
    client.post("/api/cycle/accept")
    sid = client.get("/api/plan").json()["weeks"][0]["sessions"][0]["id"]
    r = client.get(f"/api/sessions/{sid}/export-check", params={"date": "2026-11-03"})
    assert r.status_code == 200 and r.json() == {"warnings": []}
    r = client.get("/api/sessions/9999/export-check", params={"date": "2026-11-03"})
    assert r.status_code == 422


def test_post_goal_available_days(make_client):
    client = make_client()
    r = _create_goal(client, available_days="mardi,jeudi,dimanche", long_run_day="dimanche")
    assert r.status_code == 200
    first_id = r.json()["goal"]["id"]
    cycle = client.get("/api/status").json()["cycle"]
    assert cycle["available_days"] == ["mardi", "jeudi", "dimanche"]
    assert cycle["long_run_day"] == "dimanche"
    client.delete(f"/api/goals/{first_id}")  # ferme le cycle : le suivant repart de zéro
    _create_goal(client)
    assert client.get("/api/status").json()["cycle"]["available_days"][0] == "lundi"  # absent : 7 jours


def test_post_goal_priority(make_client):
    client = make_client()
    assert _create_goal(client).json()["goal"]["priority"] == "principal"  # absent : principal
    assert _create_goal(client, priority="plaisir").json()["goal"]["priority"] == "plaisir"
    r = _create_goal(client, priority="inconnue")
    assert r.status_code == 422 and r.json()["code"] == "invalid"


def test_post_goal_invalid_available_day(make_client):
    r = _create_goal(make_client(), available_days="mardi,lunid,dimanche")
    assert r.status_code == 422 and r.json()["code"] == "invalid"


def test_post_goal_too_few_available_days(make_client):
    r = _create_goal(make_client(), available_days="mardi,jeudi")
    assert r.status_code == 422


def test_plan_exposes_available_days(make_client):
    client = make_client(llm=FakeLLMProvider([valid_plan_json(14, 3)]))
    goal = _create_goal(client, available_days="mardi,jeudi,dimanche").json()["goal"]
    client.post("/api/cycle/generate")
    client.post("/api/cycle/accept")
    assert client.get("/api/plan").json()["cycle"]["available_days"] == ["mardi", "jeudi", "dimanche"]


def test_patch_cycle_available_days(make_client):
    client = make_client(llm=FakeLLMProvider([valid_plan_json(14, 3), adjustment_json(), adjustment_json()]))
    _accepted_goal(client)
    r = client.patch(
        "/api/cycle",
        json={"available_days": ["mardi", "jeudi", "dimanche"], "long_run_day": "dimanche"},
    )
    assert r.status_code == 200
    assert r.json()["cycle"]["available_days"] == ["mardi", "jeudi", "dimanche"]
    assert r.json()["cycle"]["long_run_day"] == "dimanche"
    r = client.patch("/api/cycle", json={"long_run_day": ""})
    assert r.status_code == 200 and r.json()["cycle"]["long_run_day"] is None


def test_patch_goal_ignores_plan_settings(make_client):
    client = make_client(llm=FakeLLMProvider([valid_plan_json(14, 3)]))
    goal = _accepted_goal(client)
    r = client.patch(f"/api/goals/{goal['id']}", json={"include_bike": True})
    assert r.status_code == 422 and r.json()["detail"] == "Aucune modification"


def test_patch_cycle_settings_asks_adjustment(make_client):
    client = make_client(llm=FakeLLMProvider([valid_plan_json(14, 3), adjustment_json()]))
    _accepted_goal(client)
    r = client.patch("/api/cycle", json={"include_bike": True})
    assert r.status_code == 200
    body = r.json()
    assert body["cycle"]["include_bike"] is True and isinstance(body["proposal_id"], int)
    assert client.get("/api/proposals/pending").json()["id"] == body["proposal_id"]
    assert client.get("/api/status").json()["cycle"]["include_bike"] is True


def test_patch_cycle_without_plan_is_422(make_client):
    r = make_client().patch("/api/cycle", json={"include_bike": True})
    assert r.status_code == 422 and r.json()["detail"] == "Aucun plan en cours"


def test_generate_without_cycle_is_422(make_client):
    client = make_client(llm=FakeLLMProvider([valid_plan_json(14, 3)]))
    for url in ("/api/cycle/generate", "/api/cycle/accept"):
        r = client.post(url)
        assert r.status_code == 422 and r.json() == {"code": "invalid", "detail": "Aucun plan en cours"}


def test_status_after_migration(make_client, tmp_path):
    from tests.plan.test_repo import _old_db_with_plan

    path = tmp_path / "old.db"
    _old_db_with_plan(path)
    body = make_client(db=Repo(make_engine(path))).get("/api/status").json()
    assert body["cycle"]["id"] == 7 and body["cycle"]["plan_accepted"] is True
    assert body["cycle"]["sessions_per_week"] == 4 and body["cycle"]["end_date"] == "2027-01-31"
    assert body["next_goal"]["id"] == 7 and body["next_goal"]["priority"] == "principal"
    assert [g["id"] for g in body["goals"]] == [7]


def test_export_check_warns_on_unavailable_day(make_client):
    client = make_client(llm=FakeLLMProvider([valid_plan_json(14, 3)]))
    goal = _create_goal(client, available_days="mardi,jeudi,dimanche").json()["goal"]
    client.post("/api/cycle/generate")
    client.post("/api/cycle/accept")
    sid = client.get("/api/plan").json()["weeks"][0]["sessions"][0]["id"]
    r = client.get(f"/api/sessions/{sid}/export-check", params={"date": "2026-11-02"})  # lundi
    assert "Jour hors de tes disponibilités" in r.json()["warnings"]
    r = client.get(f"/api/sessions/{sid}/export-check", params={"date": "2026-11-03"})  # mardi
    assert "Jour hors de tes disponibilités" not in r.json()["warnings"]


def test_export_and_unschedule(make_client, fake_garmin):
    client = make_client(llm=FakeLLMProvider([valid_plan_json(14, 3)]))
    goal = _create_goal(client).json()["goal"]
    client.post("/api/cycle/generate")
    client.post("/api/cycle/accept")
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
    goal = _create_goal(client).json()["goal"]
    client.post("/api/cycle/generate")
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


def _db_session(repo, **kw):
    """Séance persistée (un échauffement Z2 de 10 min) sans activité."""
    cycle = repo.add(make_cycle())
    return repo.add(make_db_session(cycle.id, **kw))


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


def test_manual_match_refuses_other_sport(make_client, repo):
    from datetime import date

    run_session = _db_session(repo)
    bike_session = _db_session(repo, sport="bike")
    ride = repo.add(Activity(garmin_activity_id=41, date=date(2026, 11, 3), type_key="road_biking"))
    run = repo.add(Activity(garmin_activity_id=42, date=date(2026, 11, 3), type_key="running"))
    client = make_client()
    for act, session in ((run, bike_session), (ride, run_session)):
        r = client.post(f"/api/activities/{act.id}/match", json={"session_id": session.id})
        assert r.status_code == 422 and r.json()["code"] == "sport_mismatch"
        with repo.transaction() as db:
            assert db.get(Activity, act.id).session_id is None
        assert repo.session(session.id).status == "todo"
    ok = client.post(f"/api/activities/{ride.id}/match", json={"session_id": bike_session.id})
    assert ok.status_code == 200


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
    cycle = repo.add(make_cycle())
    first = repo.add(make_db_session(cycle.id))
    second = repo.add(make_db_session(cycle.id, order=2))
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
    assert client.get("/api/activities?week=1").json() == []  # pas de cycle
    goal = _create_goal(client).json()["goal"]
    monday = date.fromisoformat(client.get("/api/plan").json()["cycle"]["plan_start"])
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


def test_free_activities_of_bike_sport(make_client, repo):
    from datetime import date

    client = make_client()
    ride = repo.add(Activity(garmin_activity_id=31, date=date.today(), type_key="road_biking", duration_s=3600.0))
    repo.add(Activity(garmin_activity_id=32, date=date.today(), type_key="running"))
    assert [r["id"] for r in client.get("/api/activities/free?days=7&sport=bike").json()] == [ride.id]
    assert [r["type_key"] for r in client.get("/api/activities/free?days=7").json()] == ["running"]
    assert client.get("/api/activities/free?days=7&sport=swim").status_code == 422


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
    goal = _create_goal(client).json()["goal"]
    r = client.post("/api/cycle/generate")
    assert r.status_code == 429
    assert r.json()["code"] == "llm_limit"


def test_generic_llm_error_maps_to_502_on_generate(make_client):
    client = make_client(llm=BrokenLLM())
    goal = _create_goal(client).json()["goal"]
    r = client.post("/api/cycle/generate")
    assert r.status_code == 502
    assert r.json() == {
        "code": "llm_error",
        "detail": "Réponse illisible du CLI claude (code 1) : OAuth token has expired",
    }


def test_generic_llm_error_maps_to_502_on_sync(make_client, fake_garmin):
    from datetime import date

    from coach.garmin.port import ActivitySummary

    client = make_client(llm=FakeLLMProvider([valid_plan_json(14, 3)]))
    goal = _create_goal(client).json()["goal"]
    client.post("/api/cycle/generate")
    client.post("/api/cycle/accept")
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
    save_state(repo, HistoryState(status="error", imported=5, error="boum"))
    body = client.get("/api/status").json()
    assert body["has_activities"] is True
    assert body["history"] == {"status": "error", "imported": 5, "error": "boum"}


def test_status_reports_running_when_runner_running(make_client, repo):
    client = make_client()
    save_state(repo, HistoryState(status="idle"))
    client.app.state.history = FakeRunner(running=True)
    assert client.get("/api/status").json()["history"]["status"] == "running"


def test_sync_starts_history_import_once(make_client, repo):
    save_state(repo, HistoryState())  # idle
    client = make_client()
    runner = FakeRunner()
    client.app.state.history = runner
    assert client.post("/api/sync").status_code == 200
    assert runner.calls == 1
    save_state(repo, HistoryState(status="done"))
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
    return r.json()["goal"]["id"]


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
    assert client.delete(f"/api/goals/{first}").status_code == 200
    r = client.get(f"/api/goals/{first}/race-plan")
    assert r.status_code == 422


# --- imprévus ---------------------------------------------------------------------------------


# avant le début du plan : aucune séance concernée, la réponse vide de Claude respecte les contraintes
UNAVAILABLE = {"kind": "unavailable", "start_date": "2026-10-10", "end_date": "2026-10-12"}


def _event_client(make_client, *extra):
    client = make_client(llm=FakeLLMProvider([valid_plan_json(14, 3), *extra]))
    return client, _accepted_goal(client)


def test_post_event_creates_it_and_proposal(make_client):
    client, goal = _event_client(make_client, adjustment_json())
    r = client.post("/api/cycle/events", json={**UNAVAILABLE, "note": "voyage"})
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["event_id"], int) and isinstance(body["proposal_id"], int) and body["error"] is None
    assert client.get("/api/proposals/pending").json()["id"] == body["proposal_id"]
    assert client.get("/api/cycle/events").json() == [
        {
            "id": body["event_id"], "kind": "unavailable", "start_date": "2026-10-10", "end_date": "2026-10-12",
            "max_sessions": None, "days": None, "session_id": None, "note": "voyage",
        }
    ]


def test_post_event_claude_failure_keeps_event(make_client):
    client, goal = _event_client(make_client, "pas du json")
    body = client.post("/api/cycle/events", json=UNAVAILABLE).json()
    assert body["proposal_id"] is None and body["error"]
    assert len(client.get("/api/cycle/events").json()) == 1


def test_post_event_invalid_returns_422(make_client):
    client, goal = _event_client(make_client)
    url = "/api/cycle/events"
    for body in (
        {"kind": "inconnu"},
        {"kind": "unavailable", "start_date": "2026-11-10"},  # fin manquante (service)
        {"kind": "unavailable", "start_date": "2026-10-12", "end_date": "2026-10-10"},
    ):
        r = client.post(url, json=body)
        assert r.status_code == 422 and r.json()["code"] == "invalid"


def test_post_event_without_cycle_returns_422(make_client):
    r = make_client().post("/api/cycle/events", json=UNAVAILABLE)
    assert r.status_code == 422 and r.json() == {"code": "invalid", "detail": "Aucun plan en cours"}


def test_post_event_on_draft_plan_returns_422(make_client):
    client = make_client(llm=FakeLLMProvider([valid_plan_json(14, 3)]))
    _create_goal(client)
    client.post("/api/cycle/generate")
    r = client.post("/api/cycle/events", json=UNAVAILABLE)
    assert r.status_code == 422 and r.json()["detail"] == "Le plan doit être validé"


def test_get_events_without_cycle_is_empty(make_client):
    r = make_client().get("/api/cycle/events")
    assert r.status_code == 200 and r.json() == []


def test_delete_event(make_client):
    client, goal = _event_client(make_client, adjustment_json())
    event_id = client.post("/api/cycle/events", json=UNAVAILABLE).json()["event_id"]
    assert client.delete(f"/api/events/{event_id}").json() == {"status": "ok"}
    assert client.get("/api/cycle/events").json() == []


def test_delete_event_unknown_is_404(make_client):
    r = make_client().delete("/api/events/999")
    assert r.status_code == 404 and r.json()["code"] == "not_found"


def test_resume_injury_and_open_injury_in_plan(make_client):
    # un arrêt ouvert bloque tout le plan : la réponse vide est refusée (2 essais) tant qu'il n'est pas clos
    client, goal = _event_client(make_client, adjustment_json(), adjustment_json(), adjustment_json())
    injury = {"kind": "injury", "start_date": "2026-10-01", "note": "genou"}
    event_id = client.post("/api/cycle/events", json=injury).json()["event_id"]
    open_injury = client.get("/api/plan").json()["open_injury"]
    assert open_injury["id"] == event_id and open_injury["end_date"] is None and open_injury["note"] == "genou"

    r = client.post(f"/api/events/{event_id}/resume", json={"date": "2026-10-10"})
    assert r.status_code == 200 and r.json()["event_id"] == event_id and r.json()["error"] is None
    assert client.get("/api/plan").json()["open_injury"] is None
    assert client.get("/api/cycle/events").json()[0]["end_date"] == "2026-10-09"


def test_resume_invalid_returns_422(make_client):
    client, goal = _event_client(make_client, adjustment_json())
    event_id = client.post("/api/cycle/events", json=UNAVAILABLE).json()["event_id"]
    r = client.post(f"/api/events/{event_id}/resume", json={"date": "2026-11-20"})  # pas un arrêt ouvert
    assert r.status_code == 422 and r.json()["code"] == "invalid"
    r = client.post(f"/api/events/{event_id}/resume", json={"date": "pas une date"})
    assert r.status_code == 422 and r.json()["code"] == "invalid"


def test_resume_unknown_event_is_404(make_client):
    r = make_client().post("/api/events/999/resume", json={"date": "2026-11-09"})
    assert r.status_code == 404 and r.json()["code"] == "not_found"


def test_plan_open_injury_is_null_without_injury(make_client):
    client, _ = _event_client(make_client)
    assert client.get("/api/plan").json()["open_injury"] is None


def test_post_adjust(make_client):
    client, goal = _event_client(make_client, adjustment_json())
    body = client.post("/api/cycle/adjust").json()
    assert isinstance(body["proposal_id"], int)
    assert client.get("/api/proposals/pending").json()["id"] == body["proposal_id"]


def test_post_adjust_without_cycle_returns_422(make_client):
    r = make_client().post("/api/cycle/adjust")
    assert r.status_code == 422 and r.json()["code"] == "invalid"


def test_post_adjust_llm_limit_maps_to_429(make_client):
    client = make_client(llm=FakeLLMProvider([valid_plan_json(14, 3)]))
    goal = _accepted_goal(client)
    limited = make_client(llm=LimitedLLM())
    r = limited.post("/api/cycle/adjust")
    assert r.status_code == 429 and r.json()["code"] == "llm_limit"


def test_cycle_include_bike_roundtrip(make_client):
    # le premier objectif est retiré : l'estimation porte sur le second (id 2)
    client = make_client(llm=FakeLLMProvider([valid_plan_json(14, 3, goal_id=2), adjustment_json()]))
    other = make_client()
    first = _create_goal(other).json()["goal"]
    assert other.get("/api/status").json()["cycle"]["include_bike"] is False
    other.delete(f"/api/goals/{first['id']}")
    _create_goal(client, include_bike="true")
    client.post("/api/cycle/generate")
    client.post("/api/cycle/accept")
    plan = client.get("/api/plan").json()
    assert plan["cycle"]["include_bike"] is True
    assert all(s["sport"] == "run" for w in plan["weeks"] for s in w["sessions"])
    r = client.patch("/api/cycle", json={"include_bike": False})
    assert r.status_code == 200 and r.json()["cycle"]["include_bike"] is False


def test_add_and_remove_goals(make_client):
    client = make_client(llm=FakeLLMProvider([valid_plan_json(14, 3)]))
    _accepted_goal(client)
    # après le Principal : simple ajout à l'horizon, sans réglages du plan ni appel à Claude
    form = {"type": "route", "distance_km": "10", "race_date": "2027-04-11", "priority": "secondaire"}
    r = client.post("/api/goals", data=form)
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["proposal_id"], body["needs_generation"]) == (None, False)
    later = body["goal"]
    assert [g["id"] for g in client.get("/api/plan").json()["horizon"]] == [later["id"]]
    r = client.post("/api/goals", data={**form, "race_date": "2027-04-18"})
    assert r.status_code == 422 and "est à 7 jours" in r.json()["detail"]
    r = client.patch(f"/api/goals/{later['id']}", json={"priority": "plaisir"})
    assert r.status_code == 200 and r.json()["goal"]["priority"] == "plaisir"
    r = client.delete(f"/api/goals/{later['id']}")
    assert r.status_code == 200 and r.json() == {"proposal_id": None, "needs_generation": False}
    assert client.get("/api/plan").json()["horizon"] == []
    assert client.delete(f"/api/goals/{later['id']}").status_code == 422


def test_first_goal_without_sessions_per_week_is_422(make_client):
    form = {k: v for k, v in GOAL_FORM.items() if k != "sessions_per_week"}
    r = make_client().post("/api/goals", data=form)
    assert r.status_code == 422 and r.json()["detail"] == "Indique le nombre de séances par semaine"


# --- cycle suivant ------------------------------------------------------------------------------


def _finished_cycle(repo):
    """Cycle terminé au Principal du dimanche 01/11/2026 ; un objectif reste à venir."""
    from tests.plan.factories import make_goal

    repo.add(make_cycle(plan_start=date(2026, 8, 3), end_date=date(2026, 11, 1), status="done",
                        sessions_per_week=4, long_run_day="dimanche"))
    old = repo.add(make_goal(race_date=date(2026, 9, 6), status="done", priority="plaisir", distance_km=10))
    ran = repo.add(make_goal(race_date=date(2026, 11, 1), status="done"))
    repo.add(make_goal(race_date=date(2026, 8, 1), status="archived"))
    upcoming = repo.add(make_goal(race_date=date(2027, 2, 7)))
    return old, ran, upcoming


def test_status_reports_past_goals_and_cycle_to_prepare(make_client, repo):
    old, ran, upcoming = _finished_cycle(repo)
    body = make_client().get("/api/status").json()
    assert body["cycle"] is None
    assert [g["id"] for g in body["goals"]] == [upcoming.id]
    assert [g["id"] for g in body["past_goals"]] == [ran.id, old.id]
    assert body["past_goals"][0]["status"] == "done"
    assert body["last_cycle"]["sessions_per_week"] == 4 and body["last_cycle"]["long_run_day"] == "dimanche"


def test_post_next_cycle(make_client, repo):
    _, ran, upcoming = _finished_cycle(repo)
    client = make_client(llm=FakeLLMProvider([valid_plan_json(14, 4, estimated_time_s=None)]))
    assert client.post("/api/cycle/next", json={"sessions_per_week": 9}).status_code == 422
    r = client.post("/api/cycle/next", json={"include_bike": True, "sessions_per_week": 5})
    assert r.status_code == 200
    cycle = r.json()
    assert (cycle["plan_start"], cycle["end_date"]) == ("2026-11-02", "2027-02-07")
    assert cycle["sessions_per_week"] == 5 and cycle["include_bike"] is True and cycle["needs_generation"] is True
    status = client.get("/api/status").json()
    assert status["cycle"]["id"] == cycle["id"]
    # déjà un cycle en cours
    r = client.post("/api/cycle/next")
    assert r.status_code == 422 and r.json()["detail"] == "Un cycle est déjà en cours"


def test_post_next_cycle_without_body_or_goal(make_client, repo):
    client = make_client()
    r = client.post("/api/cycle/next")
    assert r.status_code == 422 and r.json()["detail"] == "Aucun objectif à venir"
    _finished_cycle(repo)
    assert client.post("/api/cycle/next").status_code == 200


# --- verrou Garmin entre PC ---------------------------------------------------------------------


def _lock_elsewhere(repo):
    from datetime import datetime, timedelta, timezone

    from coach.plan.models import GarminLock
    from coach.storage.lock import try_acquire

    with repo.transaction() as db:  # un verrou d'écriture de ce PC encore actif est écrasé
        lock = db.get(GarminLock, 1)
        if lock is not None:
            db.delete(lock)
    assert try_acquire(repo, "autre-pc", timedelta(minutes=15), datetime.now(timezone.utc))


def _assert_locked(r):
    from coach.storage.lock import LOCK_MSG

    assert r.status_code == 409
    assert r.json() == {"code": "garmin_locked", "detail": LOCK_MSG}


def test_business_export_with_lock_held_leaves_sync_error(make_client, repo):
    import json as _json

    from coach.plan.models import Proposal
    from coach.storage.lock import LOCK_MSG

    client = make_client(llm=FakeLLMProvider([valid_plan_json(14, 3)]))
    _accepted_goal(client)
    sid = client.get("/api/plan").json()["weeks"][0]["sessions"][0]["id"]
    assert client.post(f"/api/sessions/{sid}/export", json={"date": "2026-11-05"}).status_code == 200
    with repo.transaction() as db:
        p = Proposal(analysis="x", changes_json=_json.dumps([{"op": "remove", "session_id": sid, "reason": "r"}]))
        db.add(p)
        db.flush()
        pid = p.id
    _lock_elsewhere(repo)
    r = client.post(f"/api/proposals/{pid}/accept")
    assert r.status_code == 200 and r.json() == {"sync_error_ids": [sid]}
    s = repo.session(sid)
    assert s.status == "sync_error" and LOCK_MSG in s.sync_error and s.pending_removal


def test_sync_endpoint_409_when_locked(make_client, repo):
    client = make_client()
    _lock_elsewhere(repo)
    _assert_locked(client.post("/api/sync"))


def test_history_import_409_when_locked(make_client, repo):
    client = make_client()
    client.app.state.history = FakeRunner(result=True)
    _lock_elsewhere(repo)
    _assert_locked(client.post("/api/history/import"))
    assert client.app.state.history.calls == 0


def test_manual_export_409_when_locked(make_client, repo, fake_garmin):
    client = make_client(llm=FakeLLMProvider([valid_plan_json(14, 3)]))
    _accepted_goal(client)
    sid = client.get("/api/plan").json()["weeks"][0]["sessions"][0]["id"]
    _lock_elsewhere(repo)
    _assert_locked(client.post(f"/api/sessions/{sid}/export", json={"date": "2026-11-05"}))
    assert fake_garmin.calls == [] and repo.session(sid).status == "todo"


def test_sync_takes_and_releases_lock(make_client, repo):
    from datetime import datetime, timezone

    from coach.storage.lock import held_elsewhere

    seen = []

    class Spy(FakeGarminClient):
        def activities(self, start, end):
            seen.append(held_elsewhere(repo, "autre-pc", datetime.now(timezone.utc)))
            return super().activities(start, end)

    assert make_client(garmin=Spy(metrics=METRICS)).post("/api/sync").status_code == 200
    assert seen == [True]
    assert not held_elsewhere(repo, "autre-pc", datetime.now(timezone.utc))


# --- stockage cloud ---------------------------------------------------------------------------

STORAGE_TOKEN = "jeton-secret-turso"
LOCAL_PEER = ("127.0.0.1", 50000)
TURSO_SETTINGS = {"storage_mode": "turso", "turso_url": "libsql://base.turso.io", "turso_token": STORAGE_TOKEN}


class FakeCloud:
    """« Base cloud » de test : un second fichier SQLite ; `fail` simule une erreur à l'ouverture."""

    def __init__(self, path):
        self.path = path
        self.fail: Exception | None = None
        self.opened: list[tuple[str, str]] = []

    def source_for(self, settings):
        if settings.storage_mode != "turso":
            return LocalSource(db_path())
        cloud = self

        class _Source:
            kind = "turso"

            def engine(self):
                cloud.opened.append((settings.turso_url, settings.turso_token))
                if cloud.fail is not None:
                    raise cloud.fail
                return make_engine(cloud.path)

        return _Source()


def _activity_count(engine) -> int:
    with engine.connect() as c:
        return c.execute(sa_select(func.count()).select_from(Activity.__table__)).scalar()


def _seed_local(home: Path, n: int = 2) -> None:
    engine = make_engine(home / "coach.db")
    with Repo(engine).transaction() as db:
        cycle = make_cycle(status="active")
        db.add(cycle)
        db.flush()
        db.add(make_db_session(cycle.id, title="Séance locale"))
        for i in range(n):
            db.add(make_activity(garmin_activity_id=500 + i))
    engine.dispose()
    (home / "gpx").mkdir(exist_ok=True)
    (home / "gpx" / "1.gpx").write_text("<gpx/>")
    (home / "history.json").write_text('{"status": "done"}')


@pytest.fixture
def cloud(tmp_path):
    path = tmp_path / "cloud-db" / "cloud.db"
    path.parent.mkdir()
    return FakeCloud(path)


@pytest.fixture
def storage_client(_home, cloud, fake_garmin):
    _seed_local(_home)
    now = [0.0]

    def build(peer=LOCAL_PEER):
        app = create_app(
            lan=False,
            garmin_factory=lambda: fake_garmin,
            llm_factory=lambda: FakeLLMProvider([]),
            login_client=FakeLogin(False),
            extra_hosts={"testserver"},
            source_for=cloud.source_for,
            clock=lambda: now[0],
        )
        client = TestClient(app, client=peer, headers={"X-Coach": "1"})
        client.now = now
        return client

    return build


def _enable(client, replace_local=False):
    body = {"url": "libsql://base.turso.io", "token": STORAGE_TOKEN, "replace_local": replace_local}
    return client.post("/api/storage/cloud", json=body)


def _session_titles(client) -> list[str]:
    return [s["title"] for w in client.get("/api/plan").json()["weeks"] for s in w["sessions"]]


def _start_in_cloud_mode(cloud, fail: Exception) -> None:
    save_settings(load_settings().model_copy(update=TURSO_SETTINGS))
    cloud.fail = fail


def test_storage_default_is_local(storage_client):
    r = storage_client().get("/api/storage")
    assert r.status_code == 200
    assert r.json() == {"mode": "local", "turso_url": None, "has_turso_token": False}


def test_enable_on_empty_cloud_copies_and_deletes_local(storage_client, _home, cloud):
    client = storage_client()
    before = client.get("/api/plan").json()
    assert before["weeks"]
    r = _enable(client)
    assert r.status_code == 200, r.text
    assert r.json() == {"mode": "turso", "turso_url": "libsql://base.turso.io", "has_turso_token": True}
    assert not (_home / "coach.db").exists()
    assert not (_home / "gpx").exists() and not (_home / "history.json").exists()
    assert client.get("/api/storage").json()["mode"] == "turso"
    assert client.get("/api/plan").json() == before
    s = load_settings()
    assert (s.storage_mode, s.turso_url, s.turso_token) == ("turso", "libsql://base.turso.io", STORAGE_TOKEN)
    assert _activity_count(make_engine(cloud.path)) == 2


def test_enable_on_nonempty_cloud_needs_confirmation_then_adopts(storage_client, _home, cloud):
    other = _home / "autre-pc"
    other.mkdir()
    _seed_local(other, n=5)
    remote = make_engine(cloud.path)
    switch_mod.enable_cloud(make_engine(other / "coach.db"), switch_mod.OpenedSource("turso", remote), replace_local=False)
    client = storage_client()
    r = _enable(client)
    assert r.status_code == 409
    assert r.json() == {
        "code": "needs_confirmation",
        "detail": "Les données de ce PC seront remplacées par celles du cloud",
    }
    assert load_settings().storage_mode == "local" and (_home / "coach.db").exists()
    r = _enable(client, replace_local=True)
    assert r.status_code == 200
    assert not (_home / "coach.db").exists()
    assert _activity_count(remote) == 5  # rien de ce PC n'a été écrit dans le cloud
    assert len(client.get("/api/stats/activities").json()["activities"]) == 5


def test_enable_with_bad_token_changes_nothing(storage_client, _home, cloud):
    cloud.fail = CloudUnreachable("Jeton Turso refusé : vérifie-le")
    client = storage_client()
    r = _enable(client)
    assert r.status_code == 422
    assert r.json() == {"code": "cloud_unreachable", "detail": "Jeton Turso refusé : vérifie-le"}
    s = load_settings()
    assert (s.storage_mode, s.turso_url, s.turso_token) == ("local", None, None)
    assert (_home / "coach.db").exists() and (_home / "history.json").exists()
    assert _session_titles(client) == ["Séance locale"]


def test_enable_copy_failure_keeps_local(storage_client, _home, monkeypatch):
    def boom(src, dst):
        raise switch_mod.CopyMismatch("activity")

    monkeypatch.setattr(switch_mod, "verify_copy", boom)
    client = storage_client()
    r = _enable(client)
    assert r.status_code == 422
    assert r.json() == {
        "code": "cloud_copy_failed",
        "detail": "Le transfert vers le cloud a échoué : tes données locales sont intactes.",
    }
    assert load_settings().storage_mode == "local"
    assert (_home / "coach.db").exists() and (_home / "gpx" / "1.gpx").exists()
    assert _session_titles(client) == ["Séance locale"]


def test_schema_too_new_on_enable(storage_client, _home, cloud):
    cloud.fail = SchemaTooNew("schéma 2 > 1")
    client = storage_client()
    r = _enable(client)
    assert r.status_code == 409
    assert r.json() == {"code": "schema_too_new", "detail": "Mets à jour CoachCloclo sur ce PC"}
    assert load_settings().storage_mode == "local" and (_home / "coach.db").exists()


def test_enable_refused_while_history_import_runs(storage_client):
    client = storage_client()
    client.app.state.history = FakeRunner(running=True)
    r = _enable(client)
    assert r.status_code == 409 and r.json()["code"] == "history_running"
    assert load_settings().storage_mode == "local"


def test_enable_recreates_history_runner_on_new_repo(storage_client):
    client = storage_client()
    old = client.app.state.history
    assert _enable(client).status_code == 200
    assert client.app.state.history is not old
    assert client.app.state.history._repo is client.app.state.repo


def test_disable_copies_back_and_keeps_cloud(storage_client, _home, cloud):
    client = storage_client()
    assert _enable(client).status_code == 200
    remote = make_engine(cloud.path)
    with Repo(remote).transaction() as db:
        db.add(make_activity(garmin_activity_id=999))  # ajoutée depuis un autre PC
    r = client.delete("/api/storage/cloud")
    assert r.status_code == 200
    assert r.json() == {"mode": "local", "turso_url": None, "has_turso_token": False}
    s = load_settings()
    assert (s.storage_mode, s.turso_url, s.turso_token) == ("local", None, None)
    assert (_home / "coach.db").exists()
    assert _activity_count(client.app.state.repo.engine) == 3
    assert _activity_count(remote) == 3  # la désactivation n'efface jamais la base cloud
    assert _session_titles(client) == ["Séance locale"]


def test_wipe_cloud(storage_client, _home, cloud):
    client = storage_client()
    r = client.post("/api/storage/cloud/wipe")
    assert r.status_code == 409 and r.json()["code"] == "not_cloud"
    assert _enable(client).status_code == 200
    r = client.post("/api/storage/cloud/wipe")
    assert r.status_code == 200
    assert r.json()["mode"] == "local"
    remote = make_engine(cloud.path)
    assert _activity_count(remote) == 0 and switch_mod.is_empty(remote)
    assert _session_titles(client) == ["Séance locale"]  # ce PC garde ses données, en local


def test_cloud_unreachable_returns_503(storage_client):
    client = storage_client()
    assert _enable(client).status_code == 200

    @event.listens_for(client.app.state.repo.engine, "before_cursor_execute")
    def coupure(*args):
        raise sqlite3.OperationalError("unable to open database file")

    r = client.get("/api/plan")
    assert r.status_code == 503
    assert r.json() == {"code": "cloud_unreachable", "detail": "Base cloud injoignable : vérifie ta connexion"}


def test_libsql_network_error_returns_503(storage_client):
    client = storage_client()
    assert _enable(client).status_code == 200

    @event.listens_for(client.app.state.repo.engine, "before_cursor_execute")
    def coupure(*args):
        raise ValueError("Hrana: `http error: `error trying to connect: dns error``")

    assert client.get("/api/plan").status_code == 503


def test_local_mode_db_error_is_not_cloud_unreachable(storage_client):
    client = storage_client()

    @event.listens_for(client.app.state.repo.engine, "before_cursor_execute")
    def coupure(*args):
        raise sqlite3.OperationalError("disk I/O error")

    with pytest.raises(OperationalError):
        client.get("/api/plan")


def test_startup_with_unreachable_cloud_then_recovers(storage_client, cloud):
    _start_in_cloud_mode(cloud, CloudUnreachable("Base cloud injoignable"))
    client = storage_client()  # ne plante pas
    assert client.get("/api/storage").json()["mode"] == "turso"
    status = client.get("/api/status")
    assert status.status_code == 200
    assert status.json()["storage"]["code"] == "cloud_unreachable"
    r = client.get("/api/plan")
    assert r.status_code == 503 and r.json()["code"] == "cloud_unreachable"
    cloud.fail = None
    client.now[0] += 60  # nouvel essai après le délai
    assert client.get("/api/plan").status_code == 200
    assert client.get("/api/status").json()["storage"] is None


def test_startup_retry_is_throttled(storage_client, cloud):
    _start_in_cloud_mode(cloud, CloudUnreachable("Base cloud injoignable"))
    client = storage_client()
    tries = len(cloud.opened)
    client.get("/api/plan")
    client.get("/api/plan")
    assert len(cloud.opened) == tries  # pas de nouvel essai réseau à chaque requête


def test_startup_with_schema_too_new_cloud(storage_client, cloud):
    _start_in_cloud_mode(cloud, SchemaTooNew("schéma 2 > 1"))
    r = storage_client().get("/api/plan")
    assert r.status_code == 409
    assert r.json() == {"code": "schema_too_new", "detail": "Mets à jour CoachCloclo sur ce PC"}


def test_resaving_settings_recovers_unavailable_cloud(storage_client, _home, cloud):
    _start_in_cloud_mode(cloud, CloudUnreachable("Jeton Turso refusé : vérifie-le"))
    client = storage_client()
    cloud.fail = None
    assert _enable(client).status_code == 200
    assert load_settings().turso_token == STORAGE_TOKEN
    assert client.get("/api/plan").status_code == 200
    assert (_home / "coach.db").exists()  # pas de suppression : ce PC n'était pas en mode local


def test_storage_routes_loopback_only(storage_client):
    client = storage_client(peer=("192.168.1.20", 50000))
    for method, path in [
        ("get", "/api/storage"),
        ("post", "/api/storage/cloud"),
        ("delete", "/api/storage/cloud"),
        ("post", "/api/storage/cloud/wipe"),
    ]:
        kw = {"json": {"url": "u", "token": "t"}} if (method, path) == ("post", "/api/storage/cloud") else {}
        r = getattr(client, method)(path, **kw)
        assert r.status_code == 403 and r.json()["code"] == "local_only", (method, path)
    assert load_settings().storage_mode == "local"


def test_storage_view_never_returns_token(storage_client):
    client = storage_client()
    for r in (_enable(client), client.get("/api/storage"), client.get("/api/status")):
        assert r.status_code == 200
        assert STORAGE_TOKEN not in r.text


def test_cloud_mode_refuses_another_url(storage_client, cloud):
    client = storage_client()
    assert _enable(client).status_code == 200
    body = {"url": "libsql://autre-base.turso.io", "token": "autre", "replace_local": True}
    r = client.post("/api/storage/cloud", json=body)
    assert r.status_code == 409
    assert r.json() == {"code": "cloud_url_change", "detail": "Reviens d'abord au stockage local pour changer de base cloud."}
    s = load_settings()
    assert (s.turso_url, s.turso_token) == ("libsql://base.turso.io", STORAGE_TOKEN)


def test_cloud_mode_accepts_same_host_new_token(storage_client, cloud):
    client = storage_client()
    assert _enable(client).status_code == 200
    r = client.post("/api/storage/cloud", json={"url": "https://BASE.turso.io/", "token": "nouveau"})
    assert r.status_code == 200
    assert load_settings().turso_token == "nouveau"
    assert _session_titles(client) == ["Séance locale"]


@pytest.mark.parametrize("body", [{"url": "   ", "token": "t"}, {"url": "libsql://base.turso.io", "token": "  "}])
def test_enable_blank_fields_rejected(storage_client, body):
    client = storage_client()
    r = client.post("/api/storage/cloud", json=body)
    assert r.status_code == 422
    assert load_settings().storage_mode == "local"


def test_switch_recovers_orphan_import(storage_client, _home):
    client = storage_client()
    save_state(client.app.state.repo, HistoryState(status="running"))  # import interrompu, sans thread
    assert _enable(client).status_code == 200
    from coach.services.history import load_state

    assert load_state(client.app.state.repo).status == "error"
