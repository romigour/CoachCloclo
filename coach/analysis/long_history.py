"""Historique long pour Claude : volume mensuel, compétitions passées et records, sans accès à la base."""

import datetime as dt
from dataclasses import dataclass

from coach.plan.models import Activity, PersonalRecord, Race
from coach.stats.normalize import sport_family

MONTHS = 12
MAX_RACES = 15
RECORD_KINDS = ("5k", "10k", "half", "marathon", "longest_run")
_RUN_FAMILIES = ("run", "trail")


@dataclass(frozen=True)
class MonthVolume:
    month: dt.date  # 1er du mois
    runs: int = 0
    run_km: float = 0.0
    run_s: float = 0
    d_plus_m: float = 0
    longest_km: float = 0.0
    other_s: float = 0


@dataclass(frozen=True)
class PastRace:
    date: dt.date
    name: str | None
    distance_km: float | None
    d_plus_m: float | None
    time_s: float | None
    overall_rank: int | None
    overall_total: int | None


@dataclass(frozen=True)
class LongHistory:
    months: list[MonthVolume]
    races: list[PastRace]
    records: list[PersonalRecord]


def _shift(month: dt.date, n: int) -> dt.date:
    """1er du mois situé `n` mois avant `month`."""
    y, m = divmod(month.year * 12 + month.month - 1 - n, 12)
    return dt.date(y, m + 1, 1)


def window_start(today: dt.date, months: int = MONTHS) -> dt.date:
    """Premier jour de la fenêtre : 1er du mois de `today` moins `months - 1` mois."""
    return _shift(today.replace(day=1), months - 1)


def monthly_volume(activities: list[Activity], today: dt.date, months: int = MONTHS) -> list[MonthVolume]:
    """`months` mois, le plus récent d'abord (mois de `today` compris), mois vides compris."""
    current = today.replace(day=1)
    keys = [_shift(current, i) for i in range(months)]
    acc = {k: {"runs": 0, "run_km": 0.0, "run_s": 0, "d_plus_m": 0, "longest_km": 0.0, "other_s": 0} for k in keys}
    start = keys[-1]
    for a in activities:
        if not start <= a.date <= today:
            continue
        m = acc[a.date.replace(day=1)]
        duration = a.duration_s or 0
        if sport_family(a.type_key) in _RUN_FAMILIES:
            km = (a.distance_m or 0) / 1000
            m["runs"] += 1
            m["run_km"] += km
            m["run_s"] += duration
            m["d_plus_m"] += a.d_plus_m or 0
            m["longest_km"] = max(m["longest_km"], km)
        else:
            m["other_s"] += duration
    return [MonthVolume(month=k, **acc[k]) for k in keys]


def past_races(races: list[Race], activities: dict[int, Activity], limit: int = MAX_RACES) -> list[PastRace]:
    """Compétitions saisies (hors exclues et sans activité connue), les plus récentes d'abord.

    `activities` : activités indexées par `Activity.id`.
    """
    out = []
    for r in races:
        a = activities.get(r.activity_id)
        if r.excluded or a is None:
            continue
        out.append(
            PastRace(
                date=a.date,
                name=r.name,
                distance_km=a.distance_m / 1000 if a.distance_m else None,
                d_plus_m=a.d_plus_m,
                time_s=r.official_time_s if r.official_time_s is not None else a.duration_s,
                overall_rank=r.overall_rank,
                overall_total=r.overall_total,
            )
        )
    out.sort(key=lambda p: p.date, reverse=True)
    return out[:limit]


def kept_records(records: list[PersonalRecord]) -> list[PersonalRecord]:
    """Records utiles à Claude, dans l'ordre de `RECORD_KINDS` ; valeurs non positives ignorées."""
    by_kind = {r.kind: r for r in records if r.value > 0}
    return [by_kind[k] for k in RECORD_KINDS if k in by_kind]
