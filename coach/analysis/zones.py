"""Zones d'entraînement : allures (multiples de l'allure seuil) et fréquence cardiaque."""

from typing import Literal

from pydantic import BaseModel

PaceZoneName = Literal["récup", "EF", "marathon", "seuil", "VMA"]
HrZoneName = Literal["Z1", "Z2", "Z3", "Z4", "Z5"]

_PACE_FACTORS: dict[PaceZoneName, tuple[float, float]] = {
    "récup": (1.30, 1.45),
    "EF": (1.20, 1.32),
    "marathon": (1.06, 1.12),
    "seuil": (0.98, 1.03),
    "VMA": (0.88, 0.93),
}
_HR_NAMES: list[HrZoneName] = ["Z1", "Z2", "Z3", "Z4", "Z5"]
_KARVONEN = [(0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.0)]


class Zones(BaseModel):
    pace: dict[PaceZoneName, tuple[int, int]] | None  # s/km, borne rapide puis lente
    hr: dict[HrZoneName, tuple[int, int]]  # bpm
    source: list[str]


def compute_zones(
    *,
    threshold_pace_s_km: int | None,
    pred_10k_s: int | None,
    garmin_hr_zones: list[int] | None,
    hr_max: int | None,
    hr_rest: int | None,
) -> Zones:
    """Calcule les zones d'allure et de FC, avec repli sur la prédiction 10 km et Karvonen."""
    source: list[str] = []

    if threshold_pace_s_km is not None:
        t: int | None = threshold_pace_s_km
        source.append("lactate_threshold")
    elif pred_10k_s is not None:
        t = round(pred_10k_s / 10 * 1.04)
        source.append("race_prediction_10k")
    else:
        t = None

    pace = (
        {name: (round(t * fast), round(t * slow)) for name, (fast, slow) in _PACE_FACTORS.items()}
        if t is not None
        else None
    )

    if hr_max is None:
        raise ValueError("FC max inconnue")
    if garmin_hr_zones is not None:
        if len(garmin_hr_zones) != 5:
            raise ValueError("Il faut 5 bornes de zones FC Garmin")
        bounds = [*garmin_hr_zones, hr_max]
        hr = {name: (bounds[i], bounds[i + 1]) for i, name in enumerate(_HR_NAMES)}
        source.append("garmin_hr_zones")
    else:
        if hr_rest is None:
            raise ValueError("FC repos inconnue")
        reserve = hr_max - hr_rest
        hr = {
            name: (round(hr_rest + reserve * lo), round(hr_rest + reserve * hi))
            for name, (lo, hi) in zip(_HR_NAMES, _KARVONEN)
        }
        source.append("karvonen")

    return Zones(pace=pace, hr=hr, source=source)
