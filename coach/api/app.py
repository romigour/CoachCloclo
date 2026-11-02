"""Application FastAPI : routes JSON sous /api, protection par PIN en mode LAN."""

import ipaddress
import json
import secrets
import socket
import threading
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from typing import Annotated, Literal

from fastapi.exceptions import RequestValidationError
from fastapi import APIRouter, Depends, FastAPI, File, Form, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError, model_validator
from sqlmodel import select

from coach.analysis.compliance import activity_types_for
from coach.analysis.gpx import GpxError
from coach.api.desktop_routes import desktop_router
from coach.api.deps import get_garmin, get_llm, is_loopback, verify_pin
from coach.config import Settings, db_path, load_settings, save_settings, tokenstore_dir
from coach.desktop.context import Desktop
from coach.garmin.client import GarminClient
from coach.garmin.port import (
    GarminAuthRequired,
    GarminPort,
    GarminRateLimited,
    GarminUnavailable,
)
from coach.llm.provider import (
    LLMError,
    LLMInvalidResponse,
    LLMProvider,
    LLMTimeout,
    LLMUnavailable,
    LLMUsageLimit,
)
from coach.plan import calendar
from coach.plan.models import Activity, Event, Goal, Proposal, Session
from coach.plan.repo import Repo, make_engine
from coach.services import CoachError
from coach.services import garmin_export as export
from coach.services.plans import (
    GoalInput,
    GoalUpdate,
    accept_plan,
    create_goal,
    generate_plan,
    parse_target_time,
    update_goal,
)
from coach.analysis.race_plan import RaceSettings
from coach.services import race_strategy
from coach.services.adjust import request_adjustment
from coach.services.events import EventInput, EventResult, create_event, delete_event, resume_injury
from coach.services.history import HistoryRunner, load_state, recover_orphan
from coach.services.laps import fetch_laps, latest_zones, session_comparison
from coach.services.sync import sync
from coach.stats.normalize import stat_row
from coach.version import app_version

MFA_TTL_S = 600
PIN_MAX_FAILURES = 5
PIN_LOCK_S = 60
COOKIE = "coach_session"
MAX_GPX_BYTES = 10 * 1024 * 1024
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]"}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
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


class RaceBody(BaseModel):
    name: str | None = Field(None, max_length=120)
    official_time_s: int | None = Field(None, gt=0)
    overall_rank: int | None = Field(None, ge=1)
    overall_total: int | None = Field(None, ge=1)
    category: str | None = Field(None, max_length=40)
    category_rank: int | None = Field(None, ge=1)
    category_total: int | None = Field(None, ge=1)

    @model_validator(mode="after")
    def _rank_within_total(self):
        for rank, total in (
            (self.overall_rank, self.overall_total),
            (self.category_rank, self.category_total),
        ):
            if rank is not None and total is not None and rank > total:
                raise ValueError("Le classement dépasse le nombre de participants")
        return self


def _activity_row(a: Activity) -> dict:
    return {
        "id": a.id,
        "date": a.date.isoformat(),
        "type_key": a.type_key,
        "duration_s": a.duration_s,
        "distance_m": a.distance_m,
        "d_plus_m": a.d_plus_m,
        "avg_hr": a.avg_hr,
        "session_id": a.session_id,
        "match_source": a.match_source,
    }


def _error(status: int, code: str, detail) -> JSONResponse:
    return JSONResponse(status_code=status, content={"code": code, "detail": detail})


def _invalid(errors: list[dict], prefix: tuple = ()) -> JSONResponse:
    # jamais d'écho de `input` : il peut contenir clé API ou mot de passe
    # pydantic préfixe les ValueError des validateurs par « Value error, »
    return _error(422, "invalid", [
        {"loc": [*prefix, *e["loc"]], "msg": e["msg"].removeprefix("Value error, ")} for e in errors
    ])


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
        "target_time_s": goal.target_time_s,
        "target_source": goal.target_source,
        "available_days": goal.available_days(),
        "long_run_day": goal.long_run_day,
        "include_bike": goal.include_bike,
        "gpx_summary": json.loads(goal.gpx_summary_json) if goal.gpx_summary_json else None,
    }


def _event_dict(e: Event) -> dict:
    return {
        "id": e.id,
        "kind": e.kind,
        "start_date": e.start_date.isoformat(),
        "end_date": e.end_date.isoformat() if e.end_date else None,
        "max_sessions": e.max_sessions,
        "days": e.days(),
        "session_id": e.session_id,
        "note": e.note,
    }


def _session_dict(s: Session) -> dict:
    return {
        "id": s.id,
        "order": s.order,
        "type": s.type,
        "sport": s.sport,
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
    add(LLMError, 502, "llm_error")  # après les sous-classes (la plus précise l'emporte)
    add(CoachError, 422, "invalid")  # inclut GoalError et ExportError
    add(GpxError, 422, "invalid_gpx")

    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _invalid(exc.errors())

    app.add_exception_handler(RequestValidationError, validation_handler)


def _host_name(host_header: str) -> str:
    """Nom d'hôte sans port ('[::1]:80' -> '[::1]')."""
    host = host_header.strip().lower()
    if host.startswith("["):
        return host[: host.find("]") + 1]
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


def _host_allowed(host_header: str, lan: bool, extra: set[str]) -> bool:
    name = _host_name(host_header)
    if name in LOCAL_HOSTS or name in extra:
        return True
    if not lan:
        return False
    try:
        ipaddress.ip_address(name.strip("[]"))
        return True
    except ValueError:
        pass
    machine = socket.gethostname().lower()
    return name in {machine, machine + ".local"}


def garmin_state(factory: Callable[[], GarminPort]) -> str:
    """« ok », « auth_required » ou « unavailable » selon ce que renvoie la fabrique Garmin."""
    try:
        factory()
    except GarminAuthRequired:
        return "auth_required"
    except (GarminUnavailable, GarminRateLimited):
        return "unavailable"
    return "ok"


def create_app(
    *,
    lan: bool,
    garmin_factory: Callable[[], GarminPort],
    llm_factory: Callable[[], LLMProvider],
    repo: Repo | None = None,
    login_client=GarminClient,
    clock: Callable[[], float] = time.monotonic,
    extra_hosts: set[str] | frozenset[str] = frozenset(),
    desktop: Desktop | None = None,
) -> FastAPI:
    """`login_client` (start_login/finish_login) et `clock` sont injectables pour les tests."""
    if lan and not load_settings().pin_hash:
        raise ValueError("Le mode LAN exige un PIN : lance `coach start --lan` pour en définir un")

    app = FastAPI(title="CoachCloclo")
    app.state.garmin_factory = garmin_factory
    app.state.llm_factory = llm_factory
    app.state.repo = repo or Repo(make_engine(db_path()))
    app.state.mfa = {}  # login_id -> (état MFA, expiration) ; jamais renvoyé au client
    app.state.lan = lan
    app.state.sessions = set()
    app.state.pin_failures = 0
    app.state.pin_locked_until = 0.0
    pin_lock = threading.Lock()
    recover_orphan()  # un import resté « en cours » a été interrompu par l'arrêt précédent
    app.state.history = HistoryRunner(app.state.repo, garmin_factory)
    _register_errors(app)

    def get_repo(request: Request) -> Repo:
        return request.app.state.repo

    RepoDep = Annotated[Repo, Depends(get_repo)]
    GarminDep = Annotated[GarminPort, Depends(get_garmin)]
    LLMDep = Annotated[LLMProvider, Depends(get_llm)]

    @app.middleware("http")
    async def require_pin(request: Request, call_next):
        # le mode LAN se lit à chaque requête : il peut être basculé à chaud
        path = request.url.path
        if (
            request.app.state.lan
            and not is_loopback(request)
            and path.startswith("/api")
            and path not in ("/api/auth/pin", "/api/version")
        ):
            if request.cookies.get(COOKIE) not in request.app.state.sessions:
                return _error(401, "pin_required", "PIN requis")
        return await call_next(request)

    @app.middleware("http")
    async def csrf_guard(request: Request, call_next):
        h = request.headers
        if request.url.path.startswith("/api") and request.method not in SAFE_METHODS:
            origin = h.get("origin")
            fetch_site = h.get("sec-fetch-site")
            if (
                h.get("x-coach") != "1"
                or (origin is not None and urlparse(origin).netloc != h.get("host", ""))
                or (fetch_site is not None and fetch_site not in ("same-origin", "none"))
            ):
                return _error(403, "csrf", "Requête refusée")
        return await call_next(request)

    @app.middleware("http")
    async def host_guard(request: Request, call_next):
        if not _host_allowed(request.headers.get("host", ""), request.app.state.lan, set(extra_hosts)):
            return JSONResponse(status_code=400, content={"code": "bad_host", "detail": "Hôte refusé"})
        return await call_next(request)

    api = APIRouter(prefix="/api")

    # --- statut et authentification ---------------------------------------------------------

    @api.get("/status")
    def status(repo: RepoDep):
        garmin = garmin_state(app.state.garmin_factory)
        goal = repo.active_goal()
        proposal = repo.pending_proposal()
        history = load_state()
        # le thread peut ne pas avoir encore écrit son état : le runner fait foi
        history_status = "running" if app.state.history.running else history.status
        return {
            "garmin": garmin,
            "llm_mode": load_settings().llm_mode,
            "pending_proposal_id": proposal.id if proposal else None,
            "goal": _goal_dict(goal) if goal else None,
            "has_activities": repo.has_activities(),
            "history": {
                "status": history_status,
                "imported": history.imported,
                "error": history.error,
            },
        }

    @api.get("/version")
    def version():
        return {"version": app_version()}

    @api.post("/auth/pin")
    def auth_pin(body: PinBody):
        stored = load_settings().pin_hash
        if not stored:
            return _error(422, "no_pin", "Aucun PIN défini")
        with pin_lock:  # verrou + vérification + compteur : pas de course entre tentatives
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

    def _login_refused() -> JSONResponse:
        return _error(401, "garmin_login_failed", "Identifiants Garmin refusés")

    @api.post("/garmin/login")
    def garmin_login(body: LoginBody):
        try:
            status_, state = login_client.start_login(body.email, body.password, tokenstore_dir())
        except GarminAuthRequired:
            return _login_refused()
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
        try:
            login_client.finish_login(entry[0], body.code, tokenstore_dir())
        except GarminAuthRequired:
            return _login_refused()
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
        target_time: Annotated[str | None, Form()] = None,
        available_days: Annotated[str | None, Form()] = None,
        long_run_day: Annotated[str | None, Form()] = None,
        include_bike: Annotated[bool, Form()] = False,
        gpx: Annotated[UploadFile | None, File()] = None,
    ):
        target_time_s = parse_target_time(target_time) if target_time else None
        raw = gpx.file.read(MAX_GPX_BYTES + 1) if gpx is not None else None
        if raw is not None and len(raw) > MAX_GPX_BYTES:
            return _error(413, "too_large", "Fichier GPX trop volumineux (10 Mo maximum)")
        days = {}  # absent : GoalInput garde ses 7 jours par défaut
        if available_days:
            days["available_days"] = [d.strip() for d in available_days.split(",") if d.strip()]
        try:
            data = GoalInput(
                **days,
                long_run_day=long_run_day or None,
                include_bike=include_bike,
                type=type,
                distance_km=distance_km,
                d_plus_m=d_plus_m,
                race_date=race_date,
                sessions_per_week=sessions_per_week,
                gpx=raw,
                target_time_s=target_time_s,
            )
        except ValidationError as e:
            return _invalid(e.errors(), ("body",))
        return _goal_dict(create_goal(repo, garmin, data))

    @api.patch("/goals/{goal_id}")
    def patch_goal(goal_id: int, body: GoalUpdate, repo: RepoDep, garmin: GarminDep, llm: LLMDep):
        goal, proposal_id = update_goal(repo, garmin, llm, goal_id, body)
        return {"goal": _goal_dict(goal), "proposal_id": proposal_id}

    @api.post("/goals/{goal_id}/generate")
    def post_generate(goal_id: int, repo: RepoDep, garmin: GarminDep, llm: LLMDep):
        plan = generate_plan(repo, garmin, llm, goal_id)
        return {"summary": plan.summary, "weeks": len(plan.weeks)}

    @api.post("/goals/{goal_id}/accept")
    def post_accept(goal_id: int, repo: RepoDep):
        accept_plan(repo, goal_id)
        return {"status": "ok"}

    @api.get("/goals/{goal_id}/race-plan")
    def get_race_plan(goal_id: int, repo: RepoDep, garmin: GarminDep):
        return race_strategy.get_race_view(repo, garmin, goal_id).model_dump(mode="json")

    @api.put("/goals/{goal_id}/race-plan")
    def put_race_plan(goal_id: int, body: RaceSettings, repo: RepoDep, garmin: GarminDep):
        return race_strategy.save_settings(repo, garmin, goal_id, body).model_dump(mode="json")

    @api.post("/goals/{goal_id}/race-plan/refresh")
    def post_race_plan_refresh(goal_id: int, repo: RepoDep, garmin: GarminDep):
        return race_strategy.refresh_basis(repo, garmin, goal_id).model_dump(mode="json")

    @api.post("/goals/{goal_id}/race-plan/reimport")
    def post_race_plan_reimport(goal_id: int, repo: RepoDep, garmin: GarminDep):
        return race_strategy.reimport_stations(repo, garmin, goal_id).model_dump(mode="json")

    @api.post("/goals/{goal_id}/race-plan/export")
    def post_race_plan_export(goal_id: int, repo: RepoDep, garmin: GarminDep):
        return race_strategy.export_race(repo, garmin, goal_id).model_dump(mode="json")

    @api.get("/plan")
    def get_plan(repo: RepoDep):
        goal = repo.active_goal()
        if goal is None:
            return {"goal": None, "weeks": []}
        weeks: dict[int, list[dict]] = {}
        for s in repo.sessions(goal.id):
            weeks.setdefault(s.week_index, []).append(_session_dict(s))
        injury = repo.open_injury(goal.id)
        return {
            "goal": _goal_dict(goal),
            "open_injury": _event_dict(injury) if injury else None,
            "weeks": [
                {
                    "week_index": idx,
                    "week_monday": calendar.week_monday(goal, idx).isoformat(),
                    "sessions": sessions,
                }
                for idx, sessions in sorted(weeks.items())
            ],
        }

    # --- imprévus ---------------------------------------------------------------------------

    def _exists(repo: Repo, model, id: int) -> bool:
        with repo.transaction() as db:
            return db.get(model, id) is not None

    @api.post("/goals/{goal_id}/events")
    def post_event(goal_id: int, body: EventInput, repo: RepoDep, garmin: GarminDep, llm: LLMDep) -> EventResult:
        return create_event(repo, garmin, llm, goal_id, body)

    @api.get("/goals/{goal_id}/events")
    def get_events(goal_id: int, repo: RepoDep):
        if not _exists(repo, Goal, goal_id):
            return _error(404, "not_found", "Objectif introuvable")
        return [_event_dict(e) for e in repo.events(goal_id)]

    @api.delete("/events/{event_id}")
    def delete_event_route(event_id: int, repo: RepoDep):
        if not _exists(repo, Event, event_id):
            return _error(404, "not_found", "Imprévu introuvable")
        delete_event(repo, event_id)
        return {"status": "ok"}

    @api.post("/events/{event_id}/resume")
    def post_resume(event_id: int, body: DateBody, repo: RepoDep, garmin: GarminDep, llm: LLMDep) -> EventResult:
        if not _exists(repo, Event, event_id):
            return _error(404, "not_found", "Imprévu introuvable")
        return resume_injury(repo, garmin, llm, event_id, body.date)

    @api.post("/goals/{goal_id}/adjust")
    def post_adjust(goal_id: int, repo: RepoDep, garmin: GarminDep, llm: LLMDep):
        return {"proposal_id": request_adjustment(repo, garmin, llm, goal_id)}

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

    @api.get("/sessions/{session_id}/comparison")
    def get_comparison(session_id: int, repo: RepoDep):
        """Prévu / réalisé étape par étape, ou la raison pour laquelle la comparaison est impossible."""
        try:
            session = repo.session(session_id)
        except KeyError:
            return _error(404, "not_found", "Séance introuvable")
        result = session_comparison(repo, session, latest_zones(repo))
        if isinstance(result, str):
            return {"available": False, "reason": result}
        return {"available": True, **result.model_dump(exclude={"laps": {"__all__": {"raw"}}})}

    @api.get("/zones")
    def get_zones(repo: RepoDep):
        """Zones d'allure et de FC du dernier instantané, `null` s'il n'y en a pas encore."""
        zones = latest_zones(repo)
        return zones.model_dump() if zones else None

    # --- activités, synchro, propositions ---------------------------------------------------

    @api.get("/activities")
    def get_activities(week: int, repo: RepoDep):
        """Activités de l'objectif actif dans la semaine `week` du plan (lundi..dimanche)."""
        goal = repo.active_goal()
        if goal is None:
            return []
        monday = calendar.week_monday(goal, week)
        sunday = monday + timedelta(days=6)
        return [_activity_row(a) for a in repo.activities_since(monday) if a.date <= sunday]

    @api.get("/activities/free")
    def get_free_activities(
        days: Annotated[int, Query(ge=1, le=90)], repo: RepoDep, sport: Literal["run", "bike"] = "run"
    ):
        """Activités du `sport` (course par défaut) des `days` derniers jours, rattachées à aucune séance."""
        since = date.today() - timedelta(days=days)
        types = activity_types_for(sport)
        free = [a for a in repo.activities_since(since) if a.session_id is None and a.type_key in types]
        return [_activity_row(a) for a in reversed(free)]

    @api.post("/activities/{activity_id}/match")
    def post_match(activity_id: int, body: MatchBody, request: Request, repo: RepoDep):
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
                if activity.type_key not in activity_types_for(new.sport):
                    return _error(422, "sport_mismatch", "Cette activité ne correspond pas au sport de la séance")
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
        if body.session_id is not None and repo.laps(activity_id) is None:
            # lecture des tours hors transaction ; un Garmin déconnecté ne doit pas faire échouer le rattachement
            try:
                garmin = request.app.state.garmin_factory()
            except GarminAuthRequired:
                pass
            else:
                fetch_laps(repo, garmin, repo.activity(activity_id))
        return {"status": "ok"}

    @api.post("/sync")
    def post_sync(repo: RepoDep, garmin: GarminDep, llm: LLMDep):
        result = sync(repo, garmin, llm, now=datetime.now(timezone.utc))
        if load_state().status == "idle":  # premier lancement : import de l'historique complet
            app.state.history.start()
        return result

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

    # --- statistiques -----------------------------------------------------------------------

    @api.get("/stats/activities")
    def get_stats_activities(repo: RepoDep):
        races = {r.activity_id: r for r in repo.races()}
        rows = [stat_row(a, races.get(a.id)) for a in repo.all_activities()]
        rows.sort(key=lambda r: (r["date"], r["id"]))
        return {"activities": rows}

    @api.get("/stats/records")
    def get_stats_records(repo: RepoDep):
        return {
            "records": [
                {
                    "kind": r.kind,
                    "value": r.value,
                    "garmin_activity_id": r.garmin_activity_id,
                    "date": r.date.isoformat() if r.date else None,
                }
                for r in repo.records()
            ]
        }

    def _race_row(repo: Repo, activity_id: int) -> dict:
        race = next((r for r in repo.races() if r.activity_id == activity_id), None)
        return stat_row(repo.activity(activity_id), race)

    @api.put("/races/{activity_id}")
    def put_race(activity_id: int, body: RaceBody, repo: RepoDep):
        try:
            repo.activity(activity_id)
        except KeyError:
            return _error(404, "not_found", "Activité introuvable")
        repo.upsert_race(activity_id, body.model_dump())
        return _race_row(repo, activity_id)

    @api.delete("/races/{activity_id}")
    def delete_race(activity_id: int, repo: RepoDep):
        try:
            repo.activity(activity_id)
        except KeyError:
            return _error(404, "not_found", "Activité introuvable")
        repo.exclude_race(activity_id)
        return {"status": "ok"}

    @api.post("/history/import")
    def post_history_import():
        if not app.state.history.start():
            return _error(409, "history_running", "Un import est déjà en cours")
        return {"status": "started"}

    app.include_router(api)
    if desktop is not None:
        app.state.garmin_state = lambda: garmin_state(app.state.garmin_factory)
        app.include_router(desktop_router(desktop))
    if WEB_DIST.is_dir():
        app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
    return app
