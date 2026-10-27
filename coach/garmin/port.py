"""Port Garmin : erreurs, modèles, Protocol et fake en mémoire pour les tests."""

from __future__ import annotations

import itertools
from datetime import date
from typing import Protocol

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


class GarminPort(Protocol):
    def today(self) -> date: ...
    def metrics(self) -> Metrics: ...
    def activities(self, start: date, end: date) -> list[ActivitySummary]: ...
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
        fail_on: set[str] | None = None,
    ):
        self._metrics = metrics or Metrics()
        self._activities = list(activities or [])
        self._today = today
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
