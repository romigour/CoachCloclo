"""Génère les fixtures GPX synthétiques (lancé une fois, résultat committé)."""

import math
from pathlib import Path

OUT = Path(__file__).parent
STEP_M = 20
DEG_PER_M = 1 / 111_195  # latitude


def _profile(km: float) -> float:
    """Altitude : deux montées de +300 m sur 3 km, chacune suivie d'une descente de 1 km."""
    if km < 1:
        return 100.0
    if km < 4:
        return 100 + 100 * (km - 1)
    if km < 5:
        return 400 - 300 * (km - 4)
    if km < 6:
        return 100.0
    if km < 9:
        return 100 + 100 * (km - 6)
    return 400 - 300 * (km - 9)


def _gpx(points: list[tuple[float, float, float | None]]) -> str:
    rows = []
    for lat, lon, ele in points:
        e = "" if ele is None else f"<ele>{ele:.1f}</ele>"
        rows.append(f'<trkpt lat="{lat:.6f}" lon="{lon:.6f}">{e}</trkpt>')
    body = "\n".join(rows)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<gpx version="1.1" creator="coach-fixtures" xmlns="http://www.topografix.com/GPX/1/1">\n'
        f"<trk><trkseg>\n{body}\n</trkseg></trk>\n</gpx>\n"
    )


def main() -> None:
    n = 10_000 // STEP_M
    base_lat, base_lon = 45.0, 6.0
    climb = [
        (base_lat + i * STEP_M * DEG_PER_M, base_lon + 0.00005 * math.sin(i / 40), _profile(i * STEP_M / 1000))
        for i in range(n + 1)
    ]
    (OUT / "climb.gpx").write_text(_gpx(climb), encoding="utf-8")
    flat = [(base_lat + i * STEP_M * DEG_PER_M, base_lon, None) for i in range(n + 1)]
    (OUT / "flat_no_ele.gpx").write_text(_gpx(flat), encoding="utf-8")
    (OUT / "broken.gpx").write_text("<gpx><trk><trkseg><trkpt lat=", encoding="utf-8")


if __name__ == "__main__":
    main()
