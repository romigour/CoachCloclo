"""Copie, vérification et effacement d'une base (SQLAlchemy Core, sans ORM).

Les deux moteurs sont déjà préparés (schéma présent, même version). La destination
peut être libSQL : aucune dépendance aux types d'exception du driver.
Hypothèse : `dst` n'a pas de colonne NOT NULL absente du modèle (schéma préparé par l'app).
"""

import datetime as dt
import json

from sqlalchemy import Engine, Table, delete, func, insert, select
from sqlmodel import SQLModel

from coach.plan.models import AppState, GarminLock

BATCH = 500  # lignes par INSERT : borne la taille de chaque requête vers la base distante
COMPLETE_KEY = "copy_complete"
_TECHNICAL_KEYS = ("schema_version", COMPLETE_KEY)
_STATE = AppState.__table__
_LOCK = GarminLock.__table__  # verrou entre PC : propre à chaque base, jamais copié ni compté


class CopyMismatch(Exception):
    """Le nombre de lignes d'une table diffère entre source et destination."""

    def __init__(self, table: str):
        super().__init__(f"Copie incomplète : table {table}")
        self.table = table


def _not_marker(table: Table) -> tuple:
    """Le marqueur de fin n'est ni copié ni compté : il n'appartient qu'à la destination."""
    return (_STATE.c.key != COMPLETE_KEY,) if table is _STATE else ()


def _data_tables() -> list[Table]:
    return [t for t in SQLModel.metadata.sorted_tables if t is not _LOCK]


def _count(conn, table: Table, *where) -> int:
    return conn.execute(select(func.count()).select_from(table).where(*where)).scalar() or 0


def is_empty(engine: Engine) -> bool:
    """Vrai si aucune donnée applicative, ou si la copie n'a pas été marquée terminée."""
    with engine.connect() as conn:
        marker = conn.execute(select(_STATE.c.key).where(_STATE.c.key == COMPLETE_KEY)).first()
        if marker is None:
            return True
        for table in _data_tables():
            where = (_STATE.c.key.not_in(_TECHNICAL_KEYS),) if table is _STATE else ()
            if _count(conn, table, *where):
                return False
        return True


def _insert_rows(conn, table: Table, rows: list[dict]) -> None:
    conn.execute(insert(table), rows)


def copy_all(src: Engine, dst: Engine) -> None:
    """Vide `dst` puis y copie toutes les tables (sauf le verrou Garmin), en une transaction."""
    # Marqueur effacé et validé d'abord : une copie interrompue n'est jamais « complète ».
    with dst.begin() as conn:
        conn.execute(delete(_STATE).where(_STATE.c.key == COMPLETE_KEY))
    tables = _data_tables()
    with src.connect() as sconn, dst.begin() as dconn:
        for table in reversed(tables):
            dconn.execute(delete(table))
        for table in tables:
            result = sconn.execute(select(table).where(*_not_marker(table)))
            while batch := result.mappings().fetchmany(BATCH):
                _insert_rows(dconn, table, [dict(r) for r in batch])


def verify_copy(src: Engine, dst: Engine) -> None:
    """Compare les nombres de lignes par table, puis écrit le marqueur de fin dans `dst`."""
    with src.connect() as sconn, dst.connect() as dconn:
        for table in _data_tables():
            where = _not_marker(table)
            if _count(sconn, table, *where) != _count(dconn, table, *where):
                raise CopyMismatch(table.name)
    marker = json.dumps({"at": dt.datetime.now(dt.timezone.utc).isoformat()})
    with dst.begin() as conn:
        conn.execute(delete(_STATE).where(_STATE.c.key == COMPLETE_KEY))
        conn.execute(insert(_STATE).values(key=COMPLETE_KEY, value_json=marker))


def wipe(engine: Engine) -> None:
    """Supprime toutes les lignes des tables applicatives (version de schéma comprise)."""
    with engine.begin() as conn:
        for table in reversed(SQLModel.metadata.sorted_tables):
            conn.execute(delete(table))
