"""Stratégie du jour J : modèle d'effort (coût de pente) et prédiction de temps. Module pur."""

from datetime import date

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
