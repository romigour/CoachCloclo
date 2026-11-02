"""Tables SQLModel de CoachCloclo (section 4 de la spec)."""

import datetime as dt

from pydantic import TypeAdapter
from sqlmodel import Field, SQLModel

from coach.llm.schemas import RepeatSpec, SessionSpec, StepSpec



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
    status: str = "active"  # "active" | "archived"
    plan_start: dt.date
    plan_accepted: bool = False
    target_time_s: int | None = None
    target_source: str | None = None  # "user" | "claude"


class Session(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    goal_id: int = Field(index=True)
    week_index: int
    order: int
    suggested_day: str
    chaining_note: str | None = None
    type: str
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
            steps=_STEPS.validate_json(self.steps_json),
        )

    @classmethod
    def from_spec(cls, spec: SessionSpec, goal_id: int) -> "Session":
        return cls(
            goal_id=goal_id,
            week_index=spec.week_index,
            order=spec.order,
            suggested_day=spec.suggested_day,
            chaining_note=spec.chaining_note,
            type=spec.type,
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
    status: str = "pending"  # pending | accepted | rejected | stale


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
