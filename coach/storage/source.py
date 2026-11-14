"""Sources de données interchangeables : base SQLite locale ou base cloud (Turso).

Pour ajouter un hébergeur : une classe `XxxSource` + une valeur de `Settings.storage_mode`.
"""

from pathlib import Path
from typing import Protocol

from sqlalchemy.engine import Engine

from coach.config import Settings, db_path
from coach.plan.repo import make_engine, prepare_engine
from coach.storage.cloud_errors import as_unreachable, is_cloud_failure
from coach.storage.libsql_dialect import remote_engine


class DataSource(Protocol):
    kind: str

    def engine(self) -> Engine:
        """Moteur prêt à l'emploi : contrôle de version, tables et migrations appliqués."""
        ...


class LocalSource:
    kind = "local"

    def __init__(self, path: Path) -> None:
        self.path = path

    def engine(self) -> Engine:
        return make_engine(self.path)


def turso_host(url: str) -> str:
    """Hôte d'une URL Turso : accepte libsql://, https:// ou un hôte nu (casse et / final ignorés)."""
    return url.strip().split("://", 1)[-1].rstrip("/").lower()


def same_turso_url(a: str | None, b: str | None) -> bool:
    return bool(a) and bool(b) and turso_host(a) == turso_host(b)


class TursoSource:
    kind = "turso"

    def __init__(self, url: str, token: str) -> None:
        if not url:
            raise ValueError("URL Turso manquante")
        if not token:
            raise ValueError("Jeton Turso manquant")
        self.url = url
        self.token = token

    def engine(self) -> Engine:
        """Lève `CloudUnreachable` si la base ne répond pas ou refuse le jeton."""
        host = turso_host(self.url)
        engine = remote_engine(host, self.token)
        try:
            return prepare_engine(engine)
        except Exception as exc:
            engine.dispose()
            if is_cloud_failure(exc):
                raise as_unreachable(exc) from exc
            raise


def source_from_settings(s: Settings) -> DataSource:
    if s.storage_mode == "turso":
        return TursoSource(s.turso_url or "", s.turso_token or "")
    return LocalSource(db_path())
