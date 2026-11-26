"""Guide de course : phases, passages, eau et nutrition, matin et préparation. Module pur."""

from typing import Literal

from pydantic import BaseModel

from coach.analysis import race_guide_texts as texts
from coach.analysis.race_plan import (
    _PACE_TOLERANCE_S,
    _ZONES,
    RaceBasis,
    RacePlan,
    RaceSettings,
    Segment,
    clock_at,
    hhmm_s,
    intake_per_hour,
    intake_tier,
    race_hr_zone,
)
from coach.analysis.zones import HrZoneName

DistanceBand = Literal["court", "semi", "marathon", "ultra"]
PhaseName = Literal["Départ", "Installation", "Cœur de course", "Final"]
PrepTitle = Literal["La semaine d'avant", "La veille", "Le matin"]

_HALF_KM = 21.0975
_BAND_LIMITS_KM: tuple[tuple[float, DistanceBand], ...] = ((12.0, "court"), (25.0, "semi"), (45.0, "marathon"))
_SHORT_PHASES: tuple[tuple[PhaseName, float], ...] = (("Départ", 0.15), ("Cœur de course", 0.85), ("Final", 1.0))
_LONG_PHASES: tuple[tuple[PhaseName, float], ...] = (
    ("Départ", 0.10),
    ("Installation", 0.40),
    ("Cœur de course", 0.85),
    ("Final", 1.0),
)
_SNAP_RATIO = 0.10  # écart de temps maximal (part de la durée de la phase) pour caler une borne sur un ravito
_CLIMB_MIN_M = {False: 20, True: 100}  # selon trail
_DESCENT_MIN_M = 150  # trail seulement
_SPLIT_STEP_KM = {"court": 5.0, "semi": 5.0, "ultra": 10.0}
_MARATHON_MARKS: tuple[tuple[float, str], ...] = (
    (5.0, "5 km"),
    (10.0, "10 km"),
    (_HALF_KM, "Semi"),
    (25.0, "25 km"),
    (30.0, "30 km"),
    (35.0, "35 km"),
)
_GEL_G = 25
_FIRST_GEL_S = 40 * 60
_NO_GEL_LAST_S = 15 * 60
_GEL = f"Gel ({_GEL_G} g) + quelques gorgées"
# Durée supposée sans temps de référence, pour choisir le palier de nutrition : 10 km < 1 h 15, semi < 2 h 30.
_BAND_DURATION_S: dict[DistanceBand, int] = {"court": 0, "semi": 2 * 3600, "marathon": 4 * 3600, "ultra": 8 * 3600}
_BREAKFAST_BEFORE_S: dict[DistanceBand, int] = {"court": 2 * 3600, "semi": 3 * 3600, "marathon": 3 * 3600, "ultra": 3 * 3600}
_ARRIVAL_BEFORE_S = 60 * 60
_WARMUP_BEFORE_S: dict[DistanceBand, int] = {"court": 30 * 60, "semi": 25 * 60, "marathon": 15 * 60, "ultra": 15 * 60}


def distance_band(distance_km: float) -> DistanceBand:
    for limit, band in _BAND_LIMITS_KM:
        if distance_km <= limit:
            return band
    return "ultra"


class Phase(BaseModel):
    name: PhaseName
    start_km: float
    end_km: float
    pace_low_s_km: int | None
    pace_high_s_km: int | None
    hr_zone: HrZoneName | None
    hr_low: int | None
    hr_high: int | None
    elapsed_end_s: int | None
    clock_end: str | None
    terrain: list[str]
    advice: str


class Split(BaseModel):
    km: float
    label: str
    elapsed_s: int
    clock: str


class _Clock:
    """Temps écoulé ↔ kilomètre, interpolés linéairement dans les segments du plan."""

    def __init__(self, plan: RacePlan):
        self.segments = plan.segments
        self.total_s = plan.reference_time_s or 0
        self.distance_km = plan.distance_km

    def elapsed_at(self, km: float) -> float:
        if km >= self.distance_km:
            return float(self.total_s)
        prev = 0.0
        for s in self.segments:
            end = s.elapsed_s or 0
            if km < s.end_km:
                length = s.end_km - s.start_km
                frac = (km - s.start_km) / length if length > 0 else 1.0
                return prev + (end - prev) * min(max(frac, 0.0), 1.0)
            prev = float(end)
        return float(self.total_s)

    def km_at(self, elapsed_s: float) -> float:
        prev = 0.0
        for s in self.segments:
            end = s.elapsed_s or 0
            if elapsed_s < end:
                frac = (elapsed_s - prev) / (end - prev) if end > prev else 1.0
                return s.start_km + (s.end_km - s.start_km) * frac
            prev = float(end)
        return self.distance_km


def _half_km(km: float) -> float:
    return round(km * 2) / 2


def _boundaries(plan: RacePlan, trail: bool, shares: list[float]) -> list[tuple[float, float | None]]:
    """(km, temps écoulé) de la fin de chaque phase ; temps None sans temps de référence."""
    clock = _Clock(plan)
    reference = plan.reference_time_s
    out: list[tuple[float, float | None]] = []
    phase_start_s = 0.0
    for share in shares[:-1]:
        if reference is None:
            out.append((_half_km(share * plan.distance_km), None))
        elif not trail:
            km = _half_km(share * plan.distance_km)
            out.append((km, clock.elapsed_at(km)))
        else:
            target_s = share * reference
            near = min(plan.aid_passages, key=lambda a: abs(a.passage.elapsed_s - target_s), default=None)
            if near is not None and abs(near.passage.elapsed_s - target_s) < _SNAP_RATIO * (target_s - phase_start_s):
                out.append((near.station.km, float(near.passage.elapsed_s)))
            else:
                out.append((_half_km(clock.km_at(target_s)), target_s))
        phase_start_s = out[-1][1] or 0.0
    out.append((plan.distance_km, None if reference is None else float(reference)))
    return out


def _terrain(segments: list[Segment], start_km: float, end_km: float, trail: bool) -> list[str]:
    lines: list[str] = []
    for s in segments:
        if min(s.end_km, end_km) - max(s.start_km, start_km) <= 0:
            continue
        span = f"km {s.start_km:g}–{s.end_km:g}"
        if s.kind == "montée" and s.d_plus_m >= _CLIMB_MIN_M[trail]:
            lines.append(f"Montée {span}, +{s.d_plus_m} m")
        elif trail and s.kind == "descente" and s.d_minus_m >= _DESCENT_MIN_M:
            lines.append(f"Descente {span}, −{s.d_minus_m} m")
    return lines


def build_phases(plan: RacePlan, trail: bool, basis: RaceBasis, start_time: str) -> list[Phase]:
    """Phases de course : par distance sur route, par temps de course sur trail."""
    shape = _SHORT_PHASES if distance_band(plan.distance_km) == "court" else _LONG_PHASES
    bounds = _boundaries(plan, trail, [share for _, share in shape])
    start_s = hhmm_s(start_time)
    phases: list[Phase] = []
    prev_km, prev_elapsed = 0.0, 0.0
    for (name, _), (end_km, elapsed) in zip(shape, bounds):
        pace_low = pace_high = zone = hr_low = hr_high = None
        if elapsed is not None and plan.reference_time_s is not None:
            if trail:
                zone = race_hr_zone(plan.reference_time_s)
                if name == "Départ":
                    zone = _ZONES[max(_ZONES.index(zone) - 1, 0)]
                hr_low, hr_high = basis.hr.get(zone, (None, None))
            elif end_km > prev_km:
                pace = round((elapsed - prev_elapsed) / (end_km - prev_km))
                pace_low, pace_high = pace - _PACE_TOLERANCE_S, pace + _PACE_TOLERANCE_S
        phases.append(
            Phase(
                name=name,
                start_km=prev_km,
                end_km=end_km,
                pace_low_s_km=pace_low,
                pace_high_s_km=pace_high,
                hr_zone=zone,
                hr_low=hr_low,
                hr_high=hr_high,
                elapsed_end_s=None if elapsed is None else round(elapsed),
                clock_end=None if elapsed is None else clock_at(start_s, elapsed),
                terrain=_terrain(plan.segments, prev_km, end_km, trail),
                advice="",
            )
        )
        prev_km, prev_elapsed = end_km, elapsed or 0.0
    return phases


def _split_marks(distance_km: float) -> list[tuple[float, str]]:
    band = distance_band(distance_km)
    if band == "marathon":
        marks = list(_MARATHON_MARKS)
    else:
        step = _SPLIT_STEP_KM[band]
        marks = [(k * step, f"{k * step:g} km") for k in range(1, int(distance_km // step) + 1)]
    return [(km, label) for km, label in marks if km < distance_km - 0.05] + [(distance_km, "Arrivée")]


def build_splits(plan: RacePlan, start_time: str) -> list[Split]:
    """Passages kilométriques de la route ; vide en trail (cible FC) ou sans temps de référence."""
    trail = any(s.target_kind == "hr" for s in plan.segments)
    if plan.reference_time_s is None or trail:
        return []
    clock, start_s = _Clock(plan), hhmm_s(start_time)
    return [
        Split(km=km, label=label, elapsed_s=round(clock.elapsed_at(km)), clock=clock_at(start_s, clock.elapsed_at(km)))
        for km, label in _split_marks(plan.distance_km)
    ]


class Intake(BaseModel):
    km: float
    clock: str | None
    what: str


class GuideNutrition(BaseModel):
    carbs_g_h: int
    water_ml_h: int
    recommended: bool  # glucides et eau tirés de la recommandation (aucun des deux saisi)
    principle: str
    intakes: list[Intake]


class MorningStep(BaseModel):
    clock: str
    label: str


class PrepBlock(BaseModel):
    title: PrepTitle
    items: list[str]


class RaceGuide(BaseModel):
    band: DistanceBand
    reference_time_s: int | None
    avg_pace_s_km: int | None  # route seulement
    phases: list[Phase]
    splits: list[Split]
    nutrition: GuideNutrition
    morning: list[MorningStep]
    preparation: list[PrepBlock]


def _intakes(plan: RacePlan, carbs_g_h: int, start_s: int) -> list[Intake]:
    """Gels route : le premier à 40 min, puis au rythme des glucides visés ; aucun dans les 15 dernières minutes."""
    total = plan.reference_time_s
    if total is None or carbs_g_h <= 0:
        return []
    clock, step = _Clock(plan), _GEL_G / carbs_g_h * 3600
    out: list[Intake] = []
    t = float(_FIRST_GEL_S)
    while t <= total - _NO_GEL_LAST_S:
        out.append(Intake(km=round(clock.km_at(t), 1), clock=clock_at(start_s, t), what=_GEL))
        t += step
    return out


def _nutrition(
    plan: RacePlan, trail: bool, settings: RaceSettings, band: DistanceBand, start_s: int
) -> GuideNutrition:
    duration = plan.reference_time_s if plan.reference_time_s is not None else _BAND_DURATION_S[band]
    carbs, water = intake_per_hour(settings, duration)
    return GuideNutrition(
        carbs_g_h=carbs,
        water_ml_h=water,
        recommended=settings.carbs_g_h is None and settings.water_ml_h is None,
        principle=texts.PRINCIPLE[(trail, intake_tier(duration))],
        intakes=[] if trail else _intakes(plan, carbs, start_s),
    )


def _morning(band: DistanceBand, start_s: int) -> list[MorningStep]:
    steps = [
        (_BREAKFAST_BEFORE_S[band], texts.MORNING_BREAKFAST),
        (_ARRIVAL_BEFORE_S, texts.MORNING_ARRIVAL),
        (_WARMUP_BEFORE_S[band], texts.MORNING_WARMUP.format(texts.WARMUP[band])),
        (0, texts.MORNING_START),
    ]
    return [MorningStep(clock=clock_at(start_s, -before), label=label) for before, label in steps]


def _advice(trail: bool, band: DistanceBand, phase: Phase) -> str:
    advice = texts.PHASE_ADVICE[(trail, band, phase.name)]
    if not trail and phase.terrain:
        advice = f"{advice} {texts.ROAD_CLIMB_HINT}"
    return advice


def build_race_guide(*, plan: RacePlan, trail: bool, settings: RaceSettings, basis: RaceBasis) -> RaceGuide:
    """Guide complet tiré du plan ; sans temps de référence, ni allure ni passage, mais conseils et matin datés."""
    band = distance_band(plan.distance_km)
    start_s = hhmm_s(settings.start_time)
    phases = [
        p.model_copy(update={"advice": _advice(trail, band, p)})
        for p in build_phases(plan, trail, basis, settings.start_time)
    ]
    reference = plan.reference_time_s
    return RaceGuide(
        band=band,
        reference_time_s=reference,
        avg_pace_s_km=None if reference is None or trail else round(reference / plan.distance_km),
        phases=phases,
        splits=build_splits(plan, settings.start_time),
        nutrition=_nutrition(plan, trail, settings, band, start_s),
        morning=_morning(band, start_s),
        preparation=[PrepBlock(title=title, items=items) for title, items in texts.PREPARATION[(trail, band)].items()],
    )
