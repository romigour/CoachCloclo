"""Port Garmin : erreurs, modèles, Protocol et fake en mémoire pour les tests."""

from __future__ import annotations

import itertools
import datetime as dt
from datetime import date
from typing import Literal, Protocol

from pydantic import BaseModel


class GarminAuthRequired(Exception):
    """Authentification Garmin absente ou expirée : reconnexion nécessaire."""


class GarminRateLimited(Exception):
    """Garmin limite les requêtes (429), même après une nouvelle tentative."""


class GarminUnavailable(Exception):
    """Garmin est injoignable ou a répondu par une erreur."""


class Metrics(BaseModel):
    vo2max: float | None = None
    hr_max: int | None = None
    hr_rest: int | None = None
    threshold_hr: int | None = None
    threshold_pace_s_km: int | None = None
    pred_10k_s: int | None = None
    hr_zones: list[int] | None = None


class ActivitySummary(BaseModel):
    garmin_id: int
    date: date
    type_key: str
    duration_s: int
    distance_m: int
    d_plus_m: int | None = None
    avg_hr: int | None = None
    raw: dict


class PersonalRecordSummary(BaseModel):
    kind: Literal["1k", "1mile", "5k", "10k", "half", "marathon", "longest_run"]
    value: float  # secondes, ou mètres pour `longest_run`
    garmin_activity_id: int | None = None
    date: dt.date | None = None


class LapSummary(BaseModel):
    index: int
    duration_s: float
    distance_m: float
    avg_hr: int | None = None
    max_hr: int | None = None
    avg_pace_s_km: float | None = None
    step_order: int | None = None  # stepOrder Garmin de l'étape exécutée, None hors workout
    raw: dict = {}


class GarminPort(Protocol):
    def today(self) -> date: ...
    def metrics(self) -> Metrics: ...
    def activities(self, start: date, end: date) -> list[ActivitySummary]: ...
    def activities_page(self, offset: int, limit: int) -> list[ActivitySummary]: ...
    def personal_records(self) -> list[PersonalRecordSummary]: ...
    def activity_laps(self, garmin_id: int) -> list[LapSummary]: ...
    def upload_workout(self, workout: dict) -> int: ...
    def schedule(self, workout_id: int, d: date) -> int: ...
    def reschedule(self, schedule_id: int, d: date) -> None: ...
    def unschedule(self, schedule_id: int) -> None: ...
    def delete_workout(self, workout_id: int) -> None: ...


class FakeGarminClient:
    """Garmin en mémoire. `calls` ne contient que les écritures réussies."""

    def __init__(
        self,
        metrics: Metrics | None = None,
        activities: list[ActivitySummary] | None = None,
        today: date = date(2026, 11, 4),
        personal_records: list[PersonalRecordSummary] | None = None,
        fail_on: set[str] | None = None,
        laps: dict[int, list[LapSummary]] | None = None,
    ):
        self._metrics = metrics or Metrics()
        self._activities = list(activities or [])
        self._today = today
        self._personal_records = list(personal_records or [])
        self._laps = dict(laps or {})
        self.fail_on: set[str] = set(fail_on or ())
        self.workouts: dict[int, dict] = {}
        self.calendar: dict[date, list[int]] = {}  # jour -> ids planifiés
        self.schedules: dict[int, tuple[int, date]] = {}  # id planifié -> (workout, jour)
        self.calls: list[str] = []
        self._workout_ids = itertools.count(1000)
        self._schedule_ids = itertools.count(5000)

    def _check(self, name: str, write: bool = False) -> None:
        if name in self.fail_on:
            raise GarminUnavailable(f"Garmin indisponible ({name}, simulé)")
        if write:
            self.calls.append(name)

    def today(self) -> date:
        return self._today

    def metrics(self) -> Metrics:
        self._check("metrics")
        return self._metrics

    def activities(self, start: date, end: date) -> list[ActivitySummary]:
        self._check("activities")
        return [a for a in self._activities if start <= a.date <= end]

    def activities_page(self, offset: int, limit: int) -> list[ActivitySummary]:
        self._check("activities_page")
        ordered = sorted(self._activities, key=lambda a: (a.date, a.garmin_id), reverse=True)
        return ordered[offset : offset + limit]

    def personal_records(self) -> list[PersonalRecordSummary]:
        self._check("personal_records")
        return list(self._personal_records)

    def activity_laps(self, garmin_id: int) -> list[LapSummary]:
        self._check("activity_laps")
        return list(self._laps.get(garmin_id, []))

    def upload_workout(self, workout: dict) -> int:
        self._check("upload_workout", write=True)
        wid = next(self._workout_ids)
        self.workouts[wid] = workout
        return wid

    def schedule(self, workout_id: int, d: date) -> int:
        self._check("schedule", write=True)
        if workout_id not in self.workouts:
            raise GarminUnavailable(f"Séance Garmin {workout_id} introuvable")
        sid = next(self._schedule_ids)
        self.schedules[sid] = (workout_id, d)
        self.calendar.setdefault(d, []).append(sid)
        return sid

    def _detach(self, schedule_id: int) -> int:
        workout_id, d = self.schedules.pop(schedule_id)
        self.calendar[d].remove(schedule_id)
        if not self.calendar[d]:
            del self.calendar[d]
        return workout_id

    def reschedule(self, schedule_id: int, d: date) -> None:
        self._check("reschedule", write=True)
        if schedule_id not in self.schedules:
            raise GarminUnavailable(f"Planification {schedule_id} introuvable")
        workout_id = self._detach(schedule_id)
        self.schedules[schedule_id] = (workout_id, d)
        self.calendar.setdefault(d, []).append(schedule_id)

    def unschedule(self, schedule_id: int) -> None:
        self._check("unschedule", write=True)
        if schedule_id in self.schedules:
            self._detach(schedule_id)

    def delete_workout(self, workout_id: int) -> None:
        self._check("delete_workout", write=True)
        self.workouts.pop(workout_id, None)
