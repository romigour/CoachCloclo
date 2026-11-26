"""Tables SQLModel de CoachCloclo (section 4 de la spec)."""

import datetime as dt
import json

from pydantic import TypeAdapter
from sqlmodel import Field, SQLModel

from coach.llm.schemas import RepeatSpec, SessionSpec, StepSpec

# Jours de la semaine, dans l'ordre de coach.plan.calendar._WEEKDAYS (défini ici : calendar importe models).
ALL_DAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
ALL_DAYS_JSON = json.dumps(list(ALL_DAYS))

# Priorité d'un objectif : détermine la place qu'il prend dans le plan
PRIORITIES = ("principal", "secondaire", "plaisir")
PRIORITY_LABELS = {"principal": "Principal", "secondaire": "Secondaire", "plaisir": "Plaisir"}


def _now() -> dt.datetime:
    """Horodatage UTC (colonnes datetime SQLModel : fuseau obligatoire)."""
    return dt.datetime.now(dt.timezone.utc)


_STEPS = TypeAdapter(list[StepSpec | RepeatSpec])


class AthleteSnapshot(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    date: dt.date
    vo2max: float | None = None
    hr_max: int | None = None
    hr_rest: int | None = None
    threshold_hr: int | None = None
    threshold_pace_s_km: float | None = None
    zones_json: str = "{}"
    hr_rest_source: str | None = None  # "manual" | "nights" | "last_good" | "garmin" ; None : instantané d'avant
    hr_rest_nights: int | None = None  # nuits portées de la moyenne (source "nights")


class Goal(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    created_at: dt.datetime = Field(default_factory=_now)
    type: str  # "route" | "trail"
    distance_km: float
    d_plus_m: int = 0
    race_date: dt.date
    sessions_per_week: int
    gpx_path: str | None = None
    gpx_summary_json: str | None = None
    status: str = "active"  # "active" | "done" | "archived"
    plan_start: dt.date
    plan_accepted: bool = False
    target_time_s: int | None = None
    target_source: str | None = None  # "user" | "claude"
    available_days_json: str = ALL_DAYS_JSON
    long_run_day: str | None = None
    include_bike: bool = False
    priority: str = "principal"  # "principal" | "secondaire" | "plaisir"
    notes: str | None = None  # précisions de l'athlète, transmises à Claude
    # Les champs de plan ci-dessus (plan_start, sessions_per_week, plan_accepted, available_days_json,
    # long_run_day, include_bike) sont écrits à la création (copie du cycle) mais plus lus : la source est `Cycle`.

    def available_days(self) -> list[str]:
        return json.loads(self.available_days_json)


class Cycle(SQLModel, table=True):
    """Plan d'entraînement : un cycle couvre un ou plusieurs objectifs, de `plan_start` à `end_date`."""

    id: int | None = Field(default=None, primary_key=True)
    created_at: dt.datetime = Field(default_factory=_now)
    status: str = "active"  # "active" | "done"
    plan_start: dt.date
    end_date: dt.date
    sessions_per_week: int
    available_days_json: str = ALL_DAYS_JSON
    long_run_day: str | None = None
    include_bike: bool = False
    plan_accepted: bool = False
    needs_generation: bool = False
    recovery_from_goal_id: int | None = None
    # objectifs changés : mise à jour de l'entraînement à lancer, avec les changements à transmettre à Claude
    # (défaut côté base : les insertions SQL brutes, comme la migration d'avant les cycles, les omettent)
    adjust_due: bool = Field(default=False, sa_column_kwargs={"server_default": "0"})
    adjust_notes_json: str = Field(default="[]", sa_column_kwargs={"server_default": "[]"})

    def available_days(self) -> list[str]:
        return json.loads(self.available_days_json)

    def adjust_notes(self) -> list[str]:
        return json.loads(self.adjust_notes_json)


def add_adjust_note(c: Cycle, note: str) -> None:
    """Ajoute un changement d'objectif en attente et marque le cycle à mettre à jour (l'appelant enregistre)."""
    c.adjust_notes_json = json.dumps([*c.adjust_notes(), note], ensure_ascii=False)
    c.adjust_due = True


def consume_adjust_notes(c: Cycle, sent: list[str]) -> None:
    """Retire les notes transmises à Claude (`sent`, en tête de liste) ; celles ajoutées depuis restent en
    attente, et le cycle reste à mettre à jour."""
    notes = c.adjust_notes()
    rest = notes[len(sent):] if notes[: len(sent)] == sent else notes
    c.adjust_notes_json = json.dumps(rest, ensure_ascii=False)
    c.adjust_due = bool(rest)


def clear_adjust(c: Cycle) -> None:
    """Plus rien en attente : les changements ont été transmis à Claude (ou le plan est régénéré)."""
    c.adjust_due = False
    c.adjust_notes_json = "[]"


class Session(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    cycle_id: int = Field(index=True)
    week_index: int
    order: int
    suggested_day: str
    chaining_note: str | None = None
    type: str
    sport: str = "run"  # "run" | "bike"
    d_plus_m: int | None = None  # D+ prévu par Claude
    target_kind: str  # "pace" | "hr"
    title: str
    description: str
    steps_json: str
    est_duration_min: float | None = None
    est_distance_km: float | None = None
    status: str = "todo"  # todo | exported | done | missed | sync_error
    scheduled_date: dt.date | None = None
    garmin_workout_id: int | None = None
    garmin_schedule_id: int | None = None
    sync_error: str | None = None
    # Anciens ids Garmin à nettoyer (remplacement ou retrait d'une séance exportée)
    pending_old_workout_id: int | None = None
    pending_old_schedule_id: int | None = None
    pending_removal: bool = False  # supprimer la ligne une fois Garmin nettoyé
    export_hr_zones_json: str | None = None  # zones FC utilisées au dernier envoi à la montre

    def to_spec(self) -> SessionSpec:
        return SessionSpec(
            week_index=self.week_index,
            order=self.order,
            suggested_day=self.suggested_day,
            type=self.type,
            target_kind=self.target_kind,
            title=self.title,
            description=self.description,
            chaining_note=self.chaining_note,
            sport=self.sport,
            d_plus_m=self.d_plus_m,
            steps=_STEPS.validate_json(self.steps_json),
        )

    @classmethod
    def from_spec(cls, spec: SessionSpec, cycle_id: int) -> "Session":
        return cls(
            cycle_id=cycle_id,
            week_index=spec.week_index,
            order=spec.order,
            suggested_day=spec.suggested_day,
            chaining_note=spec.chaining_note,
            type=spec.type,
            sport=spec.sport,
            d_plus_m=spec.d_plus_m,
            target_kind=spec.target_kind,
            title=spec.title,
            description=spec.description,
            steps_json=_STEPS.dump_json(spec.steps).decode(),
        )


class Activity(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    garmin_activity_id: int = Field(unique=True, index=True)
    date: dt.date = Field(index=True)
    type_key: str
    duration_s: float | None = None
    distance_m: float | None = None
    d_plus_m: float | None = None
    avg_hr: float | None = None
    avg_pace_s_km: float | None = None
    raw_json: str = "{}"
    session_id: int | None = None
    match_source: str | None = None  # "auto" | "manual"


class ActivityLaps(SQLModel, table=True):
    """Tours Garmin d'une activité (sans `raw`), récupérés une fois puis mis en cache."""

    id: int | None = Field(default=None, primary_key=True)
    activity_id: int = Field(unique=True, index=True)
    laps_json: str
    fetched_at: dt.datetime = Field(default_factory=_now)


class Proposal(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    created_at: dt.datetime = Field(default_factory=_now)
    analysis: str
    changes_json: str = "[]"
    estimates_json: str = "[]"  # [{goal_id, seconds}] : temps estimés, appliqués à l'acceptation
    status: str = "pending"  # pending | accepted | rejected | stale


class Event(SQLModel, table=True):
    """Imprévu déclaré par l'athlète (spec 3.2) : indisponibilité, blessure, semaine allégée, fatigue."""

    id: int | None = Field(default=None, primary_key=True)
    cycle_id: int = Field(index=True)
    created_at: dt.datetime = Field(default_factory=_now)
    kind: str  # "unavailable" | "injury" | "light_week" | "fatigue"
    start_date: dt.date
    end_date: dt.date | None = None  # None seulement pour un arrêt (injury) en cours
    max_sessions: int | None = None  # light_week seulement
    days_json: str | None = None  # light_week seulement : jours possibles cette semaine-là
    session_id: int | None = None  # fatigue seulement : séance ratée
    note: str | None = None

    def days(self) -> list[str] | None:
        return None if self.days_json is None else json.loads(self.days_json)


class Race(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    activity_id: int = Field(unique=True, index=True)
    name: str | None = None
    official_time_s: int | None = None
    overall_rank: int | None = None
    overall_total: int | None = None
    category: str | None = None
    category_rank: int | None = None
    category_total: int | None = None
    excluded: bool = False


class PersonalRecord(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    kind: str
    value: float
    garmin_activity_id: int | None = None
    date: dt.date | None = None


class RaceStrategy(SQLModel, table=True):
    """Stratégie du jour J d'un objectif : réglages, base de calcul et export Garmin."""

    id: int | None = Field(default=None, primary_key=True)
    goal_id: int = Field(unique=True, index=True)
    settings_json: str  # RaceSettings sérialisé (temps visé, départ, nutrition, ravitos)
    basis_json: str  # RaceBasis sérialisé (prédictions, allure seuil, zones FC, date de capture)
    garmin_workout_id: int | None = None
    garmin_schedule_id: int | None = None
    # Anciens ids Garmin à supprimer au prochain export
    pending_old_workout_id: int | None = None
    pending_old_schedule_id: int | None = None
    export_error: str | None = None
    # Empreinte (settings_json + basis_json) du plan au dernier export réussi
    exported_hash: str | None = None
    # Copie de la vue Jour J (JSON sans sa date) pour le mobile, qui lit la base sans Python
    view_json: str | None = None
    view_updated_at: dt.datetime | None = None
    # Conseil du coach : JSON, date, et empreinte des données sur lesquelles il a été écrit
    advice_json: str | None = None
    advice_at: dt.datetime | None = None
    advice_hash: str | None = None


class AppState(SQLModel, table=True):
    """Paires clé/valeur JSON (version de schéma, historique, synchro, marqueur de copie)."""

    key: str = Field(primary_key=True)
    value_json: str


class GpxFile(SQLModel, table=True):
    """Fichier GPX d'un objectif."""

    goal_id: int = Field(primary_key=True)
    data: bytes


class GarminLock(SQLModel, table=True):
    """Verrou de synchronisation Garmin entre plusieurs PC (une seule ligne, id = 1)."""

    id: int = Field(default=1, primary_key=True)
    holder: str
    expires_at: dt.datetime


class LlmUsage(SQLModel, table=True):
    """Consommation d'une action Claude (génération de plan ou ajustement), essais cumulés."""

    id: int | None = Field(default=None, primary_key=True)
    created_at: dt.datetime = Field(default_factory=_now, index=True)
    kind: str  # generation | adjustment
    mode: str | None = None  # cli | api
    model: str | None = None
    attempts: int
    input_tokens: int
    output_tokens: int
    cost_usd: float | None = None  # estimation équivalent API ; None si tarif inconnu
    duration_ms: int
    status: str  # ok | failed
