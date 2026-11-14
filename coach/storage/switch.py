"""Bascule entre stockage local et cloud : sonde, activation, désactivation, effacement.

Règle commune : une base qui reçoit des données les reçoit par `copy_all` suivi de `verify_copy`
(le marqueur de fin dont dépend `is_empty`), et aucune donnée n'est supprimée avant cette vérification.
Ces fonctions ne touchent ni aux réglages ni à l'app : l'ordre des étapes est géré par l'API.
"""

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.engine import Engine

from coach.plan.models import Session
from coach.plan.repo import Repo, make_engine
from coach.storage.cloud_errors import CloudUnreachable, as_unreachable, is_cloud_failure
from coach.storage.source import DataSource, LocalSource
from coach.storage.transfer import CopyMismatch, copy_all, is_empty, verify_copy, wipe

__all__ = [
    "Adopted",
    "CloudStatus",
    "CloudUnreachable",
    "CopyMismatch",
    "NeedsConfirmation",
    "OpenedSource",
    "delete_local_files",
    "disable_cloud",
    "enable_cloud",
    "is_empty",
    "probe",
    "sessions_on_watch",
    "wipe_cloud",
]

PROBE_KEY = "probe"
_SQLITE_SIDE_FILES = ("-journal", "-wal", "-shm")
BACKUP_SUFFIX = ".bak"


class CloudStatus(BaseModel):
    mode: str
    turso_url: str | None
    has_turso_token: bool


class NeedsConfirmation:
    """Le cloud contient déjà des données : les adopter remplacerait celles de ce PC."""


class Adopted:
    """Le cloud non vide a été adopté : rien de ce PC n'y a été écrit."""

    def __init__(self, engine: Engine):
        self.engine = engine


class OpenedSource:
    """Source déjà ouverte (par `probe`) : évite de refaire contrôle de version et migrations."""

    def __init__(self, kind: str, engine: Engine):
        self.kind = kind
        self._engine = engine

    def engine(self) -> Engine:
        return self._engine


def probe(source: DataSource) -> Engine:
    """Ouvre la base, puis y lit et écrit une valeur ; `SchemaTooNew` passe tel quel."""
    engine = None
    try:
        engine = source.engine()
        repo = Repo(engine)
        repo.get_state(PROBE_KEY)
        repo.set_state(PROBE_KEY, {"at": datetime.now(timezone.utc).isoformat()})
    except Exception as exc:
        if engine is not None:
            engine.dispose()
        if is_cloud_failure(exc):
            raise as_unreachable(exc) from exc
        raise
    return engine


def enable_cloud(
    current: Engine, cloud: DataSource, *, replace_local: bool
) -> Engine | NeedsConfirmation | Adopted:
    """Cloud vide : y copie la base courante (vérifiée). Sinon l'adopte tel quel, sur confirmation."""
    engine = cloud.engine()
    if is_empty(engine):
        copy_all(current, engine)
        verify_copy(current, engine)
        return engine
    if not replace_local:
        return NeedsConfirmation()
    return Adopted(engine)  # rien de ce PC n'est écrit dans le cloud


def sessions_on_watch(engine: Engine) -> int:
    """Séances de cette base envoyées sur la montre (exportées ou en erreur de synchro)."""
    t = Session.__table__
    query = select(func.count()).select_from(t).where(
        t.c.status.in_(("exported", "sync_error")),
        or_(t.c.garmin_workout_id.is_not(None), t.c.garmin_schedule_id.is_not(None)),
    )
    with engine.connect() as conn:
        return conn.execute(query).scalar() or 0


def _remove_sqlite_files(path: Path) -> None:
    for suffix in _SQLITE_SIDE_FILES:
        path.with_name(path.name + suffix).unlink(missing_ok=True)


def disable_cloud(cloud: Engine, local: LocalSource) -> Engine:
    """Recopie le cloud dans un fichier voisin de `coach.db`, vérifie, puis remplace `coach.db`."""
    tmp = local.path.with_name(local.path.name + ".tmp")
    tmp.unlink(missing_ok=True)
    _remove_sqlite_files(tmp)
    tmp_engine = make_engine(tmp)
    try:
        copy_all(cloud, tmp_engine)
        verify_copy(cloud, tmp_engine)
    except BaseException:
        tmp_engine.dispose()
        tmp.unlink(missing_ok=True)
        raise
    tmp_engine.dispose()
    # un journal périmé de l'ancien coach.db serait rejoué sur la nouvelle base
    _remove_sqlite_files(local.path)
    try:
        os.replace(tmp, local.path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return local.engine()


def wipe_cloud(cloud: Engine) -> None:
    wipe(cloud)


def delete_local_files(home: Path, *, keep_backup: bool = False) -> None:
    """Supprime `coach.db` (et ses fichiers SQLite annexes), `gpx/` et `history.json` s'ils existent.

    `keep_backup` : `coach.db` est renommé en `coach.db.bak` (remplace l'ancien) au lieu d'être supprimé.
    `coach.db.bak` n'est jamais supprimé.
    """
    db = home / "coach.db"
    if keep_backup and db.exists():
        os.replace(db, db.with_name(db.name + BACKUP_SUFFIX))
    db.unlink(missing_ok=True)
    _remove_sqlite_files(db)
    if (home / "gpx").is_dir():
        shutil.rmtree(home / "gpx")
    (home / "history.json").unlink(missing_ok=True)
