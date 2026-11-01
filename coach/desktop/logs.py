"""Journal du lanceur de bureau : fichier tournant, stdout/stderr redirigés."""

from __future__ import annotations

import io
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from coach.config import data_dir

_UVICORN = ("uvicorn", "uvicorn.error", "uvicorn.access")

_etat: dict = {}


class _FluxJournal(io.TextIOBase):
    """Flux texte qui écrit ligne par ligne dans le journal."""

    def __init__(self, logger: logging.Logger, niveau: int) -> None:
        self._logger = logger
        self._niveau = niveau
        self._tampon = ""

    def writable(self) -> bool:
        return True

    def write(self, s: str) -> int:
        self._tampon += s
        *lignes, self._tampon = self._tampon.split("\n")
        for ligne in lignes:
            if ligne.strip():
                self._logger.log(self._niveau, ligne.rstrip())
        return len(s)

    def flush(self) -> None:
        if self._tampon.strip():
            self._logger.log(self._niveau, self._tampon.rstrip())
        self._tampon = ""


def setup_logging() -> Path:
    """Branche le journal tournant ; renvoie le chemin du fichier."""
    teardown_logging()
    dossier = data_dir() / "logs"
    dossier.mkdir(parents=True, exist_ok=True)
    chemin = dossier / "coachcloclo.log"
    handler = RotatingFileHandler(
        chemin, maxBytes=1_000_000, backupCount=5, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s : %(message)s")
    )
    racine = logging.getLogger()
    etat = {
        "handler": handler,
        "niveau": racine.level,
        "stdout": sys.stdout,
        "stderr": sys.stderr,
        "excepthook": sys.excepthook,
        "uvicorn": {},
    }
    racine.setLevel(logging.INFO)
    racine.addHandler(handler)
    # uvicorn coupe souvent la propagation : on lui branche le handler en direct.
    for nom in _UVICORN:
        lg = logging.getLogger(nom)
        etat["uvicorn"][nom] = lg.propagate
        lg.addHandler(handler)
        lg.propagate = False

    if sys.stdout is None:
        sys.stdout = _FluxJournal(logging.getLogger("stdout"), logging.INFO)
    if sys.stderr is None:
        sys.stderr = _FluxJournal(logging.getLogger("stderr"), logging.ERROR)

    def _hook(type_, valeur, tb) -> None:
        logging.getLogger("coach").critical(
            "exception non gérée", exc_info=(type_, valeur, tb)
        )

    sys.excepthook = _hook
    _etat.update(etat)
    return chemin


def teardown_logging() -> None:
    """Annule setup_logging : flux, excepthook et handlers retrouvent leur état."""
    if not _etat:
        return
    etat = dict(_etat)
    _etat.clear()
    handler = etat["handler"]
    for flux in (sys.stdout, sys.stderr):
        if isinstance(flux, _FluxJournal):
            flux.flush()
    sys.stdout = etat["stdout"]
    sys.stderr = etat["stderr"]
    sys.excepthook = etat["excepthook"]
    racine = logging.getLogger()
    racine.removeHandler(handler)
    racine.setLevel(etat["niveau"])
    for nom, propagate in etat["uvicorn"].items():
        lg = logging.getLogger(nom)
        lg.removeHandler(handler)
        lg.propagate = propagate
    handler.close()
