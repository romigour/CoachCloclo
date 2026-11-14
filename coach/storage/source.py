"""Sources de données interchangeables : base SQLite locale ou base cloud (Turso).

Pour ajouter un hébergeur : une classe `XxxSource` + une valeur de `Settings.storage_mode`.
"""

from pathlib import Path
from typing import Protocol

from sqlalchemy.engine import Engine

from coach.config import Settings, db_path
from coach.plan.repo import make_engine, prepare_engine
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
        host = self.url.split("://", 1)[-1].rstrip("/")  # accepte libsql://, https:// ou un hôte nu
        return prepare_engine(remote_engine(host, self.token))


def source_from_settings(s: Settings) -> DataSource:
    if s.storage_mode == "turso":
        return TursoSource(s.turso_url or "", s.turso_token or "")
    return LocalSource(db_path())
