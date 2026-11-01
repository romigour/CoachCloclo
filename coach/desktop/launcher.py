"""Point d'entrée de l'exécutable fenêtré CoachCloclo."""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import urllib.request
import webbrowser

from coach.api.app import create_app
from coach.config import load_settings, tokenstore_dir
from coach.desktop import instance
from coach.desktop.claude_setup import ClaudeSetup
from coach.desktop.context import Desktop, lan_addresses
from coach.desktop.errors import fatal
from coach.desktop.logs import setup_logging
from coach.desktop.server import AppServer
from coach.desktop.updater import UpdateError, default_updater
from coach.garmin.client import GarminClient
from coach.llm.provider import provider_from_settings
from coach.version import app_version

_log = logging.getLogger(__name__)

_DELAI_SONDE_S = 3


def _version_servie(port: int) -> str | None:
    """Version renvoyée par l'appli sur ce port, ou None si elle ne répond pas."""
    # sonde en boucle locale : jamais par le proxy système
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"http://127.0.0.1:{port}/api/version", timeout=_DELAI_SONDE_S) as r:
            return json.loads(r.read().decode("utf-8")).get("version")
    except Exception:
        return None


def _log_thread(args) -> None:
    _log.critical(
        "exception non gérée dans le thread %s",
        getattr(args.thread, "name", "?"),
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
    )


def _version_attendue(argv: list[str]) -> str | None:
    """Valeur de `--expect-version X` (test de fumée de la CI), ou None."""
    if "--expect-version" not in argv:
        return None
    i = argv.index("--expect-version")
    return argv[i + 1] if i + 1 < len(argv) else ""


def _fumee(port: int, attendue: str | None) -> int:
    """Code de retour du test de fumée : l'appli répond avec une version plausible."""
    actuelle = app_version()
    if actuelle == "0.0.0":
        _log.error("Test de fumée : métadonnées du paquet introuvables (version 0.0.0)")
        return 1
    if attendue is not None and actuelle != attendue:
        _log.error("Test de fumée : version %s, %s attendue", actuelle, attendue)
        return 1
    servie = _version_servie(port)
    if servie != actuelle:
        _log.error("Test de fumée : version servie %r, %s attendue", servie, actuelle)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    smoke = "--smoke" in argv
    ouvrir_navigateur = "--no-browser" not in argv

    def signaler(message: str, log_path=None) -> None:
        # en test de fumée (CI), une boîte de dialogue bloquerait le runner
        if smoke:
            _log.error("%s", message)
            print(message, file=sys.stderr)
        else:
            fatal(message, log_path)

    try:
        log = setup_logging()
    except Exception as e:
        signaler(str(e))
        return 1
    threading.excepthook = _log_thread
    mutex = None
    server: AppServer | None = None
    try:
        mutex = instance.acquire_mutex()
        if mutex is None:
            etat = instance.read_state()
            port = etat.get("port") if etat else None
            if port and _version_servie(int(port)) is not None:
                if ouvrir_navigateur:
                    webbrowser.open(f"http://127.0.0.1:{port}")
                return 0
            signaler(
                "CoachCloclo semble bloqué : quitte-le depuis l'icône près de l'horloge "
                "ou redémarre l'ordinateur",
                log,
            )
            return 1

        try:
            port = instance.pick_port()
        except instance.NoFreePort:
            signaler("Aucun port libre entre 8765 et 8775", log)
            return 1
        instance.write_state(port, os.getpid())

        settings = load_settings()
        lan = bool(settings.lan_enabled and settings.pin_hash)
        quitter = threading.Event()
        tray = None
        updater = default_updater(app_version())

        def set_lan(_actif: bool) -> None:
            # L'ordre des Timers n'est pas garanti : on relit l'état courant.
            try:
                server.restart("0.0.0.0" if web.state.lan else "127.0.0.1")
            except Exception:
                _log.exception("Changement du mode réseau local impossible")

        def request_exit() -> None:
            quitter.set()
            if tray is not None:
                tray.stop()

        web = create_app(
            lan=lan,
            garmin_factory=lambda: GarminClient.from_tokens(tokenstore_dir()),
            llm_factory=lambda: provider_from_settings(load_settings()),
            desktop=Desktop(
                updater=updater,
                claude=ClaudeSetup(),
                set_lan=set_lan,
                request_exit=request_exit,
                lan_addresses=lambda: lan_addresses(port),
            ),
        )
        server = AppServer(web, port)
        server.start("0.0.0.0" if lan else "127.0.0.1")

        if smoke:
            return _fumee(port, _version_attendue(argv))

        from coach.desktop.tray import Tray

        url = f"http://127.0.0.1:{port}"

        def verifier() -> str:
            try:
                info = updater.check()
            except UpdateError as e:
                return str(e)
            return f"Version {info.version} disponible" if info else "CoachCloclo est à jour"

        tray = Tray(lambda: webbrowser.open(url), verifier, request_exit)

        def verif_demarrage() -> None:
            try:
                info = updater.check()
            except Exception:
                _log.exception("Vérification des mises à jour impossible")
                return
            if info:
                tray.notify(f"Version {info.version} de CoachCloclo disponible")

        threading.Thread(target=verif_demarrage, name="coach-update", daemon=True).start()
        if ouvrir_navigateur:
            # --no-browser : relance après une mise à jour, l'onglet existant se recharge
            webbrowser.open(url)
        if quitter.is_set():
            tray.stop()
        else:
            tray.run()
        return 0
    except Exception as e:
        _log.exception("Erreur fatale")
        signaler(str(e), log)
        return 1
    finally:
        if server is not None:
            try:
                server.stop()
            except Exception:
                _log.exception("Arrêt du serveur impossible")
        if mutex is not None:
            instance.release_mutex(mutex)
