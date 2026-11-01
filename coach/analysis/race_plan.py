"""Stratégie du jour J : coût de pente, prédiction, segments, passages et nutrition. Module pur."""

from datetime import date
from math import ceil
from typing import Literal, get_args

from pydantic import BaseModel, Field

from coach.analysis.gpx import ProfilePoint
from coach.analysis.zones import HrZoneName

# Coût énergétique de la course selon la pente (Minetti), polynôme de degré 5 en i (pente en fraction).
_MINETTI = (155.4, -30.4, -43.3, 46.3, 19.5, 3.6)  # coefficients de i^5 à i^0
_MINETTI_FLAT_COST = 3.6
_GRADE_LIMIT = 0.45
_MULT_MIN = 0.8
_MULT_MAX = 6.0

_MARATHON_KM = 42.195
_REFERENCES_KM = (5.0, 10.0, 21.0975, _MARATHON_KM)
_RIEGEL_EXP = 1.06
_RIEGEL_EXP_ULTRA = 1.10
_THRESHOLD_TO_MARATHON = 1.09

_GRADE_SMOOTH_STEPS = 2  # de part et d'autre du pas : fenêtre de classement ≈ 200 m
_CLASS_GRADE = 0.03
_MIN_SEGMENT_KM = 0.5
_MAX_SEGMENTS = 25
_SLICE_SIZES_KM = (1, 2, 5, 10)

SegmentKind = Literal["montée", "plat", "descente"]
_KINDS: tuple[SegmentKind, ...] = ("plat", "montée", "descente")


class RaceBasis(BaseModel):
    """Base physiologique figée du plan (prédictions Garmin, seuil, zones FC)."""

    captured_on: date
    pred_5k_s: int | None
    pred_10k_s: int | None
    pred_half_s: int | None
    pred_marathon_s: int | None
    threshold_pace_s_km: int | None
    hr: dict[HrZoneName, tuple[int, int]]


def grade_multiplier(grade: float) -> float:
    """Multiplicateur de coût d'une pente (fraction, ex. 0,10 = 10 %) par rapport au plat."""
    i = max(-_GRADE_LIMIT, min(_GRADE_LIMIT, grade))
    cost = 0.0
    for coef in _MINETTI:
        cost = cost * i + coef
    return max(_MULT_MIN, min(_MULT_MAX, cost / _MINETTI_FLAT_COST))


def step_eq_km(profile: list[ProfilePoint]) -> list[float]:
    """Distance équivalente plat de chaque pas du profil (len = len(profile) - 1)."""
    out: list[float] = []
    for a, b in zip(profile, profile[1:]):
        d_km = b.km - a.km
        grade = (b.ele_m - a.ele_m) / (d_km * 1000) if d_km > 0 else 0.0
        out.append(d_km * grade_multiplier(grade))
    return out


def predict_run_time(eq_km: float, basis: RaceBasis) -> int | None:
    """Temps prédit (s) pour une distance équivalente plat, ou None sans aucune base."""
    refs = [
        (km, t)
        for km, t in zip(
            _REFERENCES_KM,
            (basis.pred_5k_s, basis.pred_10k_s, basis.pred_half_s, basis.pred_marathon_s),
        )
        if t
    ]
    if refs:
        ref_km, ref_t = min(refs, key=lambda r: abs(eq_km - r[0]))
        if eq_km <= _MARATHON_KM:
            return round(ref_t * (eq_km / ref_km) ** _RIEGEL_EXP)
        t42 = ref_t * (_MARATHON_KM / ref_km) ** _RIEGEL_EXP
    elif basis.threshold_pace_s_km:
        t42 = _MARATHON_KM * basis.threshold_pace_s_km * _THRESHOLD_TO_MARATHON
        if eq_km <= _MARATHON_KM:
            return round(t42 * (eq_km / _MARATHON_KM) ** _RIEGEL_EXP)
    else:
        return None
    return round(t42 * (eq_km / _MARATHON_KM) ** _RIEGEL_EXP_ULTRA)


class Span(BaseModel):
    """Tronçon contigu du parcours (montée, plat ou descente)."""

    kind: SegmentKind
    start_km: float
    end_km: float
    eq_km: float
    d_plus_m: int
    d_minus_m: int


def _step_kinds(profile: list[ProfilePoint]) -> list[SegmentKind]:
    """Type de chaque pas, d'après la pente lissée sur ≈ 200 m."""
    n = len(profile) - 1
    kinds: list[SegmentKind] = []
    for j in range(n):
        lo = max(j - _GRADE_SMOOTH_STEPS, 0)
        hi = min(j + _GRADE_SMOOTH_STEPS, n)
        d_km = profile[hi].km - profile[lo].km
        grade = (profile[hi].ele_m - profile[lo].ele_m) / (d_km * 1000) if d_km > 0 else 0.0
        kinds.append("montée" if grade > _CLASS_GRADE else "descente" if grade < -_CLASS_GRADE else "plat")
    return kinds


class _Run:
    """Suite de pas [start, end) avec la distance cumulée par type, pour le type dominant."""

    def __init__(self, start: int, end: int, dist: dict[SegmentKind, float]):
        self.start, self.end, self.dist = start, end, dist

    @property
    def kind(self) -> SegmentKind:
        return max(_KINDS, key=lambda k: self.dist.get(k, 0.0))

    def km(self) -> float:
        return sum(self.dist.values())

    def merged(self, other: "_Run") -> "_Run":
        dist = dict(self.dist)
        for k, v in other.dist.items():
            dist[k] = dist.get(k, 0.0) + v
        return _Run(min(self.start, other.start), max(self.end, other.end), dist)


def _fuse_same_kind(runs: list[_Run]) -> list[_Run]:
    out: list[_Run] = []
    for r in runs:
        if out and out[-1].kind == r.kind:
            out[-1] = out[-1].merged(r)
        else:
            out.append(r)
    return out


def _merge_at(runs: list[_Run], i: int, j: int) -> list[_Run]:
    """Fusionne les tronçons voisins i et j, puis refusionne les voisins de même type."""
    lo = min(i, j)
    return _fuse_same_kind(runs[:lo] + [runs[i].merged(runs[j])] + runs[lo + 2 :])


def _slices(distance_km: float) -> list[Span]:
    """Découpage en tranches égales quand le parcours n'a pas de profil."""
    size = next((s for s in _SLICE_SIZES_KM if ceil(distance_km / s) <= _MAX_SEGMENTS), None)
    if size is None:
        size = distance_km / _MAX_SEGMENTS
    full = int(distance_km // size)
    if full < 1:
        bounds = [0.0, distance_km]
    else:
        bounds = [i * size for i in range(full + 1)]
        if distance_km - bounds[-1] >= size / 2:
            bounds.append(distance_km)
        else:
            bounds[-1] = distance_km
    return [
        Span(kind="plat", start_km=a, end_km=b, eq_km=b - a, d_plus_m=0, d_minus_m=0)
        for a, b in zip(bounds, bounds[1:])
    ]


def split_segments(profile: list[ProfilePoint] | None, distance_km: float) -> list[Span]:
    """Découpe [0, distance] en montées/plats/descentes (au plus 25), sans trou."""
    if not profile or len(profile) < 2:
        return _slices(distance_km)
    kinds = _step_kinds(profile)
    runs = _fuse_same_kind(
        [_Run(j, j + 1, {k: profile[j + 1].km - profile[j].km}) for j, k in enumerate(kinds)]
    )
    while len(runs) > 1:
        i = min(range(len(runs)), key=lambda x: runs[x].km())
        if runs[i].km() >= _MIN_SEGMENT_KM:
            break
        nb = [x for x in (i - 1, i + 1) if 0 <= x < len(runs)]
        runs = _merge_at(runs, i, max(nb, key=lambda x: runs[x].km()))
    while len(runs) > _MAX_SEGMENTS:
        i = min(range(len(runs)), key=lambda x: runs[x].km())
        nb = [x for x in (i - 1, i + 1) if 0 <= x < len(runs)]
        runs = _merge_at(runs, i, min(nb, key=lambda x: runs[x].km()))
    eq = step_eq_km(profile)
    spans: list[Span] = []
    for idx, r in enumerate(runs):
        deltas = [profile[j + 1].ele_m - profile[j].ele_m for j in range(r.start, r.end)]
        spans.append(
            Span(
                kind=r.kind,
                start_km=profile[r.start].km,
                end_km=distance_km if idx == len(runs) - 1 else profile[r.end].km,
                eq_km=sum(eq[r.start : r.end]),
                d_plus_m=round(sum(d for d in deltas if d > 0)),
                d_minus_m=round(-sum(d for d in deltas if d < 0)),
            )
        )
    return spans


NO_TIME = "Pas de prédiction possible : saisis un temps visé pour obtenir le découpage"
STALE = "Données de référence du {:%d/%m/%Y} : actualise-les avant la course"
LATE = "Barrière hors délai au ravito « {} » avec le temps prédit"

_HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"
_DAY_MIN = 24 * 60
_STALE_DAYS = 30
_PACE_TOLERANCE_S = 5
_TIGHT_MARGIN_S = 30 * 60
_Z4_MAX_S = 90 * 60
_Z3_MAX_S = 4 * 3600
_ZONES: tuple[HrZoneName, ...] = get_args(HrZoneName)


class AidStation(BaseModel):
    """Ravito : position, type, barrière horaire facultative et arrêt prévu."""

    km: float = Field(gt=0)
    name: str = Field(min_length=1, max_length=60)
    kind: Literal["eau", "complet"] = "complet"
    cutoff: str | None = Field(None, pattern=_HHMM)
    stop_min: float = Field(3, ge=0, le=120)


class RaceSettings(BaseModel):
    """Réglages de la stratégie saisis par l'athlète."""

    target_time_s: int | None = Field(None, gt=0)
    start_time: str = Field("08:00", pattern=_HHMM)
    carbs_g_h: int = Field(60, ge=0, le=150)
    water_ml_h: int = Field(500, ge=0, le=2000)
    carry_ml: int = Field(1000, gt=0, le=5000)
    aid_stations: list[AidStation] = []


class Segment(Span):
    """Segment du plan : temps, passage cumulé (arrêts franchis inclus) et cible montre."""

    index: int
    avg_grade_pct: float
    time_s: int | None
    pace_s_km: int | None
    elapsed_s: int | None
    clock: str | None
    target_kind: Literal["pace", "hr"]
    target_low: int | None
    target_high: int | None
    target_zone: HrZoneName | None


class Passage(BaseModel):
    """Arrivée à un ravito : temps écoulé, heure, marge sur la barrière."""

    elapsed_s: int
    clock: str
    margin_min: int | None
    status: Literal["ok", "serré", "hors délai"] | None


class AidPassage(BaseModel):
    station: AidStation
    predicted: Passage | None
    target: Passage | None


class NutritionLeg(BaseModel):
    """Tronçon entre deux points de ravitaillement : durée, glucides et eau à prévoir."""

    from_name: str
    to_name: str
    from_km: float
    to_km: float
    duration_s: int
    carbs_g: int
    water_ml: int
    over_capacity: bool


class RacePlan(BaseModel):
    distance_km: float
    eq_km: float
    stops_s: int
    predicted_time_s: int | None
    target_time_s: int | None
    reference_time_s: int | None
    segments: list[Segment]
    aid_passages: list[AidPassage]
    nutrition: list[NutritionLeg]
    warnings: list[str]


def race_hr_zone(total_s: int) -> HrZoneName:
    """Zone FC de course selon la durée totale : Z4 sous 1 h 30, Z3 jusqu'à 4 h, Z2 au-delà."""
    if total_s < _Z4_MAX_S:
        return "Z4"
    return "Z3" if total_s <= _Z3_MAX_S else "Z2"


def _hhmm_s(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 3600 + int(m) * 60


def _clock(start_s: int, elapsed_s: float) -> str:
    """Heure du jour (HH:MM, à la minute la plus proche), modulo 24 h."""
    minutes = round((start_s + elapsed_s) / 60) % _DAY_MIN
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


class _Timing:
    """Temps de course réparti sur les segments au prorata de leur distance équivalente."""

    def __init__(self, spans: list[Span], run_s: float, stations: list[AidStation]):
        total_eq = sum(s.eq_km for s in spans)
        self.spans, self.stations = spans, stations
        self.seg_s = [run_s * s.eq_km / total_eq for s in spans]
        self.cum_s = [0.0]
        for t in self.seg_s:
            self.cum_s.append(self.cum_s[-1] + t)

    def _run_at(self, km: float) -> float:
        """Temps de course (sans arrêts) au km donné, interpolé linéairement dans son segment."""
        last = len(self.spans) - 1
        i = next(j for j, s in enumerate(self.spans) if km < s.end_km or j == last)
        s = self.spans[i]
        length = s.end_km - s.start_km
        frac = min(max((km - s.start_km) / length, 0.0), 1.0) if length > 0 else 1.0
        return self.cum_s[i] + self.seg_s[i] * frac

    def arrival(self, idx: int) -> float:
        """Arrivée au ravito idx : temps de course + arrêts des ravitos précédents (pas le sien)."""
        return self._run_at(self.stations[idx].km) + sum(st.stop_min * 60 for st in self.stations[:idx])

    def seg_elapsed(self, i: int) -> float:
        """Cumul à la fin du segment i, arrêts des ravitos situés avant sa fin inclus."""
        end = self.spans[i].end_km
        return self.cum_s[i + 1] + sum(st.stop_min * 60 for st in self.stations if st.km < end)


def _passage(elapsed: float, start_s: int, cutoff: str | None) -> Passage:
    """Passage à un ravito ; marge et statut seulement si une barrière est saisie."""
    margin_s = None if cutoff is None else _hhmm_s(cutoff) - (start_s + elapsed)
    status = None
    if margin_s is not None:
        status = "hors délai" if margin_s < 0 else "ok" if margin_s > _TIGHT_MARGIN_S else "serré"
    return Passage(
        elapsed_s=round(elapsed),
        clock=_clock(start_s, elapsed),
        margin_min=None if margin_s is None else round(margin_s / 60),
        status=status,
    )


def _nutrition(timing: _Timing, distance_km: float, settings: RaceSettings, total_s: float) -> list[NutritionLeg]:
    """Tronçons départ → ravitos → arrivée ; durée de course seule (arrêts exclus)."""
    # (nom, km, heure de départ du point, heure d'arrivée au point)
    points = [("Départ", 0.0, 0.0, 0.0)]
    for idx, st in enumerate(timing.stations):
        arrive = timing.arrival(idx)
        points.append((st.name, st.km, arrive + st.stop_min * 60, arrive))
    points.append(("Arrivée", distance_km, total_s, total_s))
    legs: list[NutritionLeg] = []
    for (name, km, leave, _), (to_name, to_km, _, arrive) in zip(points, points[1:]):
        duration = arrive - leave
        water = round(duration / 3600 * settings.water_ml_h)
        legs.append(
            NutritionLeg(
                from_name=name,
                to_name=to_name,
                from_km=km,
                to_km=to_km,
                duration_s=round(duration),
                carbs_g=round(duration / 3600 * settings.carbs_g_h),
                water_ml=water,
                over_capacity=water > settings.carry_ml,
            )
        )
    return legs


def _target(kind: SegmentKind, pace: int | None, ref_s: int | None, trail: bool, basis: RaceBasis):
    """Cible montre d'un segment : (type, borne basse, borne haute, zone)."""
    if not trail:
        if pace is None:
            return "pace", None, None, None
        return "pace", pace - _PACE_TOLERANCE_S, pace + _PACE_TOLERANCE_S, None
    if ref_s is None:
        return "hr", None, None, None
    zone = race_hr_zone(ref_s)
    if kind == "descente":
        zone = _ZONES[max(_ZONES.index(zone) - 1, 0)]
    low, high = basis.hr.get(zone, (None, None))
    return "hr", low, high, zone


def build_race_plan(
    *,
    distance_km: float,
    trail: bool,
    profile: list[ProfilePoint] | None,
    basis: RaceBasis,
    settings: RaceSettings,
    today: date,
) -> RacePlan:
    """Plan de course complet : temps par segment, passages aux ravitos, nutrition, alertes."""
    stations = sorted(settings.aid_stations, key=lambda s: s.km) if trail else []
    stops_s = round(sum(st.stop_min * 60 for st in stations))
    target = settings.target_time_s
    if target is not None and target <= stops_s:
        raise ValueError("Le temps visé doit dépasser la durée des arrêts aux ravitos")
    spans = split_segments(profile, distance_km)
    eq_km = sum(s.eq_km for s in spans)
    pred_run = predict_run_time(eq_km, basis)
    predicted = None if pred_run is None else pred_run + stops_s
    reference = target if target is not None else predicted
    start_s = _hhmm_s(settings.start_time)
    warnings: list[str] = []
    if reference is None:
        warnings.append(NO_TIME)
    if (today - basis.captured_on).days > _STALE_DAYS:
        warnings.append(STALE.format(basis.captured_on))

    ref = None if reference is None else _Timing(spans, reference - stops_s, stations)
    segments: list[Segment] = []
    for i, s in enumerate(spans):
        length = s.end_km - s.start_km
        time_s = pace = elapsed = clock = None
        if ref is not None:
            time_s = round(ref.seg_s[i])
            pace = round(ref.seg_s[i] / length) if length > 0 else None
            elapsed = round(ref.seg_elapsed(i))
            clock = _clock(start_s, ref.seg_elapsed(i))
        kind, low, high, zone = _target(s.kind, pace, reference, trail, basis)
        segments.append(
            Segment(
                **s.model_dump(),
                index=i + 1,
                avg_grade_pct=round((s.d_plus_m - s.d_minus_m) / (length * 1000) * 100, 1) if length > 0 else 0.0,
                time_s=time_s,
                pace_s_km=pace,
                elapsed_s=elapsed,
                clock=clock,
                target_kind=kind,
                target_low=low,
                target_high=high,
                target_zone=zone,
            )
        )

    aid_passages: list[AidPassage] = []
    nutrition: list[NutritionLeg] = []
    if ref is not None and trail:
        pred_t = None if pred_run is None else _Timing(spans, pred_run, stations)
        for idx, st in enumerate(stations):
            p = None if pred_t is None else _passage(pred_t.arrival(idx), start_s, st.cutoff)
            t = None if target is None else _passage(ref.arrival(idx), start_s, st.cutoff)
            if p is not None and p.status == "hors délai":
                warnings.append(LATE.format(st.name))
            aid_passages.append(AidPassage(station=st, predicted=p, target=t))
        nutrition = _nutrition(ref, distance_km, settings, reference)

    return RacePlan(
        distance_km=distance_km,
        eq_km=eq_km,
        stops_s=stops_s,
        predicted_time_s=predicted,
        target_time_s=target,
        reference_time_s=reference,
        segments=segments,
        aid_passages=aid_passages,
        nutrition=nutrition,
        warnings=warnings,
    )
