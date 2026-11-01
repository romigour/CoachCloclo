"""Sous-processus : pas de fenêtre console sous Windows, recherche du CLI Claude."""

import shutil
import subprocess
import sys
from pathlib import Path

NO_WINDOW: int = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def find_claude(which=shutil.which, home: Path | None = None) -> str | None:
    """Chemin du CLI claude : le PATH d'abord, sinon `~/.local/bin` (installeur officiel)."""
    found = which("claude")
    if found:
        return found
    name = "claude.exe" if sys.platform == "win32" else "claude"
    candidate = (home if home is not None else Path.home()) / ".local" / "bin" / name
    return str(candidate) if candidate.exists() else None
