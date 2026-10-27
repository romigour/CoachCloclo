"""Application FastAPI : routes JSON sous /api, protection par PIN en mode LAN."""

import json
import secrets
import time
from collections.abc import Callable
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlmodel import select

from coach.analysis.gpx import GpxError
from coach.api.deps import get_garmin, get_llm, verify_pin
from coach.config import Settings, db_path, load_settings, save_settings, tokenstore_dir
from coach.garmin.client import GarminClient
from coach.garmin.port import (
    GarminAuthRequired,
    GarminPort,
    GarminRateLimited,
    GarminUnavailable,
)
from coach.llm.provider import (
    LLMInvalidResponse,
    LLMProvider,
    LLMTimeout,
    LLMUnavailable,
    LLMUsageLimit,
)
from coach.plan import calendar
from coach.plan.models import Activity, Goal, Proposal, Session
from coach.plan.repo import Repo, make_engine
from coach.services import CoachError
from coach.services import garmin_export as export
from coach.services.plans import GoalInput, accept_plan, create_goal, generate_plan
from coach.services.sync import sync

MFA_TTL_S = 600
PIN_MAX_FAILURES = 5
PIN_LOCK_S = 60
COOKIE = "coach_session"
WEB_DIST = Path(__file__).resolve().parent.parent / "web_dist"


class LoginBody(BaseModel):
    email: str
    password: str


class MfaBody(BaseModel):
    login_id: str
    code: str


class PinBody(BaseModel):
    pin: str


class DateBody(BaseModel):
    date: date


class MatchBody(BaseModel):
    session_id: int | None = None


class SettingsBody(BaseModel):
    llm_mode: Literal["cli", "api"]
    anthropic_api_key: str | None = None
    anthropic_model: str | None = None


def _error(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"code": code, "detail": detail})


def _goal_dict(goal: Goal) -> dict:
    return {
        "id": goal.id,
        "type": goal.type,
        "distance_km": goal.distance_km,
        "d_plus_m": goal.d_plus_m,
        "race_date": goal.race_date.isoformat(),
        "sessions_per_week": goal.sessions_per_week,
        "plan_start": goal.plan_start.isoformat(),
        "plan_accepted": goal.plan_accepted,
        "gpx_summary": json.loads(goal.gpx_summary_json) if goal.gpx_summary_json else None,
    }


def _session_dict(s: Session) -> dict:
    return {
        "id": s.id,
        "order": s.order,
        "type": s.type,
        "title": s.title,
        "description": s.description,
        "target_kind": s.target_kind,
        "status": s.status,
        "suggested_day": s.suggested_day,
        "scheduled_date": s.scheduled_date.isoformat() if s.scheduled_date else None,
        "chaining_note": s.chaining_note,
        "steps": json.loads(s.steps_json),
        "sync_error": s.sync_error,
    }


def _register_errors(app: FastAPI) -> None:
    def add(exc_type, status: int, code: str, message: str | None = None) -> None:
        async def handler(request: Request, exc: Exception) -> JSONResponse:
            return _error(status, code, message or str(exc))

        app.add_exception_handler(exc_type, handler)

    add(GarminAuthRequired, 401, "garmin_auth", "Connexion Garmin requise")
    add(GarminRateLimited, 429, "garmin_rate_limited", "Garmin limite les requêtes, réessaie plus tard")
    add(GarminUnavailable, 502, "garmin_unavailable")
    add(LLMUsageLimit, 429, "llm_limit", "Limite d'usage de Claude atteinte")
    add(LLMUnavailable, 503, "llm_unavailable")
    add(LLMTimeout, 502, "llm_timeout", "Claude a mis trop de temps à répondre")
    add(LLMInvalidResponse, 502, "llm_invalid", "Claude a renvoyé une réponse invalide")
    add(CoachError, 422, "invalid")  # inclut GoalError et ExportError
    add(GpxError, 422, "invalid_gpx")


def create_app(
    *,
    lan: bool,
    garmin_factory: Callable[[], GarminPort],
    llm_factory: Callable[[], LLMProvider],
    repo: Repo | None = None,
    login_client=GarminClient,
    clock: Callable[[], float] = time.monotonic,
) -> FastAPI:
    """`login_client` (start_login/finish_login) et `clock` sont injectables pour les tests."""
    if lan and not load_settings().pin_hash:
        raise ValueError("Le mode LAN exige un PIN : définis-en un avec `coach set-pin`")

    app = FastAPI(title="Coach")
    app.state.garmin_factory = garmin_factory
    app.state.llm_factory = llm_factory
    app.state.repo = repo or Repo(make_engine(db_path()))
    app.state.mfa = {}  # login_id -> (état MFA, expiration) ; jamais renvoyé au client
    app.state.sessions = set()
    app.state.pin_failures = 0
    app.state.pin_locked_until = 0.0
    _register_errors(app)

    def get_repo(request: Request) -> Repo:
        return request.app.state.repo

    RepoDep = Annotated[Repo, Depends(get_repo)]
    GarminDep = Annotated[GarminPort, Depends(get_garmin)]
    LLMDep = Annotated[LLMProvider, Depends(get_llm)]

    if lan:

        @app.middleware("http")
        async def require_pin(request: Request, call_next):
            path = request.url.path
            if path.startswith("/api") and path != "/api/auth/pin":
                if request.cookies.get(COOKIE) not in request.app.state.sessions:
                    return _error(401, "pin_required", "PIN requis")
            return await call_next(request)

    api = APIRouter(prefix="/api")

    # --- statut et authentification ---------------------------------------------------------

    @api.get("/status")
    def status(repo: RepoDep):
        try:
            app.state.garmin_factory()
            garmin = "ok"
        except GarminAuthRequired:
            garmin = "auth_required"
        goal = repo.active_goal()
        proposal = repo.pending_proposal()
        return {
            "garmin": garmin,
            "llm_mode": load_settings().llm_mode,
            "pending_proposal_id": proposal.id if proposal else None,
            "goal": _goal_dict(goal) if goal else None,
        }

    @api.post("/auth/pin")
    def auth_pin(body: PinBody):
        stored = load_settings().pin_hash
        if not stored:
            return _error(422, "no_pin", "Aucun PIN défini")
        if clock() < app.state.pin_locked_until:
            return _error(429, "pin_locked", "Trop d'essais, réessaie dans une minute")
        if not verify_pin(body.pin, stored):
            app.state.pin_failures += 1
            if app.state.pin_failures >= PIN_MAX_FAILURES:
                app.state.pin_failures = 0
                app.state.pin_locked_until = clock() + PIN_LOCK_S
            return _error(401, "pin_invalid", "PIN incorrect")
        app.state.pin_failures = 0
        token = secrets.token_urlsafe(32)
        app.state.sessions.add(token)
        response = JSONResponse({"status": "ok"})
        response.set_cookie(COOKIE, token, httponly=True, samesite="strict")
        return response

    @api.post("/garmin/login")
    def garmin_login(body: LoginBody):
        status_, state = login_client.start_login(body.email, body.password, tokenstore_dir())
        if status_ == "ok":
            return {"status": "ok"}
        now = clock()
        pending = app.state.mfa
        for k in [k for k, (_, exp) in pending.items() if exp <= now]:
            del pending[k]
        login_id = secrets.token_urlsafe(16)
        pending[login_id] = (state, now + MFA_TTL_S)
        return {"status": "needs_mfa", "login_id": login_id}

    @api.post("/garmin/mfa")
    def garmin_mfa(body: MfaBody):
        entry = app.state.mfa.get(body.login_id)
        if entry is None or entry[1] <= clock():
            app.state.mfa.pop(body.login_id, None)
            return _error(422, "mfa_expired", "Connexion expirée, recommence")
        login_client.finish_login(entry[0], body.code, tokenstore_dir())
        del app.state.mfa[body.login_id]
        return {"status": "ok"}

    # --- objectifs et plan ------------------------------------------------------------------

    @api.post("/goals")
    def post_goal(
        repo: RepoDep,
        garmin: GarminDep,
        type: Annotated[Literal["route", "trail"], Form()],
        distance_km: Annotated[float, Form()],
        race_date: Annotated[date, Form()],
        sessions_per_week: Annotated[int, Form()],
        d_plus_m: Annotated[int, Form()] = 0,
        gpx: Annotated[UploadFile | None, File()] = None,
    ):
        data = GoalInput(
            type=type,
            distance_km=distance_km,
            d_plus_m=d_plus_m,
            race_date=race_date,
            sessions_per_week=sessions_per_week,
            gpx=gpx.file.read() if gpx is not None else None,
        )
        return _goal_dict(create_goal(repo, garmin, data))

    @api.post("/goals/{goal_id}/generate")
    def post_generate(goal_id: int, repo: RepoDep, garmin: GarminDep, llm: LLMDep):
        plan = generate_plan(repo, garmin, llm, goal_id)
        return {"summary": plan.summary, "weeks": len(plan.weeks)}

    @api.post("/goals/{goal_id}/accept")
    def post_accept(goal_id: int, repo: RepoDep):
        accept_plan(repo, goal_id)
        return {"status": "ok"}

    @api.get("/plan")
    def get_plan(repo: RepoDep):
        goal = repo.active_goal()
        if goal is None:
            return {"goal": None, "weeks": []}
        weeks: dict[int, list[dict]] = {}
        for s in repo.sessions(goal.id):
            weeks.setdefault(s.week_index, []).append(_session_dict(s))
        return {
            "goal": _goal_dict(goal),
            "weeks": [
                {
                    "week_index": idx,
                    "week_monday": calendar.week_monday(goal, idx).isoformat(),
                    "sessions": sessions,
                }
                for idx, sessions in sorted(weeks.items())
            ],
        }

    # --- export Garmin ----------------------------------------------------------------------

    @api.get("/sessions/{session_id}/export-check")
    def export_check(session_id: int, date: date, repo: RepoDep):
        return {"warnings": export.check_export(repo, session_id, date)}

    @api.post("/sessions/{session_id}/export")
    def post_export(session_id: int, body: DateBody, repo: RepoDep, garmin: GarminDep):
        return {"warnings": export.export_session(repo, garmin, session_id, body.date)}

    @api.post("/sessions/{session_id}/move")
    def post_move(session_id: int, body: DateBody, repo: RepoDep, garmin: GarminDep):
        return {"warnings": export.move_session(repo, garmin, session_id, body.date)}

    @api.post("/sessions/{session_id}/unschedule")
    def post_unschedule(session_id: int, repo: RepoDep, garmin: GarminDep):
        export.unschedule_session(repo, garmin, session_id)
        return {"status": "ok"}

    @api.post("/sessions/{session_id}/retry")
    def post_retry(session_id: int, repo: RepoDep, garmin: GarminDep):
        export.retry_sync_error(repo, garmin, session_id)
        return {"status": "ok"}

    # --- activités, synchro, propositions ---------------------------------------------------

    @api.post("/activities/{activity_id}/match")
    def post_match(activity_id: int, body: MatchBody, repo: RepoDep):
        """Correction manuelle du rattachement ; `session_id` nul détache l'activité."""
        with repo.transaction() as db:
            activity = db.get(Activity, activity_id)
            if activity is None:
                return _error(404, "not_found", "Activité introuvable")
            new = None
            if body.session_id is not None:
                new = db.get(Session, body.session_id)
                if new is None:
                    return _error(404, "not_found", "Séance introuvable")
                # une séance n'a qu'une activité : on libère l'éventuelle précédente
                others = db.exec(
                    select(Activity).where(Activity.session_id == new.id, Activity.id != activity.id)
                ).all()
                for o in others:
                    o.session_id = None
                    db.add(o)
            old_id = activity.session_id
            activity.session_id = body.session_id
            activity.match_source = "manual"
            db.add(activity)
            db.flush()
            if new is not None and new.status != "sync_error":
                new.status = "done"
                db.add(new)
            if old_id is not None and old_id != body.session_id:
                old = db.get(Session, old_id)
                still = db.exec(select(Activity).where(Activity.session_id == old_id)).first()
                if old is not None and old.status == "done" and still is None:
                    old.status = "exported" if old.garmin_schedule_id else "todo"
                    db.add(old)
        return {"status": "ok"}

    @api.post("/sync")
    def post_sync(repo: RepoDep, garmin: GarminDep, llm: LLMDep):
        return sync(repo, garmin, llm, now=datetime.now(timezone.utc))

    @api.get("/proposals/pending")
    def get_pending(repo: RepoDep):
        p: Proposal | None = repo.pending_proposal()
        if p is None:
            return None
        return {
            "id": p.id,
            "created_at": p.created_at.isoformat(),
            "analysis": p.analysis,
            "changes": json.loads(p.changes_json),
        }

    @api.post("/proposals/{proposal_id}/accept")
    def post_proposal_accept(proposal_id: int, repo: RepoDep, garmin: GarminDep):
        return {"sync_error_ids": export.apply_proposal(repo, garmin, proposal_id)}

    @api.post("/proposals/{proposal_id}/reject")
    def post_proposal_reject(proposal_id: int, repo: RepoDep):
        export.reject_proposal(repo, proposal_id)
        return {"status": "ok"}

    # --- réglages ---------------------------------------------------------------------------

    def _settings_view(s: Settings) -> dict:
        return {
            "llm_mode": s.llm_mode,
            "anthropic_model": s.anthropic_model,
            "has_api_key": bool(s.anthropic_api_key),
        }

    @api.get("/settings")
    def get_settings():
        return _settings_view(load_settings())

    @api.put("/settings")
    def put_settings(body: SettingsBody):
        s = load_settings()
        s.llm_mode = body.llm_mode
        if body.anthropic_api_key is not None:
            s.anthropic_api_key = body.anthropic_api_key or None
        if body.anthropic_model:
            s.anthropic_model = body.anthropic_model
        save_settings(s)
        return _settings_view(s)

    app.include_router(api)
    if WEB_DIST.is_dir():
        app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
    return app
