"""Mises à jour de la version Windows : vérification GitHub, téléchargement, installation."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import tempfile
import threading
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from coach.version import parse_version

_log = logging.getLogger(__name__)

DEFAULT_REPO = "romigour/CoachCloclo"
INSTALLER_ARGS = ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"]

_DELAI_RESEAU_S = 10
_BLOC = 64 * 1024


def repo_from_env() -> str:
    """Dépôt GitHub des releases : `COACH_UPDATE_REPO` ou le dépôt officiel."""
    return os.environ.get("COACH_UPDATE_REPO") or DEFAULT_REPO


@dataclass
class UpdateInfo:
    version: str
    installer_url: str
    sha256_url: str


class UpdateError(Exception):
    """Échec de vérification ou d'installation (message destiné à l'utilisateur)."""


class UpdateBusy(Exception):
    """Un téléchargement ou une installation est déjà en cours."""


class Updater:
    def __init__(
        self,
        current: str,
        repo: str,
        fetch_json: Callable[[str], dict],
        fetch_text: Callable[[str], str],
        download: Callable[[str, Path, Callable[[int], None]], None],
        spawn: Callable[[list[str]], None],
        tmp_dir: Path,
    ) -> None:
        self._current = current
        self._repo = repo
        self._fetch_json = fetch_json
        self._fetch_text = fetch_text
        self._download = download
        self._spawn = spawn
        self._tmp_dir = Path(tmp_dir)
        self._lock = threading.Lock()
        self._state = "idle"
        self._progress = 0
        self._error: str | None = None
        self._latest: UpdateInfo | None = None

    # -- lecture ---------------------------------------------------------

    def view(self) -> dict:
        with self._lock:
            return {
                "current": self._current,
                "latest": self._latest.version if self._latest else None,
                "available": self._latest is not None,
                "state": self._state,
                "progress": self._progress,
                "error": self._error,
            }

    # -- vérification ----------------------------------------------------

    def check(self) -> UpdateInfo | None:
        """Interroge GitHub ; None s'il n'y a rien de plus récent d'installable."""
        with self._lock:
            if self._state in ("idle", "failed"):
                self._state = "checking"
            self._error = None
        try:
            info = self._chercher()
        except UpdateError as e:
            with self._lock:
                self._error = str(e)
                self._etat_repos()
            raise
        with self._lock:
            self._latest = info
            self._etat_repos()
        return info

    def _etat_repos(self) -> None:
        # Appelé sous verrou : sort de "checking" sans toucher à un téléchargement en cours.
        if self._state == "checking":
            self._state = "idle"

    def _chercher(self) -> UpdateInfo | None:
        url = f"https://api.github.com/repos/{self._repo}/releases/latest"
        try:
            release = self._fetch_json(url)
            tag = release["tag_name"]
            assets = {a["name"]: a["browser_download_url"] for a in release["assets"]}
        except (OSError, ValueError, KeyError, TypeError) as e:
            raise UpdateError(f"Impossible de vérifier les mises à jour : {e}") from e
        try:
            nouvelle = parse_version(tag)
            courante = parse_version(self._current)
        except ValueError:
            _log.warning("Version non reconnue (tag %r, courante %r), pas de mise à jour", tag, self._current)
            return None
        if nouvelle <= courante:
            return None
        version = ".".join(str(n) for n in nouvelle)
        nom = f"CoachCloclo-Setup-{version}.exe"
        if nom not in assets or f"{nom}.sha256" not in assets:
            _log.info("Release %s sans installateur complet, ignorée", tag)
            return None
        return UpdateInfo(version, assets[nom], assets[f"{nom}.sha256"])

    # -- installation ----------------------------------------------------

    def start_install(self, on_exit: Callable[[], None]) -> None:
        """Réserve l'installation (UpdateBusy sinon) puis la déroule dans un thread démon."""
        info = self._reserver()
        threading.Thread(
            target=self._executer, args=(info, on_exit), name="coach-update", daemon=True
        ).start()

    def install(self, on_exit: Callable[[], None]) -> None:
        """Version synchrone. Un échec est consigné dans `view()`, pas levé."""
        self._executer(self._reserver(), on_exit)

    def _reserver(self) -> UpdateInfo:
        with self._lock:
            if self._state in ("downloading", "installing"):
                raise UpdateBusy("Une mise à jour est déjà en cours")
            if self._latest is None:
                raise UpdateError("Aucune mise à jour disponible")
            self._state = "downloading"
            self._progress = 0
            self._error = None
            return self._latest

    def _progression(self, pct: int) -> None:
        with self._lock:
            self._progress = pct

    def _echec(self, message: str) -> None:
        _log.error("Mise à jour échouée : %s", message)
        with self._lock:
            self._state = "failed"
            self._error = message

    def _executer(self, info: UpdateInfo, on_exit: Callable[[], None]) -> None:
        exe = self._tmp_dir / f"CoachCloclo-Setup-{info.version}.exe"
        try:
            self._tmp_dir.mkdir(parents=True, exist_ok=True)
            self._download(info.installer_url, exe, self._progression)
            attendu = self._fetch_text(info.sha256_url).lstrip("﻿").split()[0].lower()
            if _sha256(exe) != attendu:
                self._supprimer(exe)
                self._echec("Le fichier téléchargé est corrompu, réessaie")
                return
            with self._lock:
                self._state = "installing"
            self._spawn([str(exe), *INSTALLER_ARGS])
        except Exception as e:
            _log.exception("Mise à jour : échec du téléchargement ou de l'installation")
            self._supprimer(exe)
            self._echec(f"Échec de la mise à jour : {e}")
            return
        try:
            on_exit()
        except Exception:
            _log.exception("Mise à jour : l'arrêt de l'application a échoué")

    @staticmethod
    def _supprimer(chemin: Path) -> None:
        try:
            chemin.unlink(missing_ok=True)
        except OSError:
            pass


def _sha256(chemin: Path) -> str:
    h = hashlib.sha256()
    with open(chemin, "rb") as f:
        while bloc := f.read(_BLOC):
            h.update(bloc)
    return h.hexdigest()


# -- implémentations réelles ---------------------------------------------


def _ouvrir(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "CoachCloclo"})
    return urllib.request.urlopen(req, timeout=_DELAI_RESEAU_S)


def _fetch_json(url: str) -> dict:
    with _ouvrir(url) as r:
        return json.loads(r.read().decode("utf-8"))


def _fetch_text(url: str) -> str:
    with _ouvrir(url) as r:
        return r.read().decode("utf-8-sig")


def _download(url: str, dest: Path, progress: Callable[[int], None]) -> None:
    with _ouvrir(url) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        lu = 0
        while bloc := r.read(_BLOC):
            f.write(bloc)
            lu += len(bloc)
            if total:
                progress(min(100, lu * 100 // total))
    progress(100)


def _spawn(args: list[str]) -> None:
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
        subprocess, "CREATE_NEW_PROCESS_GROUP", 0
    )
    subprocess.Popen(args, creationflags=flags, close_fds=True)


def default_updater(current: str) -> Updater:
    return Updater(
        current=current,
        repo=repo_from_env(),
        fetch_json=_fetch_json,
        fetch_text=_fetch_text,
        download=_download,
        spawn=_spawn,
        tmp_dir=Path(tempfile.gettempdir()) / "CoachCloclo-update",
    )
