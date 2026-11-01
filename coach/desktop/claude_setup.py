"""Installation et connexion du CLI Claude, sans fenêtre console."""

from __future__ import annotations

import json
import logging
import subprocess
import threading
import time

from coach.proc import NO_WINDOW, find_claude

# Vérifié le 2026-11-01 avec Claude Code 2.1.285 : `claude auth login --claudeai` sans console ni stdin ouvre le navigateur et se termine (code 0) une fois connecté.
LOGIN_NEEDS_CONSOLE = False

INSTALL_CMD = ["powershell", "-NoProfile", "-Command", "irm https://claude.ai/install.ps1 | iex"]
LOGIN_TIMEOUT_S = 300
STATUS_TIMEOUT_S = 15
INSTALL_TIMEOUT_S = 600  # l'installeur natif télécharge ~100 Mo

logger = logging.getLogger(__name__)


class ClaudeSetup:
    """Installe le CLI Claude et suit la connexion à l'abonnement."""

    def __init__(
        self,
        runner=subprocess.run,
        popen=subprocess.Popen,
        find=find_claude,
        needs_console: bool = LOGIN_NEEDS_CONSOLE,
        clock=time.monotonic,
        login_timeout_s: int = LOGIN_TIMEOUT_S,
    ):
        self._runner = runner
        self._popen = popen
        self._find = find
        self._needs_console = needs_console
        self._clock = clock
        self._login_timeout_s = login_timeout_s
        self._lock = threading.Lock()
        self._step = "idle"
        self._error: str | None = None
        self._proc = None
        self._login_started = 0.0
        self._thread: threading.Thread | None = None

    def _set(self, step: str, error: str | None = None) -> None:
        self._step = step
        self._error = error

    def _logged_in(self, exe: str) -> bool:
        try:
            res = self._runner(
                [exe, "auth", "status", "--json"],
                creationflags=NO_WINDOW,
                capture_output=True,
                text=True,
                timeout=STATUS_TIMEOUT_S,
            )
            return json.loads(res.stdout).get("loggedIn") is True
        except Exception:
            return False

    def status(self) -> dict:
        exe = self._find()
        with self._lock:
            observed_step, observed_proc = self._step, self._proc
        auth = self._logged_in(exe) if exe else False
        with self._lock:
            # Le résultat n'est appliqué que si l'étape n'a pas changé pendant l'appel.
            if (
                observed_step == "logging_in"
                and self._step == "logging_in"
                and self._proc is observed_proc
            ):
                if auth:
                    self._proc = None
                    self._set("idle")
                elif self._proc is not None and self._proc.poll() not in (None, 0):
                    self._proc = None
                    self._set("failed", "La connexion à Claude a échoué, réessaie")
                elif self._clock() - self._login_started > self._login_timeout_s:
                    try:
                        self._proc.kill()
                    except Exception:
                        pass
                    self._proc = None
                    self._set("failed", "La connexion à Claude a expiré, réessaie")
            return {
                "claude_cli": exe is not None,
                "claude_auth": auth,
                "claude_step": self._step,
                "claude_error": self._error,
            }

    def start_install(self) -> None:
        with self._lock:
            if self._step in ("installing", "logging_in"):
                return
            self._set("installing")
            self._thread = threading.Thread(target=self._install, daemon=True)
            self._thread.start()

    def _install(self) -> None:
        try:
            res = self._runner(
                INSTALL_CMD,
                creationflags=NO_WINDOW,
                capture_output=True,
                stdin=subprocess.DEVNULL,
                timeout=INSTALL_TIMEOUT_S,
            )
            ok = res.returncode == 0
            error = None if ok else "L'installation de Claude a échoué, réessaie"
        except Exception:
            logger.exception("Installation de Claude impossible")
            ok = False
            error = "L'installation de Claude a échoué ou pris trop de temps, réessaie"
        with self._lock:
            if self._step == "installing":
                self._set("idle") if ok else self._set("failed", error)

    def start_login(self) -> None:
        with self._lock:
            if self._step in ("logging_in", "installing"):
                return
            exe = self._find()
            if not exe:
                self._set("failed", "Claude n'est pas installé")
                return
            args = [exe, "auth", "login", "--claudeai"]
            try:
                if self._needs_console:
                    proc = self._popen(
                        args, creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
                    )
                else:
                    proc = self._popen(
                        args,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=NO_WINDOW,
                    )
            except OSError as exc:
                self._set("failed", f"Impossible de lancer la connexion à Claude : {exc}")
                return
            self._proc = proc
            self._login_started = self._clock()
            self._set("logging_in")
