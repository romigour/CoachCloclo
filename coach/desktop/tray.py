"""Icône de notification (zone près de l'horloge) ; pystray et Pillow sont importés à la demande."""

from __future__ import annotations

import logging
import sys
import threading
from collections.abc import Callable
from pathlib import Path

_log = logging.getLogger(__name__)

_NOM_ICONE = "coachcloclo.ico"


def _chemin_icone() -> Path:
    """Icône embarquée (PyInstaller) ou, à défaut, celle du dépôt."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / _NOM_ICONE
    return Path(__file__).resolve().parents[2] / "packaging" / "windows" / _NOM_ICONE


def _charger_image():
    from PIL import Image

    chemin = _chemin_icone()
    try:
        return Image.open(chemin).convert("RGBA")
    except Exception:
        _log.warning("Icône %s illisible, image de repli utilisée", chemin)
        return Image.new("RGBA", (64, 64), (46, 125, 50, 255))


class Tray:
    def __init__(
        self,
        open_app: Callable[[], None],
        check_updates: Callable[[], str],
        quit_app: Callable[[], None],
    ) -> None:
        import pystray

        self._open_app = open_app
        self._check_updates = check_updates
        self._quit_app = quit_app
        menu = pystray.Menu(
            pystray.MenuItem("Ouvrir CoachCloclo", self._ouvrir, default=True),
            pystray.MenuItem("Vérifier les mises à jour", self._verifier),
            pystray.MenuItem("Quitter", self._quitter),
        )
        self._icon = pystray.Icon("CoachCloclo", _charger_image(), "CoachCloclo", menu)

    def _ouvrir(self, icon=None, item=None) -> None:
        self._open_app()

    def _verifier(self, icon=None, item=None) -> None:
        """Lance la vérification dans un thread : le fil de messages de pystray reste libre."""
        threading.Thread(target=self._verifier_fond, name="coach-update-tray", daemon=True).start()

    def _verifier_fond(self) -> None:
        try:
            message = self._check_updates()
        except Exception as e:
            _log.exception("Vérification des mises à jour impossible")
            message = str(e)
        self.notify(message)

    def _quitter(self, icon=None, item=None) -> None:
        self._quit_app()

    def run(self) -> None:
        """Bloque jusqu'à `stop()`."""
        self._icon.run()

    def stop(self) -> None:
        self._icon.stop()

    def notify(self, message: str) -> None:
        try:
            self._icon.notify(message, "CoachCloclo")
        except Exception:
            _log.exception("Notification impossible")
