"""Schémas JSON stricts des réponses de Claude et validation métier."""

import re
from collections import Counter
from collections.abc import Mapping
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
    d_plus_m: int | None = Field(default=None, ge=0)  # D+ total prévu, None sans dénivelé
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


class GoalEstimate(_Strict):
    """Temps estimé par Claude pour un objectif (secondes)."""

    goal_id: int
    seconds: int


class PlanResponse(_Strict):
    summary: str
    estimated_times: list[GoalEstimate] = []
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
    estimated_times: list[GoalEstimate] = []


def _uses_pace(session: SessionSpec) -> bool:
    return session.target_kind == "pace"


def estimate_errors(estimates: list[GoalEstimate], estimate_min_s: Mapping[int, int] | None) -> list[str]:
    """Une estimation par objectif attendu (`goal_id` -> plancher en secondes), au moins égale au plancher."""
    given = {e.goal_id: e.seconds for e in estimates}
    errors: list[str] = []
    for goal_id, floor in (estimate_min_s or {}).items():
        seconds = given.get(goal_id)
        if seconds is None:
            errors.append(f"estimated_times : estimation manquante pour l'objectif {goal_id}")
        elif seconds < floor:
            errors.append(
                f"estimated_times : {seconds} s invraisemblable pour l'objectif {goal_id} (au moins {floor} s)"
            )
    return errors


def validate_plan(
    plan: PlanResponse,
    *,
    n_weeks: int,
    sessions_per_week: int,
    pace_available: bool,
    estimate_min_s: Mapping[int, int] | None = None,
    first_week: int = 1,
    fixed_counts: Mapping[int, int] | None = None,
) -> list[str]:
    """Contrôle métier d'un plan ; retourne la liste des erreurs (vide si valide).

    `estimate_min_s` (goal_id -> plancher en secondes) : objectifs dont le plan doit porter une estimation
    dans `estimated_times`, au moins égale au plancher.
    `first_week` : première semaine attendue (régénération de la suite d'un plan).
    `fixed_counts` : séances conservées par semaine, qui comptent dans le maximum de leur semaine.
    """
    fixed_counts = fixed_counts or {}
    errors = estimate_errors(plan.estimated_times, estimate_min_s)
    indexes = [w.week_index for w in plan.weeks]
    if indexes != list(range(first_week, n_weeks + 1)):
        errors.append(
            f"les semaines doivent être numérotées de {first_week} à {n_weeks} sans trou (reçu : {indexes})"
        )
    for week in plan.weeks:
        n = len(week.sessions)
        fixed = fixed_counts.get(week.week_index, 0)
        cap = max(0, sessions_per_week - fixed)
        if n > cap:
            detail = f" ({fixed} fixée{'s' if fixed > 1 else ''})" if fixed else ""
            errors.append(f"semaine {week.week_index} : {n} séances pour {cap} demandées{detail}")
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
    estimate_min_s: Mapping[int, int] | None = None,
) -> list[str]:
    """Contrôle métier d'un ajustement ; retourne la liste des erreurs (vide si valide).

    `counts_by_week` : nombre de séances actuelles par semaine (tous statuts), avant changements.
    `week_of_session` (session_id -> week_index) permet de décompter un `remove` ou un `modify`
    qui change de semaine ; s'il est absent (None) ou ne connaît pas la séance, le retrait
    n'est pas décompté.
    `exported_ids` : séances exportées, qui ne peuvent pas changer de semaine (date Garmin fixée).
    `estimate_min_s` : comme pour `validate_plan`, objectifs à estimer et leur plancher.
    """
    errors = estimate_errors(adj.estimated_times, estimate_min_s)
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


# --- conseils du coach (jour J) ---------------------------------------------------------------


class AdviceTip(_Strict):
    title: str = Field(max_length=60)
    text: str = Field(max_length=400)


class CoachAdvice(_Strict):
    tips: list[AdviceTip] = Field(min_length=3, max_length=6)


# Chiffres d'allure, de durée et d'heure, dans l'ordre de lecture : chaque forme lue est effacée avant
# la suivante. Chaque chiffre donne des clés (genre, valeur) ; une forme ambiguë (« 1:48 ») en donne
# plusieurs. Prompt et conseil sont lus de la même façon.
_B = r"(?<![\d:'’′])"  # pas collé à un autre chiffre
_E = r"(?![\d:'’′])"
_HMS = re.compile(_B + r"(\d{1,2}):(\d{2}):(\d{2})" + _E)
_PACE = re.compile(
    _B + r"(\d{1,2})\s*[:'’′]\s*(\d{2})\s*(?:\"|”|″|'')?\s*(?:min\s*)?(?:/\s*km|par\s+km|au\s+km|au\s+kilo(?:mètre)?)",
    re.IGNORECASE,
)
_APOSTROPHE = re.compile(_B + r"(\d{1,2})['’′](\d{2})(?:\"|”|″|'')?(?!\d)")
_MIN_SEC = re.compile(_B + r"(\d{1,2})\s*min\s*(\d{2})(?!\d)(\s*/\s*km)?", re.IGNORECASE)
_HOURS = re.compile(
    _B + r"(\d{1,3})\s*h(?:eures?)?(?:\s*(\d{2})(?:\s*(?:min(?:utes?)?|mn))?)?(?![\w])", re.IGNORECASE
)
_COLON = re.compile(_B + r"(\d{1,2}):(\d{2})" + _E)
_MINUTES = re.compile(_B + r"(\d{1,3})\s*(?:min(?:utes?)?|mn)(?![a-zà-ÿ])", re.IGNORECASE)

_Key = tuple[str, int]


def _minutes(seconds: int) -> set[_Key]:
    """Durée à la minute : arrondie vers le bas et au plus proche (« 1:45:20 » se cite « 1 h 45 »)."""
    return {("dur", seconds // 60), ("dur", round(seconds / 60))}


def _hms_keys(m: re.Match) -> set[_Key]:
    h, mi, s = map(int, m.groups())
    return _minutes(h * 3600 + mi * 60 + s)


def _pace_keys(m: re.Match) -> set[_Key]:
    return {("pace", int(m.group(1)) * 60 + int(m.group(2)))}


def _min_sec_keys(m: re.Match) -> set[_Key]:
    mi, s = int(m.group(1)), int(m.group(2))
    return {("pace", mi * 60 + s)} if m.group(3) else _minutes(mi * 60 + s)


def _hours_keys(m: re.Match) -> set[_Key]:
    h, mi = int(m.group(1)), int(m.group(2) or 0)
    keys = {("dur", h * 60 + mi)}
    return keys | {("clock", h * 60 + mi)} if h < 24 and mi < 60 else keys


def _colon_keys(m: re.Match) -> set[_Key]:
    a, b = int(m.group(1)), int(m.group(2))
    if a < 24 and len(m.group(1)) == 2:  # « 08:30 », forme des heures du guide : une heure, jamais une allure
        return {("clock", a * 60 + b)}
    if a < 24:  # « 1:48 » : allure m:ss, heure ou durée h:mm
        return {("pace", a * 60 + b), ("clock", a * 60 + b), ("dur", a * 60 + b)}
    return _minutes(a * 60 + b)  # « 42:15 » : durée m:ss


def _minutes_keys(m: re.Match) -> set[_Key]:
    return {("dur", int(m.group(1)))}


_FORMS = (
    (_HMS, _hms_keys),
    (_PACE, _pace_keys),
    (_APOSTROPHE, _pace_keys),
    (_MIN_SEC, _min_sec_keys),
    (_HOURS, _hours_keys),
    (_COLON, _colon_keys),
    (_MINUTES, _minutes_keys),
)


def figures(text: str) -> list[tuple[str, set[_Key]]]:
    """Allures, durées et heures d'un texte : (texte lu, clés normalisées)."""
    out: list[tuple[str, set[_Key]]] = []
    for pattern, keys in _FORMS:
        def _take(m: re.Match, keys=keys) -> str:
            out.append((m.group(0).strip(), keys(m)))
            return " " * len(m.group(0))

        text = pattern.sub(_take, text)
    return out


def validate_advice(advice: CoachAdvice, prompt: str) -> list[str]:
    """Refuse toute allure, durée ou heure du conseil absente du prompt (une erreur par chiffre)."""
    known: set[_Key] = set()
    for _, keys in figures(prompt):
        known |= keys
    errors: list[str] = []
    seen: set[str] = set()
    for tip in advice.tips:
        for raw, keys in figures(f"{tip.title}\n{tip.text}"):
            if keys & known or raw in seen:
                continue
            seen.add(raw)
            errors.append(
                f"conseil « {tip.title} » : « {raw} » ne figure pas dans les données fournies ; "
                "ne cite que des allures, durées ou heures présentes dans la demande"
            )
    return errors
