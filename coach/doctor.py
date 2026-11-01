"""Diagnostic de l'installation : `coach doctor`."""

import importlib.util
import shutil
import socket
import subprocess
import sys
from pathlib import Path

from pydantic import BaseModel

from coach.config import data_dir, load_settings, tokenstore_dir
from coach.garmin.client import GarminClient
from coach.garmin.port import GarminAuthRequired, GarminRateLimited, GarminUnavailable
from coach.llm.provider import LLMError, LLMUnavailable, LLMUsageLimit, provider_from_settings
from coach.proc import NO_WINDOW, find_claude

DEFAULT_PORT = 8765
OFFLINE_DETAIL = "non vérifié (hors ligne)"
_AUTH_SYSTEM = "Tu es un test de connexion."
_AUTH_PROMPT = 'Réponds uniquement {"ok":true}'
LOGIN_MESSAGE = "Connecte-toi dans Claude puis tape /exit pour revenir"

_INSTALL_WINDOWS = ["powershell", "-NoProfile", "-Command", "irm https://claude.ai/install.ps1 | iex"]
_INSTALL_POSIX = ["bash", "-c", "curl -fsSL https://claude.ai/install.sh | bash"]


class Check(BaseModel):
    name: str
    ok: bool
    detail: str
    fix_hint: str | None = None
    fixable: bool = False


def _default_garmin():
    return GarminClient.from_tokens(tokenstore_dir())


def _default_llm():
    return provider_from_settings(load_settings())


def _check_python() -> Check:
    v = sys.version_info
    ok = v >= (3, 12)
    return Check(name="python", ok=ok, detail=f"Python {v.major}.{v.minor}.{v.micro}",
                 fix_hint=None if ok else "Installe Python 3.12 ou plus récent")


def _check_garminconnect() -> Check:
    ok = importlib.util.find_spec("garminconnect") is not None
    return Check(name="garminconnect", ok=ok,
                 detail="installé" if ok else "module absent",
                 fix_hint=None if ok else "Réinstalle CoachCloclo avec le script d'installation (voir README)")


def _check_claude_cli(which) -> Check:
    path = find_claude(which)
    if path:
        return Check(name="claude_cli", ok=True, detail=f"trouvé : {path}")
    return Check(name="claude_cli", ok=False, detail="CLI claude introuvable",
                 fix_hint="Lance `coach doctor --fix` pour installer Claude Code", fixable=True)


def _check_claude_auth(llm_factory, *, cli_ok: bool, cli_mode: bool) -> Check:
    """`cli_mode` : connexion via le CLI claude (corrigible par `--fix`), sinon clé API."""
    login_hint = "Lance `coach doctor --fix` (ou `claude`) puis connecte-toi"
    if cli_mode and not cli_ok:  # corrigé dans la même passe, après l'installation du CLI
        return Check(name="claude_auth", ok=False, detail="CLI absent",
                     fix_hint=login_hint, fixable=True)
    try:
        out = llm_factory().complete(_AUTH_SYSTEM, _AUTH_PROMPT)
    except LLMUsageLimit:
        return Check(name="claude_auth", ok=False, detail="limite d'usage atteinte",
                     fix_hint="Attends le renouvellement de ta limite, puis relance")
    except LLMUnavailable as e:
        return Check(name="claude_auth", ok=False, detail=f"non connecté ({e})",
                     fix_hint=login_hint if cli_mode else "Vérifie ta clé API dans les réglages",
                     fixable=cli_mode)
    except LLMError as e:  # ex. jeton OAuth du CLI expiré : une reconnexion règle le problème
        return Check(name="claude_auth", ok=False, detail=f"erreur Claude : {e}",
                     fix_hint=login_hint if cli_mode else None, fixable=cli_mode)
    if "ok" in out:
        return Check(name="claude_auth", ok=True, detail="connecté")
    return Check(name="claude_auth", ok=False, detail=f"réponse inattendue : {out[:80]}")


def _check_garmin_tokens(garmin_factory) -> Check:
    relogin = "Lance `coach login-garmin`"
    try:
        garmin = garmin_factory()
        garmin.today()
        garmin.metrics()
    except GarminAuthRequired:
        return Check(name="garmin_tokens", ok=False, detail="connexion Garmin absente ou expirée",
                     fix_hint=relogin, fixable=True)
    except GarminRateLimited:
        return Check(name="garmin_tokens", ok=False, detail="Garmin limite les requêtes (429)",
                     fix_hint="Réessaie dans quelques minutes")
    except GarminUnavailable as e:
        return Check(name="garmin_tokens", ok=False, detail=f"Garmin indisponible : {e}",
                     fix_hint="Réessaie plus tard")
    return Check(name="garmin_tokens", ok=True, detail="connecté à Garmin")


def _check_data_dir() -> Check:
    try:
        path = data_dir()
        probe = path / ".coach-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as e:
        return Check(name="data_dir", ok=False, detail=f"dossier de données inutilisable : {e}",
                     fix_hint="Lance `coach doctor --fix` pour le créer", fixable=True)
    return Check(name="data_dir", ok=True, detail=str(path))


def _check_port(port: int) -> Check:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return Check(name="port", ok=False, detail=f"port {port} occupé",
                         fix_hint=f"Ferme l'autre programme ou lance `coach start --port {port + 1}`")
    return Check(name="port", ok=True, detail=f"port {port} libre")


def run_checks(*, live: bool = True, offline: bool = False, which=shutil.which,
               runner=subprocess.run, garmin_factory=_default_garmin,
               llm_factory=_default_llm, port: int = DEFAULT_PORT) -> list[Check]:
    """Vérifications dans l'ordre. `offline` saute claude_cli, claude_auth et garmin_tokens ;
    `live=False` ne fait pas les appels réels de claude_auth et garmin_tokens."""
    def skipped(name: str, detail: str) -> Check:
        return Check(name=name, ok=True, detail=detail)

    checks = [_check_python(), _check_garminconnect()]
    cli = skipped("claude_cli", OFFLINE_DETAIL) if offline else _check_claude_cli(which)
    checks.append(cli)
    if offline:
        checks.append(skipped("claude_auth", OFFLINE_DETAIL))
        checks.append(skipped("garmin_tokens", OFFLINE_DETAIL))
    else:
        no_live = "appel réel non effectué"
        cli_mode = load_settings().llm_mode == "cli"
        checks.append(_check_claude_auth(llm_factory, cli_ok=cli.ok, cli_mode=cli_mode) if live
                      else skipped("claude_auth", no_live))
        checks.append(_check_garmin_tokens(garmin_factory) if live
                      else skipped("garmin_tokens", no_live))
    checks.append(_check_data_dir())
    checks.append(_check_port(port))
    return checks


def fix(check: Check, *, runner=subprocess.run, data_path: Path | None = None,
        echo=print, which=shutil.which) -> bool:
    """Tente de corriger une vérification en échec ; renvoie True si c'est réglé.

    `claude_auth` lance `claude` en interactif dans le terminal courant (stdin hérité) ;
    l'appelant revérifie ensuite la connexion."""
    if not check.fixable:
        return False
    if check.name == "data_dir":
        try:
            (data_path or data_dir()).mkdir(parents=True, exist_ok=True)
        except OSError:
            return False
        return True
    if check.name == "claude_cli":
        cmd = _INSTALL_WINDOWS if sys.platform == "win32" else _INSTALL_POSIX
        echo("Installation de Claude Code : " + " ".join(cmd[-1:] if len(cmd) > 2 else cmd))
        try:
            return runner(cmd, creationflags=NO_WINDOW).returncode == 0
        except OSError:
            return False
    if check.name == "claude_auth":
        exe = find_claude(which)
        if exe is None:
            echo("CLI claude introuvable : installe-le d'abord")
            return False
        echo(LOGIN_MESSAGE)
        try:
            return runner([exe]).returncode == 0
        except OSError:
            return False
    if check.name == "garmin_tokens":
        from coach.cli import login_garmin_flow  # import tardif : cli importe doctor

        try:
            login_garmin_flow()
        except Exception:  # noqa: BLE001 - l'échec est déjà affiché par le flux
            return False
        return True
    return False
