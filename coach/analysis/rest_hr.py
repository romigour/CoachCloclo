"""Choix de la FC repos : saisie manuelle, moyenne des nuits portées, dernière bonne valeur, Garmin."""

from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel

WINDOW_DAYS = 14
MIN_NIGHTS = 3


class NightRecord(BaseModel):
    day: date
    hr_rest: int | None
    slept: bool  # montre portée pendant la nuit


class RestHr(BaseModel):
    value: int | None
    source: Literal["manual", "nights", "last_good", "garmin"]
    nights: int | None = None


def nights_average(records: list[NightRecord], today: date) -> tuple[int, int] | None:
    """Moyenne arrondie de la FC repos et nombre de nuits portées sur les 14 derniers jours (aujourd'hui inclus).

    Renvoie None sous MIN_NIGHTS nuits exploitables.
    """
    start = today - timedelta(days=WINDOW_DAYS - 1)
    values = [
        r.hr_rest
        for r in records
        if r.slept and r.hr_rest is not None and start <= r.day <= today
    ]
    if len(values) < MIN_NIGHTS:
        return None
    return round(sum(values) / len(values)), len(values)


def choose_rest_hr(
    *,
    manual: int | None,
    nights: tuple[int, int] | None,
    last_nights_value: int | None,
    garmin_value: int | None,
) -> RestHr:
    """Priorité : saisie manuelle, moyenne des nuits, dernière moyenne valide, valeur Garmin."""
    if manual is not None:
        return RestHr(value=manual, source="manual")
    if nights is not None:
        return RestHr(value=nights[0], source="nights", nights=nights[1])
    if last_nights_value is not None:
        return RestHr(value=last_nights_value, source="last_good")
    return RestHr(value=garmin_value, source="garmin")
