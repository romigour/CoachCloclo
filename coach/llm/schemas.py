"""Schémas JSON stricts des réponses de Claude et validation métier."""

from collections import Counter
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, model_validator

from coach.analysis.zones import HrZoneName, PaceZoneName

SessionType = Literal["EF", "seuil", "VMA", "côtes", "sortie_longue", "récup"]
HARD_TYPES: frozenset[str] = frozenset({"seuil", "VMA", "côtes", "sortie_longue"})
Weekday = Literal["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]

_PACE_ZONES = frozenset(get_args(PaceZoneName))
_HR_ZONES = frozenset(get_args(HrZoneName))


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StepSpec(_Strict):
    kind: Literal["warmup", "active", "recovery", "cooldown"]
    duration_s: int | None = Field(default=None, gt=0)
    distance_m: int | None = Field(default=None, gt=0)
    zone: PaceZoneName | HrZoneName | None = None

    @model_validator(mode="after")
    def _exactly_one_length(self) -> "StepSpec":
        if (self.duration_s is None) == (self.distance_m is None):
            raise ValueError("une étape exige exactement une durée (duration_s) ou une distance (distance_m)")
        return self


class RepeatSpec(_Strict):
    repeat: int = Field(ge=2, le=30)
    steps: list[StepSpec] = Field(min_length=1)


class SessionSpec(_Strict):
    week_index: int = Field(ge=1)
    order: int = Field(ge=1)
    suggested_day: Weekday
    type: SessionType
    target_kind: Literal["pace", "hr"]
    title: str
    description: str
    chaining_note: str | None = None
    sport: Literal["run", "bike"] = "run"
    steps: list[StepSpec | RepeatSpec] = Field(min_length=1)

    def iter_steps(self):
        """Toutes les étapes à plat (répétitions dépliées d'un niveau)."""
        for s in self.steps:
            if isinstance(s, RepeatSpec):
                yield from s.steps
            else:
                yield s

    @model_validator(mode="after")
    def _zones_match_target(self) -> "SessionSpec":
        allowed = _PACE_ZONES if self.target_kind == "pace" else _HR_ZONES
        for step in self.iter_steps():
            if step.zone is not None and step.zone not in allowed:
                raise ValueError(
                    f"zone « {step.zone} » incompatible avec la cible « {self.target_kind} »"
                )
        return self


class WeekSpec(_Strict):
    week_index: int
    focus: str
    sessions: list[SessionSpec]


class PlanResponse(_Strict):
    summary: str
    estimated_time_s: int | None = None
    weeks: list[WeekSpec]


class Change(_Strict):
    op: Literal["modify", "add", "remove"]
    session_id: int | None = None
    session: SessionSpec | None = None
    reason: str

    @model_validator(mode="after")
    def _shape_matches_op(self) -> "Change":
        has_id, has_session = self.session_id is not None, self.session is not None
        expected = {"modify": (True, True), "add": (False, True), "remove": (True, False)}[self.op]
        if (has_id, has_session) != expected:
            raise ValueError(f"changement « {self.op} » : combinaison session_id/session invalide")
        return self


class AdjustmentResponse(_Strict):
    analysis: str
    changes: list[Change]


def _uses_pace(session: SessionSpec) -> bool:
    return session.target_kind == "pace"


def validate_plan(
    plan: PlanResponse,
    *,
    n_weeks: int,
    sessions_per_week: int,
    pace_available: bool,
    estimate_min_s: int | None = None,
) -> list[str]:
    """Contrôle métier d'un plan complet ; retourne la liste des erreurs (vide si valide).

    `estimate_min_s` non None : le plan doit porter une estimation `estimated_time_s` ≥ cette valeur.
    """
    errors: list[str] = []
    if estimate_min_s is not None:
        if plan.estimated_time_s is None:
            errors.append("estimated_time_s est obligatoire : estime un temps réaliste en secondes")
        elif plan.estimated_time_s < estimate_min_s:
            errors.append(
                f"estimated_time_s ({plan.estimated_time_s} s) invraisemblable : "
                f"au moins {estimate_min_s} s attendues"
            )
    indexes = [w.week_index for w in plan.weeks]
    if indexes != list(range(1, n_weeks + 1)):
        errors.append(f"les semaines doivent être numérotées de 1 à {n_weeks} sans trou (reçu : {indexes})")
    for week in plan.weeks:
        n = len(week.sessions)
        if n > sessions_per_week:
            errors.append(f"semaine {week.week_index} : {n} séances pour {sessions_per_week} demandées")
        orders = [s.order for s in week.sessions]
        if len(set(orders)) != len(orders):
            errors.append(f"semaine {week.week_index} : numéros d'ordre en double")
        if any(s.week_index != week.week_index for s in week.sessions):
            errors.append(f"semaine {week.week_index} : chaque séance doit porter le week_index de sa semaine")
        if not pace_available and any(_uses_pace(s) for s in week.sessions):
            errors.append(f"semaine {week.week_index} : cible d'allure impossible sans données d'allure")
    return errors


def validate_adjustment(
    adj: AdjustmentResponse,
    *,
    editable_ids: set[int],
    current_week: int,
    n_weeks: int,
    sessions_per_week: int,
    counts_by_week: dict[int, int],
    pace_available: bool,
    week_of_session: dict[int, int] | None = None,
    exported_ids: set[int] | None = None,
) -> list[str]:
    """Contrôle métier d'un ajustement ; retourne la liste des erreurs (vide si valide).

    `counts_by_week` : nombre de séances actuelles par semaine (tous statuts), avant changements.
    `week_of_session` (session_id -> week_index) permet de décompter un `remove` ou un `modify`
    qui change de semaine ; s'il est absent (None) ou ne connaît pas la séance, le retrait
    n'est pas décompté.
    `exported_ids` : séances exportées, qui ne peuvent pas changer de semaine (date Garmin fixée).
    """
    errors: list[str] = []
    counts: Counter[int] = Counter(counts_by_week)
    known = week_of_session or {}
    ids = [ch.session_id for ch in adj.changes if ch.session_id is not None]
    for sid in sorted({i for i in ids if ids.count(i) > 1}):
        errors.append(f"la séance {sid} apparaît dans plusieurs changements")
    for i, ch in enumerate(adj.changes, start=1):
        label = f"changement {i} ({ch.op})"
        if ch.session_id is not None and ch.session_id not in editable_ids:
            errors.append(f"{label} : la séance {ch.session_id} n'est pas modifiable")
        if ch.session is not None:
            if not pace_available and _uses_pace(ch.session):
                errors.append(f"{label} : cible d'allure impossible sans données d'allure")
            if ch.session.week_index > n_weeks:
                errors.append(
                    f"{label} : semaine {ch.session.week_index}, au-delà de la dernière semaine du plan ({n_weeks})"
                )
            if ch.session.week_index < current_week:
                errors.append(
                    f"{label} : semaine {ch.session.week_index}, avant la semaine courante {current_week}"
                )
        old_week = known.get(ch.session_id) if ch.session_id is not None else None
        if (
            ch.op == "modify"
            and ch.session_id in (exported_ids or set())
            and old_week is not None
            and ch.session.week_index != old_week
        ):
            errors.append(f"{label} : la séance {ch.session_id} est exportée, elle ne peut pas changer de semaine")
        if ch.op == "add":
            counts[ch.session.week_index] += 1
        elif old_week is not None:  # remove / modify : décompté seulement si la semaine d'origine est connue
            counts[old_week] -= 1
            if ch.op == "modify":
                counts[ch.session.week_index] += 1
    for week in sorted(counts):
        if counts[week] > sessions_per_week:
            errors.append(f"semaine {week} : {counts[week]} séances pour {sessions_per_week} demandées")
    return errors
