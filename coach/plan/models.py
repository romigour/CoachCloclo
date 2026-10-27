"""Tables SQLModel de Coach (section 4 de la spec)."""

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


class Proposal(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    created_at: dt.datetime = Field(default_factory=_now)
    analysis: str
    changes_json: str = "[]"
    status: str = "pending"  # pending | accepted | rejected | stale
