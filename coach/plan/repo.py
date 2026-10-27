"""Dépôt SQLite : accès aux données du plan."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path

from sqlalchemy.engine import Engine
from sqlmodel import Session as DbSession
from sqlmodel import SQLModel, create_engine, select

from coach.plan.models import Activity, AthleteSnapshot, Goal, Proposal, Session


def make_engine(path: Path) -> Engine:
    """Moteur SQLite sur `path` ; crée les tables si besoin."""
    engine = create_engine(f"sqlite:///{path}")
    SQLModel.metadata.create_all(engine)
    return engine


class Repo:
    def __init__(self, engine: Engine):
        self.engine = engine

    def _open(self) -> DbSession:
        return DbSession(self.engine, expire_on_commit=False)

    @contextmanager
    def transaction(self) -> Iterator[DbSession]:
        """Session commitée en cas de succès, annulée sur exception."""
        with self._open() as db:
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def add(self, obj):
        with self._open() as db:
            db.add(obj)
            db.commit()
            db.refresh(obj)
        return obj

    def update(self, obj):
        with self._open() as db:
            merged = db.merge(obj)
            db.commit()
            db.refresh(merged)
        return merged

    def active_goal(self) -> Goal | None:
        with self._open() as db:
            stmt = select(Goal).where(Goal.status == "active").order_by(Goal.id.desc())
            return db.exec(stmt).first()

    def sessions(self, goal_id: int, week_index: int | None = None) -> list[Session]:
        stmt = select(Session).where(Session.goal_id == goal_id)
        if week_index is not None:
            stmt = stmt.where(Session.week_index == week_index)
        stmt = stmt.order_by(Session.week_index, Session.order)
        with self._open() as db:
            return list(db.exec(stmt))

    def session(self, id: int) -> Session:
        with self._open() as db:
            obj = db.get(Session, id)
        if obj is None:
            raise KeyError(f"séance {id} introuvable")
        return obj

    def activities_since(self, d: date) -> list[Activity]:
        stmt = select(Activity).where(Activity.date >= d).order_by(Activity.date, Activity.id)
        with self._open() as db:
            return list(db.exec(stmt))

    def activity_by_garmin_id(self, gid: int) -> Activity | None:
        stmt = select(Activity).where(Activity.garmin_activity_id == gid)
        with self._open() as db:
            return db.exec(stmt).first()

    def pending_proposal(self) -> Proposal | None:
        stmt = select(Proposal).where(Proposal.status == "pending").order_by(Proposal.id.desc())
        with self._open() as db:
            return db.exec(stmt).first()

    def latest_snapshot(self) -> AthleteSnapshot | None:
        stmt = select(AthleteSnapshot).order_by(AthleteSnapshot.date.desc(), AthleteSnapshot.id.desc())
        with self._open() as db:
            return db.exec(stmt).first()
