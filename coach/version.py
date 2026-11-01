"""Version de l'application."""

import re
from importlib.metadata import PackageNotFoundError, version

_VERSION = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")


def app_version() -> str:
    """Version installée du paquet, `0.0.0` s'il est introuvable."""
    try:
        return version("coachcloclo")
    except PackageNotFoundError:
        return "0.0.0"


def parse_version(v: str) -> tuple[int, int, int]:
    """`0.10.0` ou `v0.10.0` -> (0, 10, 0) ; ValueError si le format n'est pas X.Y.Z."""
    m = _VERSION.fullmatch(v.strip())
    if m is None:
        raise ValueError(f"version invalide : {v!r}")
    return int(m[1]), int(m[2]), int(m[3])
