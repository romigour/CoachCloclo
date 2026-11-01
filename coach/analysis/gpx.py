"""Analyse d'une trace GPX : distance, D+/D-, montées (résumé pour le formulaire et pour Claude)."""

import gpxpy
import gpxpy.geo
from pydantic import BaseModel

_ERR = "Fichier GPX illisible ou vide"
_NO_ELE = "Trace sans altitude : D+ à saisir manuellement"
_SMOOTH_WINDOW = 5
_CLIMB_MIN_GAIN_M = 50
_CLIMB_END_DROP_M = 20
_PROFILE_STEP_KM = 0.05
_WPT_MAX_DIST_M = 200


class Climb(BaseModel):
    start_km: float
    length_km: float
    gain_m: int
    avg_grade_pct: float


class GpxSummary(BaseModel):
    distance_km: float
    d_plus_m: int | None
    d_minus_m: int | None
    max_ele_m: int | None
    climbs: list[Climb]
    warnings: list[str]


class ProfilePoint(BaseModel):
    km: float
    ele_m: float


class Waypoint(BaseModel):
    name: str
    km: float


class GpxError(ValueError):
    """Trace GPX inexploitable."""


def _smooth(values: list[float], window: int = _SMOOTH_WINDOW) -> list[float]:
    """Moyenne glissante centrée, fenêtre réduite aux bords."""
    half = window // 2
    out = []
    for i in range(len(values)):
        chunk = values[max(0, i - half) : i + half + 1]
        out.append(sum(chunk) / len(chunk))
    return out


def _detect_climbs(dist_km: list[float], ele: list[float]) -> list[Climb]:
    """Montée : gain > 50 m depuis le point bas courant ; fin au sommet après une descente > 20 m."""
    climbs: list[Climb] = []
    low = 0
    high: int | None = None  # None tant qu'aucune montée n'est en cours

    def close(top: int) -> None:
        gain = ele[top] - ele[low]
        length = dist_km[top] - dist_km[low]
        climbs.append(
            Climb(
                start_km=round(dist_km[low], 2),
                length_km=round(length, 2),
                gain_m=round(gain),
                avg_grade_pct=round(gain / (length * 1000) * 100, 1) if length > 0 else 0.0,
            )
        )

    for i in range(1, len(ele)):
        if high is None:
            if ele[i] <= ele[low]:  # <= : sur un plat, le départ est le dernier point bas
                low = i
            elif ele[i] - ele[low] > _CLIMB_MIN_GAIN_M:
                high = i
        elif ele[i] > ele[high]:
            high = i
        elif ele[high] - ele[i] > _CLIMB_END_DROP_M:
            close(high)
            high = None
            low = i
    if high is not None:
        close(high)
    return climbs


def _parse(data: bytes) -> tuple[gpxpy.gpx.GPX, list[gpxpy.gpx.GPXTrackPoint], list[float]]:
    """Fichier GPX, points de trace et km cumulés ; lève GpxError si illisible ou moins de 2 points."""
    try:
        gpx = gpxpy.parse(data)
    except Exception as exc:
        raise GpxError(_ERR) from exc
    points = [p for t in gpx.tracks for s in t.segments for p in s.points]
    if len(points) < 2:
        raise GpxError(_ERR)

    dist_km = [0.0]
    for a, b in zip(points, points[1:]):
        step = gpxpy.geo.distance(a.latitude, a.longitude, None, b.latitude, b.longitude, None)
        dist_km.append(dist_km[-1] + step / 1000)
    return gpx, points, dist_km


def analyze_gpx(data: bytes) -> GpxSummary:
    """Résume une trace GPX ; lève GpxError si le fichier est illisible ou a moins de 2 points."""
    _, points, dist_km = _parse(data)
    distance_km = round(dist_km[-1], 2)

    if any(p.elevation is None for p in points):
        return GpxSummary(
            distance_km=distance_km, d_plus_m=None, d_minus_m=None, max_ele_m=None,
            climbs=[], warnings=[_NO_ELE],
        )

    ele = _smooth([p.elevation for p in points])
    deltas = [b - a for a, b in zip(ele, ele[1:])]
    return GpxSummary(
        distance_km=distance_km,
        d_plus_m=round(sum(d for d in deltas if d > 0)),
        d_minus_m=round(-sum(d for d in deltas if d < 0)),
        max_ele_m=round(max(ele)),
        climbs=_detect_climbs(dist_km, ele),
        warnings=[],
    )


def profile(data: bytes) -> list[ProfilePoint] | None:
    """Profil d'altitude lissé, rééchantillonné tous les 50 m ; None si la trace n'a pas d'altitude."""
    _, points, dist_km = _parse(data)
    if any(p.elevation is None for p in points):
        return None
    ele = _smooth([p.elevation for p in points])
    total = dist_km[-1]
    kms = [i * _PROFILE_STEP_KM for i in range(int(total / _PROFILE_STEP_KM + 1e-9) + 1)]
    if total - kms[-1] > 1e-9:
        kms.append(total)
    else:
        kms[-1] = total
    out: list[ProfilePoint] = []
    j = 0
    for km in kms:
        while j < len(dist_km) - 2 and dist_km[j + 1] < km:
            j += 1
        span = dist_km[j + 1] - dist_km[j]
        t = 0.0 if span <= 0 else min(max((km - dist_km[j]) / span, 0.0), 1.0)
        out.append(ProfilePoint(km=km, ele_m=ele[j] + t * (ele[j + 1] - ele[j])))
    return out


def waypoints(data: bytes) -> list[Waypoint]:
    """Waypoints à moins de 200 m de la trace, projetés sur son point le plus proche, triés par km.

    Départ et arrivée (km 0 et distance totale, au 0,01 km près) sont écartés.
    """
    gpx, points, dist_km = _parse(data)
    distance = round(dist_km[-1], 2)
    found: list[Waypoint] = []
    for w in gpx.waypoints:
        dists = [gpxpy.geo.distance(w.latitude, w.longitude, None, p.latitude, p.longitude, None) for p in points]
        i = min(range(len(dists)), key=dists.__getitem__)
        km = round(dist_km[i], 2)
        if dists[i] <= _WPT_MAX_DIST_M and 0 < km < distance:
            found.append(Waypoint(name=w.name or "Ravito", km=km))
    return sorted(found, key=lambda x: x.km)


def summary_to_text(s: GpxSummary) -> str:
    """Texte français compact pour le prompt de Claude."""
    text = f"Parcours de {s.distance_km:.1f} km"
    if s.d_plus_m is None:
        return f"{text}. {' '.join(s.warnings)}"
    text += f", D+ {s.d_plus_m} m, D- {s.d_minus_m} m, altitude max {s.max_ele_m} m."
    if s.climbs:
        n = len(s.climbs)
        items = ", ".join(
            f"km {c.start_km:.1f} → +{c.gain_m} m sur {c.length_km:.1f} km ({c.avg_grade_pct:.0f} %)"
            for c in s.climbs
        )
        text += f" {n} montée{'s' if n > 1 else ''} : {items}."
    else:
        text += " Aucune montée significative."
    return text
