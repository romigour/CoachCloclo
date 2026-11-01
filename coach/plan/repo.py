"""Dépôt SQLite : accès aux données du plan."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path

from sqlalchemy.engine import Engine
from sqlmodel import Session as DbSession
from sqlmodel import SQLModel, create_engine, delete, select

from coach.plan.models import (
    Activity,
    AthleteSnapshot,
    Goal,
    PersonalRecord,
    Proposal,
    Race,
    RaceStrategy,
    Session,
)


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

    def race_strategy(self, goal_id: int) -> RaceStrategy | None:
        with self._open() as db:
            return db.exec(select(RaceStrategy).where(RaceStrategy.goal_id == goal_id)).first()

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

    def all_activities(self) -> list[Activity]:
        stmt = select(Activity).order_by(Activity.date, Activity.id)
        with self._open() as db:
            return list(db.exec(stmt))

    def has_activities(self) -> bool:
        with self._open() as db:
            return db.exec(select(Activity.id).limit(1)).first() is not None

    def activity(self, id: int) -> Activity:
        with self._open() as db:
            obj = db.get(Activity, id)
        if obj is None:
            raise KeyError(f"activité {id} introuvable")
        return obj

    def races(self) -> list[Race]:
        with self._open() as db:
            return list(db.exec(select(Race).order_by(Race.id)))

    def _save_race(self, activity_id: int, fields: dict) -> Race:
        with self.transaction() as db:
            race = db.exec(select(Race).where(Race.activity_id == activity_id)).first()
            if race is None:
                race = Race(activity_id=activity_id)
            for key, value in fields.items():
                setattr(race, key, value)
            db.add(race)
            db.flush()
            db.refresh(race)
            return race

    def upsert_race(self, activity_id: int, fields: dict) -> Race:
        """Crée ou met à jour la course de l'activité ; la ré-inclut (`excluded=False`)."""
        return self._save_race(activity_id, {**fields, "excluded": False})

    def exclude_race(self, activity_id: int) -> None:
        """Marque l'activité comme non-course, en conservant les autres champs."""
        self._save_race(activity_id, {"excluded": True})

    def records(self) -> list[PersonalRecord]:
        with self._open() as db:
            return list(db.exec(select(PersonalRecord).order_by(PersonalRecord.id)))

    def replace_records(self, records: list[PersonalRecord]) -> None:
        """Remplace tous les records en une transaction."""
        with self.transaction() as db:
            db.exec(delete(PersonalRecord))
            for r in records:
                db.add(r)
