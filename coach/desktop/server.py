"""Serveur uvicorn relançable : même app, même port, hôte modifiable à chaud."""

from __future__ import annotations

import logging
import threading
import time

import uvicorn

_log = logging.getLogger(__name__)

_DELAI_DEMARRAGE_S = 10.0
_DELAI_ARRET_S = 15.0
# une requête longue (génération de plan) ne doit pas bloquer l'arrêt
_DELAI_ARRET_GRACIEUX_S = 3


class AppServer:
    """Fait tourner `app` dans un thread démon ; `restart` change l'hôte d'écoute."""

    def __init__(self, app, port: int) -> None:
        self.app = app
        self.port = port
        self.host = ""
        self._verrou = threading.RLock()
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None

    def start(self, host: str) -> None:
        """Lance le serveur ; revient une fois qu'il écoute (10 s max).

        Si un serveur tourne déjà, il est d'abord arrêté.
        """
        with self._verrou:
            self._arreter()
            self._lancer(host)

    def _lancer(self, host: str) -> None:
        config = uvicorn.Config(
            self.app,
            host=host,
            port=self.port,
            log_config=None,
            timeout_graceful_shutdown=_DELAI_ARRET_GRACIEUX_S,
        )
        server = uvicorn.Server(config)
        thread = threading.Thread(target=self._executer, args=(server,), name="coach-uvicorn", daemon=True)
        thread.start()
        fin = time.monotonic() + _DELAI_DEMARRAGE_S
        while not server.started:
            if not thread.is_alive():
                raise RuntimeError(f"Le serveur n'a pas pu démarrer sur {host}:{self.port}")
            if time.monotonic() > fin:
                server.should_exit = True
                thread.join(_DELAI_ARRET_S)
                raise RuntimeError(f"Le serveur n'a pas démarré en {_DELAI_DEMARRAGE_S:.0f} s")
            time.sleep(0.02)
        self._server, self._thread, self.host = server, thread, host

    @staticmethod
    def _executer(server: uvicorn.Server) -> None:
        """uvicorn lève SystemExit si le port est occupé : on l'absorbe (le thread meurt)."""
        try:
            server.run()
        except SystemExit:
            pass

    def _arreter(self) -> None:
        server, thread = self._server, self._thread
        self._server = self._thread = None
        self.host = ""
        if server is None or thread is None:
            return
        server.should_exit = True
        thread.join(_DELAI_ARRET_S)
        if thread.is_alive():
            raise RuntimeError("Le serveur ne s'est pas arrêté à temps")

    def stop(self) -> None:
        """Arrête le serveur et attend la libération du port ; sans effet s'il est déjà arrêté."""
        with self._verrou:
            self._arreter()

    def restart(self, host: str) -> None:
        """Arrête puis relance sur `host` (même app, même port).

        Si l'ancien serveur tarde à s'arrêter, la relance est tentée quand même (sa socket
        d'écoute est déjà fermée). En cas d'échec, tente de relancer sur l'ancien hôte,
        puis relève l'erreur.
        """
        with self._verrou:
            ancien = self.host
            try:
                self._arreter()
            except Exception:
                _log.exception("Arrêt incomplet du serveur ; relance sur %s tentée quand même", host)
            try:
                self._lancer(host)
            except Exception:
                _log.exception("Relance sur %s impossible", host)
                if ancien:
                    try:
                        self._lancer(ancien)
                    except Exception:
                        _log.exception("Retour sur %s impossible", ancien)
                raise
