"""Instance unique, choix du port et état courant du lanceur de bureau."""

from __future__ import annotations

import json
import socket
import sys
from collections.abc import Callable

from coach.config import data_dir

PORTS: tuple[int, ...] = (8765, *range(8766, 8776))

_ERROR_ALREADY_EXISTS = 183


class NoFreePort(RuntimeError):
    """Aucun des ports prévus n'est libre."""


def port_free(port: int) -> bool:
    """Vrai si le port est libre sur la boucle locale."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def pick_port(is_free: Callable[[int], bool] | None = None) -> int:
    """Premier port libre de PORTS ; NoFreePort sinon.

    `port_free` et `PORTS` sont lus à l'appel (et non à la définition) pour
    rester substituables dans les tests.
    """
    test = is_free if is_free is not None else port_free
    for port in PORTS:
        if test(port):
            return port
    raise NoFreePort(f"aucun port libre parmi {PORTS[0]}-{PORTS[-1]}")


def write_state(port: int, pid: int) -> None:
    """Enregistre le port et le pid de l'instance courante."""
    (data_dir() / "desktop.json").write_text(
        json.dumps({"port": port, "pid": pid}), encoding="utf-8"
    )


def read_state() -> dict | None:
    """État enregistré, ou None s'il est absent ou illisible."""
    try:
        data = json.loads((data_dir() / "desktop.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def acquire_mutex(name: str = "CoachCloclo.Instance") -> object | None:
    """Prend le verrou d'instance unique ; None s'il est déjà détenu."""
    if sys.platform == "win32":
        return _acquire_windows(name)
    return _acquire_fichier()


def release_mutex(handle: object) -> None:
    """Relâche un verrou obtenu par acquire_mutex."""
    if handle is None:
        return
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        kernel32.ReleaseMutex(handle)
        kernel32.CloseHandle(handle)
    else:
        try:
            handle.close()  # type: ignore[attr-defined]  # ferme le fichier, libère le verrou
        except OSError:
            pass


def _acquire_windows(name: str) -> object | None:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.CreateMutexW(None, False, name)
    if not handle:
        return None
    if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)  # second handle du même mutex : on le rend
        return None
    return handle


def _acquire_fichier() -> object | None:
    """Repli hors Windows : verrou de fichier non bloquant."""
    import fcntl

    f = open(data_dir() / "desktop.lock", "w")  # noqa: SIM115 - gardé ouvert tant que détenu
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    return f
