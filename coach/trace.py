"""Journaux de diagnostic : appels Claude et Garmin, activables dans les Paramètres.

Chaque catégorie écrit dans son propre fichier (`<données>/logs/<catégorie>.log`), sans
passer par le journal principal. Les réglages sont relus à chaque entrée : activer ou
couper un journal prend effet tout de suite. Les secrets sont masqués et une erreur
d'écriture n'est jamais remontée à l'appelant.
"""

from __future__ import annotations

import json
import logging
import secrets as _secrets
from collections.abc import Iterable
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Literal

from coach.config import data_dir, load_settings

Category = Literal["claude", "garmin"]

GARMIN_MAX_CHARS = 20_000
MAX_BYTES = 5_000_000
BACKUP_COUNT = 3
MASK = "***"

_SENSITIVE = ("password", "passwd", "token", "secret", "api_key", "apikey",
              "authorization", "cookie", "oauth", "ticket", "mfa")

_handlers: dict[Path, RotatingFileHandler] = {}


def logs_dir() -> Path:
    path = data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def enabled(category: Category) -> bool:
    try:
        s = load_settings()
        return bool(s.trace_claude if category == "claude" else s.trace_garmin)
    except Exception:
        return False


def new_call_id() -> str:
    return _secrets.token_hex(4)


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}… [tronqué, {len(text)} caractères au total]"


def _sensitive(key: Any) -> bool:
    k = str(key).lower()
    return any(word in k for word in _SENSITIVE)


def redact(value: Any, secrets: Iterable[str] = ()) -> Any:
    """Copie de `value` : clés sensibles et secrets littéraux remplacés par `***`."""
    literals = [s for s in secrets if s]

    def walk(v: Any) -> Any:
        if isinstance(v, dict):
            return {k: MASK if _sensitive(k) else walk(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [walk(x) for x in v]
        if isinstance(v, str):
            for s in literals:
                v = v.replace(s, MASK)
            return v
        return v

    return walk(value)


def _logger(category: Category) -> logging.Logger:
    logger = logging.getLogger(f"coach.trace.{category}")
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    path = logs_dir() / f"{category}.log"
    handler = _handlers.get(path)
    if handler is None:
        handler = RotatingFileHandler(path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT,
                                      encoding="utf-8", delay=True)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        _handlers[path] = handler
    for old in list(logger.handlers):
        if old is not handler:
            logger.removeHandler(old)
    if handler not in logger.handlers:
        logger.addHandler(handler)
    return logger


def _default(o: Any) -> Any:
    if isinstance(o, bytes):
        return o.decode("utf-8", errors="replace")
    return str(o)


def record(category: Category, call_id: str, event: str, *, level: int = logging.INFO,
           **fields: Any) -> None:
    """Ajoute une entrée si le journal `category` est activé ; n'échoue jamais."""
    try:
        s = load_settings()
        if not (s.trace_claude if category == "claude" else s.trace_garmin):
            return
        literals = [s.anthropic_api_key or "", s.turso_token or ""]
        # sérialisation d'abord (objets quelconques → texte), masquage ensuite
        plain = json.loads(json.dumps(fields, default=_default, ensure_ascii=False))
        body = json.dumps(redact(plain, literals), indent=2, ensure_ascii=False)
        _logger(category).log(level, "[%s] %s\n%s", call_id, event, body)
    except Exception:
        pass


def _reset_handlers() -> None:
    """Ferme et oublie les fichiers ouverts (tests, changement de dossier de données)."""
    for handler in _handlers.values():
        for category in ("claude", "garmin"):
            logging.getLogger(f"coach.trace.{category}").removeHandler(handler)
        handler.close()
    _handlers.clear()
