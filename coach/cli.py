"""Commandes `coach` : start, doctor, login-garmin, update."""

import getpass
import json
import shutil
import subprocess
import sys
import threading
import urllib.request
import webbrowser

import typer
import uvicorn

from coach.api.app import create_app
from coach.api.deps import hash_pin
from coach.config import load_settings, save_settings, tokenstore_dir
from coach.doctor import DEFAULT_PORT, fix, run_checks
from coach.garmin.client import GarminClient
from coach.garmin.port import GarminAuthRequired, GarminRateLimited, GarminUnavailable
from coach.llm.provider import provider_from_settings

app = typer.Typer(help="CoachCloclo : plans running/trail à partir de tes données Garmin.",
                  no_args_is_help=True, add_completion=False)


@app.callback()
def _main() -> None:
    """Force l'UTF-8 en sortie (consoles Windows cp1252, CI) pour les ✓/✗/→."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _ask_pin() -> str:
    while True:
        pin = typer.prompt("PIN pour le mode LAN (4 à 12 chiffres)", hide_input=True,
                           confirmation_prompt=True)
        if pin.isdigit() and 4 <= len(pin) <= 12:
            return pin
        typer.echo("Le PIN doit contenir de 4 à 12 chiffres.")


@app.command()
def start(lan: bool = typer.Option(False, "--lan", help="Écoute sur le réseau local (PIN requis)"),
          port: int = typer.Option(DEFAULT_PORT, "--port"),
          no_browser: bool = typer.Option(False, "--no-browser", help="N'ouvre pas le navigateur")):
    """Lance l'application web locale."""
    if lan and not load_settings().pin_hash:
        settings = load_settings()
        settings.pin_hash = hash_pin(_ask_pin())
        save_settings(settings)
        typer.echo("PIN enregistré.")
    web = create_app(
        lan=lan,
        garmin_factory=lambda: GarminClient.from_tokens(tokenstore_dir()),
        llm_factory=lambda: provider_from_settings(load_settings()),
    )
    if not no_browser:
        threading.Timer(1.0, webbrowser.open, args=(f"http://127.0.0.1:{port}",)).start()
    uvicorn.run(web, host="0.0.0.0" if lan else "127.0.0.1", port=port)


@app.command()
def doctor(fix_issues: bool = typer.Option(False, "--fix", help="Tente de corriger les problèmes"),
           offline: bool = typer.Option(False, "--offline", help="Ne teste ni Claude ni Garmin")):
    """Vérifie l'installation."""
    def show(checks):
        for c in checks:
            typer.echo(f"{'✓' if c.ok else '✗'} {c.name} : {c.detail}")
            if not c.ok and c.fix_hint:
                typer.echo(f"    → {c.fix_hint}")

    checks = run_checks(live=not offline, offline=offline)
    show(checks)
    failed = [c for c in checks if not c.ok]
    if failed and fix_issues:
        for c in failed:
            if c.fixable:
                typer.echo(f"Correction de {c.name}…")
                typer.echo("  corrigé" if fix(c, echo=typer.echo) else "  échec de la correction")
        typer.echo("\nNouvelle vérification :")
        checks = run_checks(live=not offline, offline=offline)
        show(checks)
        failed = [c for c in checks if not c.ok]
    if failed:
        raise typer.Exit(1)


def login_garmin_flow() -> None:
    """Connexion Garmin interactive (email, mot de passe masqué, MFA éventuel)."""
    email = typer.prompt("Email Garmin")
    password = getpass.getpass("Mot de passe Garmin : ")
    store = tokenstore_dir()
    try:
        status, result = GarminClient.start_login(email, password, store)
        if status == "needs_mfa":
            code = typer.prompt("Code MFA reçu par email ou SMS")
            GarminClient.finish_login(result, code, store)
    except GarminAuthRequired as e:
        typer.echo(f"Connexion refusée : {e}")
        raise typer.Exit(1) from e
    except (GarminRateLimited, GarminUnavailable) as e:
        typer.echo(f"Garmin ne répond pas correctement : {e}")
        raise typer.Exit(1) from e
    typer.echo("Connecté à Garmin.")


@app.command("login-garmin")
def login_garmin():
    """Connecte CoachCloclo à ton compte Garmin."""
    login_garmin_flow()


REPO = "romigour/CoachCloclo"
RELEASES_API = f"https://api.github.com/repos/{REPO}/releases/latest"


def latest_wheel_url() -> str:
    """URL de la wheel de la dernière release GitHub (le front y est déjà compilé)."""
    with urllib.request.urlopen(RELEASES_API, timeout=30) as resp:
        release = json.load(resp)
    for asset in release.get("assets", []):
        if asset.get("name", "").endswith(".whl"):
            return asset["browser_download_url"]
    raise RuntimeError(f"Aucune wheel dans la dernière release de {REPO}")


@app.command()
def update():
    """Met à jour CoachCloclo depuis la dernière release GitHub."""
    uv = shutil.which("uv")
    if uv is None:
        typer.echo("uv est introuvable. Installe-le (https://docs.astral.sh/uv/) "
                   "puis relance le script d'installation.")
        raise typer.Exit(1)
    try:
        url = latest_wheel_url()
    except (OSError, RuntimeError, ValueError) as e:
        typer.echo(f"Impossible de trouver la dernière version : {e}")
        raise typer.Exit(1) from e
    result = subprocess.run([uv, "tool", "install", "--force", "--python", "3.12", url])
    if result.returncode != 0:
        raise typer.Exit(result.returncode)
