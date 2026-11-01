"""Rapprochement des tours d'une activité Garmin avec les étapes prévues d'une séance."""

from typing import Literal, get_args

from pydantic import BaseModel

from coach.analysis.zones import PaceZoneName, Zones
from coach.export.garmin_workout import FlatStep, flat_steps
from coach.garmin.port import LapSummary
from coach.llm.schemas import SessionSpec

_PACE_ZONES = frozenset(get_args(PaceZoneName))

Verdict = Literal["in", "fast", "slow", "hr_high", "hr_low"]


class StepResult(BaseModel):
    group: int
    iteration: int | None
    position: int
    kind: str  # warmup | active | recovery | cooldown
    planned_duration_s: int | None
    planned_distance_m: int | None
    zone: str | None
    target_low: float | None  # s/km ou bpm selon la zone
    target_high: float | None
    done: bool
    duration_s: float | None
    distance_m: float | None
    avg_pace_s_km: float | None
    avg_hr: int | None
    verdict: Verdict | None


class StepComparison(BaseModel):
    followed_workout: bool
    target_kind: str  # "pace" | "hr"
    steps: list[StepResult]  # vide en mode dégradé
    laps: list[LapSummary]  # tours bruts (sans `raw`), toujours fournis


def _group_laps(plan: list[FlatStep], laps: list[LapSummary]) -> list[list[LapSummary]] | None:
    """Affecte chaque tour à une étape prévue ; None si la structure est incohérente."""
    if not laps or any(lap.step_order is None for lap in laps):
        return None
    if {lap.step_order for lap in laps} - {f.step_order for f in plan}:
        return None
    groups: list[list[LapSummary]] = [[] for _ in plan]
    i = -1
    for lap in laps:
        suivant = plan[i + 1].step_order if i + 1 < len(plan) else None
        if i >= 0 and plan[i].step_order == lap.step_order and suivant != lap.step_order:
            groups[i].append(lap)  # appui manuel dans la même étape : fusion
            continue
        j = next((k for k in range(i + 1, len(plan)) if plan[k].step_order == lap.step_order), None)
        if j is None:
            return None  # retour en arrière
        i = j
        groups[i].append(lap)
    return groups


def _verdict(
    zone: str | None, zones: Zones | None, pace: float | None, hr: int | None
) -> tuple[float | None, float | None, Verdict | None]:
    """Bornes de la zone et verdict (bornes inclusives, sans tolérance)."""
    if zone is None or zones is None:
        return None, None, None
    if zone in _PACE_ZONES:
        if zones.pace is None:
            return None, None, None
        fast, slow = zones.pace[zone]
        if pace is None:
            return fast, slow, None
        return fast, slow, "fast" if pace < fast else "slow" if pace > slow else "in"
    low, high = zones.hr[zone]
    if hr is None:
        return low, high, None
    return low, high, "hr_low" if hr < low else "hr_high" if hr > high else "in"


def _result(flat: FlatStep, group: list[LapSummary], zones: Zones | None) -> StepResult:
    step = flat.step
    base = dict(
        group=flat.group,
        iteration=flat.iteration,
        position=flat.position,
        kind=step.kind,
        planned_duration_s=step.duration_s,
        planned_distance_m=step.distance_m,
        zone=step.zone,
    )
    if not group:
        low, high, _ = _verdict(step.zone, zones, None, None)
        return StepResult(
            **base,
            target_low=low,
            target_high=high,
            done=False,
            duration_s=None,
            distance_m=None,
            avg_pace_s_km=None,
            avg_hr=None,
            verdict=None,
        )
    duration = sum(lap.duration_s for lap in group)
    distance = sum(lap.distance_m for lap in group)
    pace = duration / (distance / 1000) if distance > 0 else None
    with_hr = [lap for lap in group if lap.avg_hr is not None]
    weight = sum(lap.duration_s for lap in with_hr)
    if with_hr and weight > 0:
        hr = round(sum(lap.avg_hr * lap.duration_s for lap in with_hr) / weight)
    elif with_hr:
        hr = round(sum(lap.avg_hr for lap in with_hr) / len(with_hr))
    else:
        hr = None
    low, high, verdict = _verdict(step.zone, zones, pace, hr)
    return StepResult(
        **base,
        target_low=low,
        target_high=high,
        done=True,
        duration_s=duration,
        distance_m=distance,
        avg_pace_s_km=pace,
        avg_hr=hr,
        verdict=verdict,
    )


def compare_session(spec: SessionSpec, laps: list[LapSummary], zones: Zones | None) -> StepComparison:
    """Rapproche les tours des étapes prévues ; mode dégradé si le rapprochement est impossible."""
    bruts = [lap.model_copy(update={"raw": {}}) for lap in laps]
    plan = flat_steps(spec)
    groups = _group_laps(plan, laps)
    if groups is None:
        return StepComparison(followed_workout=False, target_kind=spec.target_kind, steps=[], laps=bruts)
    steps = [_result(flat, group, zones) for flat, group in zip(plan, groups)]
    return StepComparison(followed_workout=True, target_kind=spec.target_kind, steps=steps, laps=bruts)
