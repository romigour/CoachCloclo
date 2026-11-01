"""Endpoints de la version bureau : configuration de Claude, mise à jour, mode LAN."""

import threading

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from coach.api.deps import hash_pin, is_loopback, valid_pin
from coach.config import load_settings, save_settings
from coach.desktop.context import Desktop
from coach.desktop.updater import UpdateBusy, UpdateError

LAN_DELAY_S = 0.5


class LanBody(BaseModel):
    enabled: bool
    pin: str | None = None


def _error(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"code": code, "detail": detail})


def _local_only() -> JSONResponse:
    return _error(403, "local_only", "Action possible seulement depuis l'ordinateur où tourne CoachCloclo")


def desktop_router(desktop: Desktop) -> APIRouter:
    api = APIRouter(prefix="/api")

    def lan_view(request: Request) -> dict:
        return {
            "enabled": request.app.state.lan,
            "has_pin": bool(load_settings().pin_hash),
            "addresses": desktop.lan_addresses(),
            "local": is_loopback(request),
        }

    @api.get("/setup/status")
    def setup_status(request: Request):
        return {
            **desktop.claude.status(),
            "garmin": request.app.state.garmin_state(),
            "llm_mode": load_settings().llm_mode,
        }

    @api.post("/setup/claude/install")
    def setup_claude_install(request: Request):
        if not is_loopback(request):
            return _local_only()
        desktop.claude.start_install()
        return {"status": "started"}

    @api.post("/setup/claude/login")
    def setup_claude_login(request: Request):
        if not is_loopback(request):
            return _local_only()
        desktop.claude.start_login()
        return {"status": "started"}

    @api.get("/update")
    def update_view():
        return desktop.updater.view()

    @api.post("/update/check")
    def update_check(request: Request):
        if not is_loopback(request):
            return _local_only()
        try:
            desktop.updater.check()
        except UpdateError as e:
            return _error(502, "update_check_failed", str(e))
        return desktop.updater.view()

    @api.post("/update/install")
    def update_install(request: Request):
        if not is_loopback(request):
            return _local_only()
        try:
            desktop.updater.start_install(desktop.request_exit)
        except UpdateBusy as e:
            return _error(409, "update_running", str(e))
        except UpdateError as e:
            return _error(409, "no_update", str(e))
        return JSONResponse(status_code=202, content={"status": "started"})

    @api.get("/lan")
    def lan_get(request: Request):
        return lan_view(request)

    @api.post("/lan")
    async def lan_post(request: Request):
        if not is_loopback(request):
            return _local_only()
        try:
            body = LanBody.model_validate(await request.json())
        except (ValueError, ValidationError):
            return _error(422, "invalid_body", "Requête invalide")
        settings = load_settings()
        if body.pin is not None and not valid_pin(body.pin):
            return _error(422, "invalid_pin", "Le PIN doit contenir 4 à 12 chiffres")
        if body.enabled and body.pin is None and not settings.pin_hash:
            return _error(422, "pin_required_to_enable", "Définis un PIN pour activer l'accès depuis le réseau local")
        update = {"lan_enabled": body.enabled}
        if body.pin is not None:
            update["pin_hash"] = hash_pin(body.pin)
        save_settings(settings.model_copy(update=update))
        request.app.state.lan = body.enabled
        if not body.enabled or body.pin is not None:
            # nouveau PIN : les téléphones déjà connectés doivent le saisir
            request.app.state.sessions.clear()
        if body.pin is not None:
            request.app.state.pin_failures = 0
            request.app.state.pin_locked_until = 0.0
        # le serveur est relancé : la réponse doit partir avant
        timer = threading.Timer(LAN_DELAY_S, desktop.set_lan, args=(body.enabled,))
        timer.daemon = True
        timer.start()
        return lan_view(request)

    return api
