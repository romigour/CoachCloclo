"""Dépôt SQLite : accès aux données du plan."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

from pydantic import TypeAdapter
from sqlalchemy import func, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import defer
from sqlalchemy.sql import Select
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
    LlmUsage,
    PersonalRecord,
    Proposal,
    Race,
    RaceStrategy,
    Session,
    _now,
)
from coach.storage.pages import is_remote, pages

_LAPS = TypeAdapter(list[LapSummary])

# Chaque changement de schéma futur doit incrémenter SCHEMA_VERSION.
SCHEMA_VERSION = 3  # 3 : provenance de la FC repos, zones FC à l'envoi


class SchemaTooNew(Exception):
    """La base a un schéma plus récent que cette version de l'app."""


def _prefetch(conn: Connection, *sqls: str) -> None:
    """Sur une base distante, envoie ces lectures ensemble ; leur `execute` consommera le résultat."""
    raw = conn.connection.driver_connection
    if hasattr(raw, "prefetch"):
        raw.prefetch(list(sqls))


_OBJECTS = "SELECT type, name FROM sqlite_master"
_VERSION = "SELECT value_json FROM appstate WHERE key = 'schema_version'"


def _read_schema(conn: Connection) -> tuple[set[str], set[str], int | None]:
    """Tables et index présents, et version de schéma inscrite (None : aucune)."""
    _prefetch(conn, _OBJECTS, _VERSION)
    found = conn.execute(text(_OBJECTS)).all()
    tables = {name for kind, name in found if kind == "table"}
    indexes = {name for kind, name in found if kind == "index"}
    # présence vérifiée plutôt qu'un except : le type d'erreur « table absente » varie selon le driver
    row = conn.execute(text(_VERSION)).first() if AppState.__tablename__ in tables else None
    return tables, indexes, json.loads(row[0])["v"] if row is not None else None


def _check_schema_version(engine: Engine) -> None:
    """Refuse une base plus récente (avant toute migration) ; sinon inscrit SCHEMA_VERSION.

    Fonctionne sur tout moteur (fichier local ou base distante) ; une base à jour n'est que lue.
    """
    with engine.connect() as conn:
        tables, indexes, found = _read_schema(conn)
    if found is not None and found > SCHEMA_VERSION:
        raise SchemaTooNew(f"schéma {found} > {SCHEMA_VERSION}")
    incomplete = [
        t
        for t in SQLModel.metadata.sorted_tables
        if t.name not in tables or not {i.name for i in t.indexes} <= indexes
    ]
    if incomplete:
        SQLModel.metadata.create_all(engine, tables=incomplete)
    _migrate(engine)
    if found != SCHEMA_VERSION:
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


_MIGRATED = ("goal", "session", "proposal", "cycle", "event", "athletesnapshot")


def _read_columns(conn: Connection) -> dict[str, set[str]]:
    """Colonnes des tables que `_migrate` peut modifier."""
    sqls = {table: f"PRAGMA table_info({table})" for table in _MIGRATED}
    _prefetch(conn, *sqls.values())
    return {table: {row[1] for row in conn.execute(text(sql))} for table, sql in sqls.items()}


def _migrate(engine: Engine) -> None:
    """Met à niveau une base existante, étape par étape (chacune idempotente)."""
    with engine.begin() as conn:
        existing = _read_columns(conn)

        def add_columns(table: str, columns: dict[str, str]) -> None:
            """Ajoute à `table` chaque colonne absente (DDL donné en valeur)."""
            for name, ddl in columns.items():
                if name not in existing[table]:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))

        if "target_time_s" not in existing["goal"]:
            # temps visé de `goal`, repris de la stratégie de course
            add_columns("goal", {"target_time_s": "INTEGER", "target_source": "VARCHAR"})
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
        add_columns(
            "goal",
            {
                "available_days_json": f"VARCHAR NOT NULL DEFAULT '{ALL_DAYS_JSON}'",
                "long_run_day": "VARCHAR",
            },
        )
        # sport des séances et option vélo de l'objectif
        add_columns("session", {"sport": "VARCHAR NOT NULL DEFAULT 'run'"})
        add_columns("goal", {"include_bike": "BOOLEAN NOT NULL DEFAULT 0"})
        # priorité des objectifs
        add_columns("goal", {"priority": "VARCHAR NOT NULL DEFAULT 'principal'"})
        # précisions de l'objectif
        add_columns("goal", {"notes": "VARCHAR"})
        # temps estimés portés par une proposition d'ajustement
        add_columns("proposal", {"estimates_json": "VARCHAR NOT NULL DEFAULT '[]'"})
        # changements d'objectif en attente de mise à jour de l'entraînement
        add_columns(
            "cycle",
            {"adjust_due": "BOOLEAN NOT NULL DEFAULT 0", "adjust_notes_json": "VARCHAR NOT NULL DEFAULT '[]'"},
        )
        # séances et imprévus rattachés à un cycle (l'id du cycle reprend celui de l'objectif)
        legacy = False
        for table in ("session", "event"):
            cols = existing[table]
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
        # provenance de la FC repos de l'instantané
        add_columns("athletesnapshot", {"hr_rest_source": "VARCHAR", "hr_rest_nights": "INTEGER"})
        # zones FC utilisées à l'envoi d'une séance à la montre
        add_columns("session", {"export_hr_zones_json": "VARCHAR"})


def active_cycle_stmt() -> Select:
    return select(Cycle).where(Cycle.status == "active").order_by(Cycle.id.desc()).limit(1)


def upcoming_goals_stmt() -> Select:
    """Objectifs actifs, du plus proche au plus lointain."""
    return select(Goal).where(Goal.status == "active").order_by(Goal.race_date, Goal.id)


def past_goals_stmt() -> Select:
    """Objectifs courus (`done`), du plus récent au plus ancien."""
    return select(Goal).where(Goal.status == "done").order_by(Goal.race_date.desc(), Goal.id.desc())


def recent_done_goals_stmt(today: date, days: int = 14) -> Select:
    """Objectifs courus (`done`) dans les `days` derniers jours, du plus ancien au plus récent."""
    return (
        select(Goal)
        .where(Goal.status == "done", Goal.race_date >= today - timedelta(days=days), Goal.race_date <= today)
        .order_by(Goal.race_date, Goal.id)
    )


def last_done_cycle_stmt(before: date) -> Select:
    """Dernier cycle terminé avant `before` (par date de fin)."""
    return (
        select(Cycle)
        .where(Cycle.status == "done", Cycle.end_date < before)
        .order_by(Cycle.end_date.desc(), Cycle.id.desc())
        .limit(1)
    )


def sessions_stmt(cycle_id: int, week_index: int | None = None) -> Select:
    stmt = select(Session).where(Session.cycle_id == cycle_id)
    if week_index is not None:
        stmt = stmt.where(Session.week_index == week_index)
    return stmt.order_by(Session.week_index, Session.order)


def open_injury_stmt(cycle_id: int) -> Select:
    """Arrêt en cours (blessure sans date de fin) du cycle."""
    return (
        select(Event)
        .where(Event.cycle_id == cycle_id, Event.kind == "injury", Event.end_date == None)  # noqa: E711
        .order_by(Event.id.desc())
        .limit(1)
    )


def pending_proposal_stmt() -> Select:
    return select(Proposal).where(Proposal.status == "pending").order_by(Proposal.id.desc()).limit(1)


def count_activities_stmt() -> Select:
    return select(func.count()).select_from(Activity)


def activities_between_stmt(start: date, end: date) -> Select:
    """Activités du `start` au `end` inclus, sans le JSON brut (lourd, inutile à l'affichage)."""
    return (
        select(Activity)
        .where(Activity.date >= start, Activity.date <= end)
        .order_by(Activity.date, Activity.id)
        .options(defer(Activity.raw_json))
    )


def week_session_activities_stmt(cycle_id: int, week_index: int) -> Select:
    """Activités rattachées à une séance de cette semaine du cycle, sans le JSON brut."""
    ids = select(Session.id).where(Session.cycle_id == cycle_id, Session.week_index == week_index)
    return select(Activity).where(Activity.session_id.in_(ids)).options(defer(Activity.raw_json))


def missing_laps_stmt() -> Select:
    """Activités rattachées à une séance et sans ligne de tours, sans le JSON brut."""
    fetched = select(ActivityLaps.activity_id)
    return (
        select(Activity)
        .where(Activity.session_id != None, Activity.id.not_in(fetched))  # noqa: E711
        .order_by(Activity.date, Activity.id)
        .options(defer(Activity.raw_json))
    )


def state_stmt(key: str) -> Select:
    return select(AppState).where(AppState.key == key)


class Repo:
    def __init__(self, engine: Engine):
        self.engine = engine

    def _open(self) -> DbSession:
        return DbSession(self.engine, expire_on_commit=False)

    def read_batch(self, *statements: Select) -> list[list]:
        """Exécute ces lectures ; rend pour chacune ses entités ou ses scalaires (une colonne), dans l'ordre.

        Sur une base distante, toutes partent en un seul envoi : chaque requête est compilée avec ses
        valeurs en clair (`literal_binds`), préchargée, puis exécutée avec le même texte, qui consomme
        le résultat préchargé. N'accepter que des valeurs produites par l'appli (entiers, dates,
        constantes), jamais une saisie brute. Sans préchargement (SQLite local), elles s'exécutent une à une.
        """
        with self._open() as db:
            raw = db.connection().connection.driver_connection
            if not hasattr(raw, "prefetch"):
                return [list(db.exec(stmt)) for stmt in statements]
            dialect = self.engine.dialect
            sqls = [str(stmt.compile(dialect=dialect, compile_kwargs={"literal_binds": True})) for stmt in statements]
            raw.prefetch(sqls)
            done: dict[str, list] = {}  # une requête répétée n'est exécutée qu'une fois
            results = []
            for stmt, sql in zip(statements, sqls, strict=True):
                if sql not in done:
                    query = text(sql.replace(":", "\\:"))  # `:` échappé : text() y verrait un paramètre
                    entity = stmt.column_descriptions[0]["entity"]
                    if entity is not None:
                        # les options (defer...) de la requête d'origine s'appliquent au résultat préchargé
                        shaped = select(entity).from_statement(query).options(*stmt._with_options)
                        done[sql] = list(db.execute(shaped).scalars())
                    else:
                        done[sql] = [row[0] for row in db.execute(query)]
                results.append(list(done[sql]))
            return results

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
            return db.exec(active_cycle_stmt()).first()

    def upcoming_goals(self) -> list[Goal]:
        """Objectifs actifs, du plus proche au plus lointain."""
        with self._open() as db:
            return list(db.exec(upcoming_goals_stmt()))

    def past_goals(self) -> list[Goal]:
        """Objectifs courus (`done`), du plus récent au plus ancien."""
        with self._open() as db:
            return list(db.exec(past_goals_stmt()))

    def recent_done_goals(self, today: date, days: int = 14) -> list[Goal]:
        """Objectifs courus (`done`) dans les `days` derniers jours, du plus ancien au plus récent :
        ils forment encore des blocs et des courses rapprochées avec les objectifs à venir."""
        with self._open() as db:
            return list(db.exec(recent_done_goals_stmt(today, days)))

    def last_done_cycle(self, before: date) -> Cycle | None:
        """Dernier cycle terminé avant `before` (par date de fin) ; ignore les cycles clos d'avance,
        par exemple ceux créés à la migration pour un objectif retiré encore à venir."""
        with self._open() as db:
            return db.exec(last_done_cycle_stmt(before)).first()

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
        with self._open() as db:
            return list(db.exec(sessions_stmt(cycle_id, week_index)))

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
        with self._open() as db:
            return db.exec(open_injury_stmt(cycle_id)).first()

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

    def activities_between(self, start: date, end: date) -> list[Activity]:
        """Activités du `start` au `end` inclus (sans `raw_json`)."""
        with self._open() as db:
            return list(db.exec(activities_between_stmt(start, end)))

    def activities_missing_laps(self) -> list[Activity]:
        """Activités rattachées à une séance dont les tours n'ont jamais été récupérés, en une requête."""
        with self._open() as db:
            return list(db.exec(missing_laps_stmt()))

    def activity_by_garmin_id(self, gid: int) -> Activity | None:
        stmt = select(Activity).where(Activity.garmin_activity_id == gid)
        with self._open() as db:
            return db.exec(stmt).first()

    def pending_proposal(self) -> Proposal | None:
        with self._open() as db:
            return db.exec(pending_proposal_stmt()).first()

    def latest_snapshot(self) -> AthleteSnapshot | None:
        stmt = select(AthleteSnapshot).order_by(AthleteSnapshot.date.desc(), AthleteSnapshot.id.desc())
        with self._open() as db:
            return db.exec(stmt).first()

    def latest_nights_snapshot(self) -> AthleteSnapshot | None:
        """Dernier instantané dont la FC repos vient de la moyenne des nuits portées."""
        stmt = (
            select(AthleteSnapshot)
            .where(AthleteSnapshot.hr_rest_source == "nights")
            .order_by(AthleteSnapshot.date.desc(), AthleteSnapshot.id.desc())
        )
        with self._open() as db:
            return db.exec(stmt).first()

    def latest_garmin_rest_snapshot(self) -> AthleteSnapshot | None:
        """Dernier instantané dont la FC repos vient de Garmin (provenance "garmin" ou inconnue)."""
        stmt = (
            select(AthleteSnapshot)
            .where((AthleteSnapshot.hr_rest_source == "garmin") | (AthleteSnapshot.hr_rest_source.is_(None)))
            .order_by(AthleteSnapshot.date.desc(), AthleteSnapshot.id.desc())
        )
        with self._open() as db:
            return db.exec(stmt).first()

    def all_activities(self, *, raw: bool = True) -> list[Activity]:
        """Toutes les activités, par date ; `raw=False` : sans le JSON brut (lourd)."""
        stmt = select(Activity).order_by(Activity.date, Activity.id)
        if not raw:
            stmt = stmt.options(defer(Activity.raw_json))
        with self._open() as db:
            if not (raw and is_remote(self.engine)):
                return list(db.exec(stmt))
            found: list[Activity] = []
            for page in pages(db.connection(), Activity.__table__):
                found += db.exec(select(Activity).where(page.where()))
            return sorted(found, key=lambda a: (a.date, a.id))

    def count_activities(self) -> int:
        with self._open() as db:
            return db.exec(count_activities_stmt()).one()

    def has_activities(self) -> bool:
        with self._open() as db:
            return db.exec(select(Activity.id).limit(1)).first() is not None

    def has_activity_on(self, day: date) -> bool:
        """Au moins une activité enregistrée ce jour-là."""
        with self._open() as db:
            return db.exec(select(Activity.id).where(Activity.date == day).limit(1)).first() is not None

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

    def activities_of_sessions(self, session_ids: list[int]) -> list[Activity]:
        """Activités rattachées à l'une des séances `session_ids`, en une seule requête."""
        if not session_ids:
            return []
        stmt = select(Activity).where(Activity.session_id.in_(session_ids))
        with self._open() as db:
            return list(db.exec(stmt))

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

    def llm_usages(self) -> list[LlmUsage]:
        """Consommation Claude, de la plus récente à la plus ancienne."""
        with self._open() as db:
            stmt = select(LlmUsage).order_by(LlmUsage.created_at.desc(), LlmUsage.id.desc())
            return list(db.exec(stmt).all())

    def records(self) -> list[PersonalRecord]:
        with self._open() as db:
            return list(db.exec(select(PersonalRecord).order_by(PersonalRecord.id)))

    def replace_records(self, records: list[PersonalRecord]) -> None:
        """Remplace tous les records en une transaction."""
        with self.transaction() as db:
            db.exec(delete(PersonalRecord))
            for r in records:
                db.add(r)
