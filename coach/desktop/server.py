"""Serveur uvicorn relançable : même app, même port, hôte modifiable à chaud."""

from __future__ import annotations

import threading
import time

import uvicorn

_DELAI_DEMARRAGE_S = 10.0
_DELAI_ARRET_S = 15.0


class AppServer:
    """Fait tourner `app` dans un thread démon ; `restart` change l'hôte d'écoute."""

    def __init__(self, app, port: int) -> None:
        self.app = app
        self.port = port
        self.host = ""
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None

    def start(self, host: str) -> None:
        """Lance le serveur ; revient une fois qu'il écoute (10 s max)."""
        config = uvicorn.Config(self.app, host=host, port=self.port, log_config=None)
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, name="coach-uvicorn", daemon=True)
        thread.start()
        fin = time.monotonic() + _DELAI_DEMARRAGE_S
        while not server.started:
            if not thread.is_alive():
                raise RuntimeError(f"Le serveur n'a pas pu démarrer sur {host}:{self.port}")
            if time.monotonic() > fin:
                server.should_exit = True
                raise RuntimeError(f"Le serveur n'a pas démarré en {_DELAI_DEMARRAGE_S:.0f} s")
            time.sleep(0.02)
        self._server, self._thread, self.host = server, thread, host

    def stop(self) -> None:
        """Arrête le serveur et attend la libération du port ; sans effet s'il est déjà arrêté."""
        server, thread = self._server, self._thread
        self._server = self._thread = None
        if server is None or thread is None:
            return
        server.should_exit = True
        thread.join(_DELAI_ARRET_S)
        if thread.is_alive():
            raise RuntimeError("Le serveur ne s'est pas arrêté à temps")

    def restart(self, host: str) -> None:
        """Arrête puis relance sur `host`, avec la même app et le même port."""
        self.stop()
        self.start(host)
