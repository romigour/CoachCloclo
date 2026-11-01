"""Stratégie du jour J : modèle d'effort (coût de pente) et prédiction de temps. Module pur."""

from datetime import date
from math import ceil
from typing import Literal

from pydantic import BaseModel

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
