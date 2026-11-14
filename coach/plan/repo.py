"""Dépôt SQLite : accès aux données du plan."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path

from pydantic import TypeAdapter
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlmodel import Session as DbSession
from sqlmodel import SQLModel, create_engine, delete, select

from coach.garmin.port import LapSummary
from coach.plan.models import (
    ALL_DAYS_JSON,
    Activity,
    ActivityLaps,
    AppState,
    AthleteSnapshot,
    Cycle,
    Event,
    Goal,
    GpxFile,
    PersonalRecord,
    Proposal,
    Race,
    RaceStrategy,
    Session,
    _now,
)

_LAPS = TypeAdapter(list[LapSummary])

# Chaque changement de schéma futur doit incrémenter SCHEMA_VERSION.
SCHEMA_VERSION = 1


class SchemaTooNew(Exception):
    """La base a un schéma plus récent que cette version de l'app."""


def _check_schema_version(engine: Engine) -> None:
    """Refuse une base plus récente (avant toute migration) ; sinon inscrit SCHEMA_VERSION.

    Fonctionne sur tout moteur (fichier local ou base distante).
    """
    # has_table plutôt qu'un except : le type d'erreur « table absente » varie selon le driver (libsql : ValueError)
    if inspect(engine).has_table(AppState.__tablename__):
        with DbSession(engine) as db:
            row = db.get(AppState, "schema_version")
        found = json.loads(row.value_json)["v"] if row is not None else None
        if found is not None and found > SCHEMA_VERSION:
            raise SchemaTooNew(f"schéma {found} > {SCHEMA_VERSION}")
    SQLModel.metadata.create_all(engine)
    _migrate(engine)
    with DbSession(engine) as db:
        db.merge(AppState(key="schema_version", value_json=json.dumps({"v": SCHEMA_VERSION})))
        db.commit()


def prepare_engine(engine: Engine) -> Engine:
    """Contrôle de version, création des tables et migrations sur un moteur (local ou distant)."""
    _check_schema_version(engine)
    return engine


def make_engine(path: Path) -> Engine:
    """Moteur SQLite sur `path` ; crée les tables si besoin."""
    return prepare_engine(create_engine(f"sqlite:///{path}"))


def _add_columns(conn, table: str, columns: dict[str, str]) -> None:
    """Ajoute à `table` chaque colonne absente (DDL donné en valeur)."""
    existing = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
    for name, ddl in columns.items():
        if name not in existing:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def _migrate(engine: Engine) -> None:
    """Met à niveau une base existante, étape par étape (chacune idempotente)."""
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(goal)"))}
        if "target_time_s" not in columns:
            # temps visé de `goal`, repris de la stratégie de course
            _add_columns(conn, "goal", {"target_time_s": "INTEGER", "target_source": "VARCHAR"})
            rows = conn.execute(text("SELECT goal_id, settings_json FROM racestrategy")).all()
            for goal_id, settings_json in rows:
                try:
                    target = json.loads(settings_json).get("target_time_s")
                except (ValueError, AttributeError, TypeError):
                    continue  # ligne corrompue : ignorée, les autres sont reprises
                if target:
                    conn.execute(
                        text("UPDATE goal SET target_time_s = :t, target_source = 'user' WHERE id = :id"),
                        {"t": target, "id": goal_id},
                    )
        # jours possibles et jour de sortie longue
        _add_columns(
            conn,
            "goal",
            {
                "available_days_json": f"VARCHAR NOT NULL DEFAULT '{ALL_DAYS_JSON}'",
                "long_run_day": "VARCHAR",
            },
        )
        # sport des séances et option vélo de l'objectif
        _add_columns(conn, "session", {"sport": "VARCHAR NOT NULL DEFAULT 'run'"})
        _add_columns(conn, "goal", {"include_bike": "BOOLEAN NOT NULL DEFAULT 0"})
        # priorité des objectifs
        _add_columns(conn, "goal", {"priority": "VARCHAR NOT NULL DEFAULT 'principal'"})
        # temps estimés portés par une proposition d'ajustement
        _add_columns(conn, "proposal", {"estimates_json": "VARCHAR NOT NULL DEFAULT '[]'"})
        # séances et imprévus rattachés à un cycle (l'id du cycle reprend celui de l'objectif)
        legacy = False
        for table in ("session", "event"):
            cols = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
            if "goal_id" in cols and "cycle_id" not in cols:
                conn.execute(text(f"ALTER TABLE {table} RENAME COLUMN goal_id TO cycle_id"))
                legacy = True
        if legacy:
            # base d'avant les cycles : un cycle par objectif, de même id. Seul le plus récent des objectifs
            # actifs (comme l'ancien `active_goal`) garde un cycle actif ; les autres sont archivés.
            conn.execute(
                text(
                    "UPDATE goal SET status = 'archived' WHERE status = 'active' "
                    "AND id < (SELECT MAX(id) FROM goal WHERE status = 'active')"
                )
            )
            conn.execute(
                text("""
                    INSERT INTO cycle (id, created_at, status, plan_start, end_date, sessions_per_week,
                        available_days_json, long_run_day, include_bike, plan_accepted, needs_generation)
                    SELECT id, created_at, CASE WHEN status = 'active' THEN 'active' ELSE 'done' END,
                        plan_start, race_date, sessions_per_week, available_days_json, long_run_day,
                        include_bike, plan_accepted, 0
                    FROM goal WHERE id NOT IN (SELECT id FROM cycle)
                """)
            )


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

    def get_state(self, key: str) -> dict | None:
        with self._open() as db:
            row = db.get(AppState, key)
            return json.loads(row.value_json) if row else None

    def set_state(self, key: str, value: dict) -> None:
        with self._open() as db:
            db.merge(AppState(key=key, value_json=json.dumps(value)))
            db.commit()

    def gpx(self, goal_id: int) -> bytes | None:
        with self._open() as db:
            row = db.get(GpxFile, goal_id)
            return row.data if row else None

    def save_gpx(self, db: DbSession, goal_id: int, data: bytes) -> None:
        """À appeler dans la transaction de l'objectif."""
        db.merge(GpxFile(goal_id=goal_id, data=data))

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

    def active_cycle(self) -> Cycle | None:
        with self._open() as db:
            stmt = select(Cycle).where(Cycle.status == "active").order_by(Cycle.id.desc())
            return db.exec(stmt).first()

    def upcoming_goals(self) -> list[Goal]:
        """Objectifs actifs, du plus proche au plus lointain."""
        stmt = select(Goal).where(Goal.status == "active").order_by(Goal.race_date, Goal.id)
        with self._open() as db:
            return list(db.exec(stmt))

    def past_goals(self) -> list[Goal]:
        """Objectifs courus (`done`), du plus récent au plus ancien."""
        stmt = select(Goal).where(Goal.status == "done").order_by(Goal.race_date.desc(), Goal.id.desc())
        with self._open() as db:
            return list(db.exec(stmt))

    def last_done_cycle(self, before: date) -> Cycle | None:
        """Dernier cycle terminé avant `before` (par date de fin) ; ignore les cycles clos d'avance,
        par exemple ceux créés à la migration pour un objectif retiré encore à venir."""
        stmt = (
            select(Cycle)
            .where(Cycle.status == "done", Cycle.end_date < before)
            .order_by(Cycle.end_date.desc(), Cycle.id.desc())
        )
        with self._open() as db:
            return db.exec(stmt).first()

    def goals_in(self, cycle: Cycle) -> list[Goal]:
        """Objectifs actifs dont la course tombe dans le cycle."""
        return [g for g in self.upcoming_goals() if cycle.plan_start <= g.race_date <= cycle.end_date]

    def horizon_goals(self, cycle: Cycle) -> list[Goal]:
        """Objectifs actifs au-delà de la fin du cycle."""
        return [g for g in self.upcoming_goals() if g.race_date > cycle.end_date]

    def race_strategy(self, goal_id: int) -> RaceStrategy | None:
        with self._open() as db:
            return db.exec(select(RaceStrategy).where(RaceStrategy.goal_id == goal_id)).first()

    def sessions(self, cycle_id: int, week_index: int | None = None) -> list[Session]:
        stmt = select(Session).where(Session.cycle_id == cycle_id)
        if week_index is not None:
            stmt = stmt.where(Session.week_index == week_index)
        stmt = stmt.order_by(Session.week_index, Session.order)
        with self._open() as db:
            return list(db.exec(stmt))

    def events(self, cycle_id: int) -> list[Event]:
        """Imprévus du cycle, le plus récent d'abord."""
        stmt = (
            select(Event)
            .where(Event.cycle_id == cycle_id)
            .order_by(Event.start_date.desc(), Event.id.desc())
        )
        with self._open() as db:
            return list(db.exec(stmt))

    def open_injury(self, cycle_id: int) -> Event | None:
        """Arrêt en cours (blessure sans date de fin), s'il y en a un."""
        stmt = (
            select(Event)
            .where(Event.cycle_id == cycle_id, Event.kind == "injury", Event.end_date == None)  # noqa: E711
            .order_by(Event.id.desc())
        )
        with self._open() as db:
            return db.exec(stmt).first()

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

    def activity_of_session(self, session_id: int) -> Activity | None:
        stmt = select(Activity).where(Activity.session_id == session_id)
        with self._open() as db:
            return db.exec(stmt).first()

    def laps(self, activity_id: int) -> list[LapSummary] | None:
        """Tours enregistrés de l'activité ; `None` s'ils n'ont jamais été récupérés."""
        stmt = select(ActivityLaps).where(ActivityLaps.activity_id == activity_id)
        with self._open() as db:
            row = db.exec(stmt).first()
        return None if row is None else _LAPS.validate_json(row.laps_json)

    def save_laps(self, activity_id: int, laps: list[LapSummary]) -> None:
        """Enregistre les tours (sans `raw`), en remplaçant ceux déjà présents."""
        payload = _LAPS.dump_json(laps, exclude={"__all__": {"raw"}}).decode()
        with self.transaction() as db:
            row = db.exec(select(ActivityLaps).where(ActivityLaps.activity_id == activity_id)).first()
            if row is None:
                row = ActivityLaps(activity_id=activity_id, laps_json=payload)
            else:
                row.laps_json = payload
                row.fetched_at = _now()
            db.add(row)

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
