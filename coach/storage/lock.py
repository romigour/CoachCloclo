"""Verrou Garmin partagé entre PC : une seule ligne `GarminLock` (id = 1) dans la base.

En mode local le verrou est toujours libre ; le même chemin de code sert aux deux modes.
Toutes les dates sont stockées en UTC.
"""

import secrets
import socket
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import case, delete, or_, update
from sqlalchemy.dialects.sqlite import insert

from coach.config import data_dir
from coach.garmin.port import GarminPort, GarminUnavailable
from coach.plan.models import GarminLock
from coach.plan.repo import Repo

LOCK_MSG = "Synchronisation en cours sur un autre PC"
WRITE_TTL = timedelta(minutes=2)
SYNC_TTL = timedelta(minutes=15)
IMPORT_TTL = timedelta(minutes=5)


class GarminLocked(GarminUnavailable):
    """Le verrou Garmin est détenu par un autre PC."""

    def __init__(self) -> None:
        super().__init__(LOCK_MSG)


def machine_id() -> str:
    """Identifiant stable de ce PC (`<hôte>-<8 hex>`), créé une fois dans le dossier de données local."""
    path = data_dir() / "machine_id"
    try:
        existing = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        existing = ""
    if existing:
        return existing
    mid = f"{socket.gethostname()}-{secrets.token_hex(4)}"
    path.write_text(mid, encoding="utf-8")
    return mid


def _utc(d: datetime) -> datetime:
    """Date en UTC ; une date naïve est supposée déjà en UTC."""
    return d.astimezone(timezone.utc) if d.tzinfo else d.replace(tzinfo=timezone.utc)


def try_acquire(repo: Repo, holder: str, ttl: timedelta, now: datetime) -> bool:
    """Prend ou prolonge le verrou s'il est libre, expiré ou déjà détenu par `holder`.

    Atomique : `INSERT OR IGNORE` de la ligne unique, sinon un seul `UPDATE` conditionnel.
    Une prolongation ne raccourcit jamais un verrou déjà détenu plus longtemps.
    """
    now = _utc(now)
    expires = now + ttl
    with repo.transaction() as db:
        inserted = db.execute(
            insert(GarminLock).values(id=1, holder=holder, expires_at=expires).on_conflict_do_nothing()
        )
        if inserted.rowcount == 1:
            return True
        updated = db.execute(
            update(GarminLock)
            .where(GarminLock.id == 1, or_(GarminLock.holder == holder, GarminLock.expires_at < now))
            .values(
                expires_at=case(
                    (
                        (GarminLock.holder == holder) & (GarminLock.expires_at > expires),
                        GarminLock.expires_at,
                    ),
                    else_=expires,
                ),
                holder=holder,
            )
        )
        return updated.rowcount == 1


def release(repo: Repo, holder: str) -> None:
    """Libère le verrou, seulement si `holder` le détient."""
    with repo.transaction() as db:
        db.execute(delete(GarminLock).where(GarminLock.id == 1, GarminLock.holder == holder))


def held_elsewhere(repo: Repo, holder: str, now: datetime) -> bool:
    """Vrai si un autre PC détient un verrou non expiré."""
    with repo.transaction() as db:
        row = db.get(GarminLock, 1)
    return row is not None and row.holder != holder and row.expires_at >= _utc(now)


@contextmanager
def garmin_lock(repo: Repo, holder: str, ttl: timedelta) -> Iterator[None]:
    """Détient le verrou pendant le bloc ; lève `GarminLocked` s'il est pris ailleurs."""
    if not try_acquire(repo, holder, ttl, datetime.now(timezone.utc)):
        raise GarminLocked()
    try:
        yield
    finally:
        release(repo, holder)


class LockedGarmin:
    """Enveloppe d'un `GarminPort` : chaque écriture prend (ou prolonge) le verrou avant d'agir."""

    def __init__(self, inner: GarminPort, repo_getter: Callable[[], Repo], holder: str):
        self._inner = inner
        self._repo_getter = repo_getter  # suit la bascule de base à chaud
        self._holder = holder

    def _acquire(self) -> None:
        if not try_acquire(self._repo_getter(), self._holder, WRITE_TTL, datetime.now(timezone.utc)):
            raise GarminLocked()

    # --- lectures : déléguées telles quelles ---

    def __getattr__(self, name: str):
        return getattr(self._inner, name)

    # --- écritures ---

    def upload_workout(self, workout: dict) -> int:
        self._acquire()
        return self._inner.upload_workout(workout)

    def schedule(self, workout_id: int, d: date) -> int:
        self._acquire()
        return self._inner.schedule(workout_id, d)

    def reschedule(self, schedule_id: int, d: date) -> None:
        self._acquire()
        self._inner.reschedule(schedule_id, d)

    def unschedule(self, schedule_id: int) -> None:
        self._acquire()
        self._inner.unschedule(schedule_id)

    def delete_workout(self, workout_id: int) -> None:
        self._acquire()
        self._inner.delete_workout(workout_id)
