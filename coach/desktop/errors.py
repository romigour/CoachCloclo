"""Erreurs fatales du lanceur : boîte de dialogue Windows, stderr ailleurs."""

from __future__ import annotations

import sys
from pathlib import Path


def fatal(message: str, log_path: Path | None = None) -> None:
    """Signale une erreur bloquante à l'utilisateur (le lanceur n'a pas de console)."""
    texte = message
    if log_path is not None:
        texte += f"\n\nJournal : {log_path}"
    if sys.platform == "win32":
        import ctypes

        # 0x10 = MB_ICONERROR
        ctypes.windll.user32.MessageBoxW(None, texte, "CoachCloclo", 0x10)
    else:
        print(texte, file=sys.stderr)
