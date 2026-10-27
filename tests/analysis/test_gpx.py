from pathlib import Path

import pytest

from coach.analysis.gpx import GpxError, analyze_gpx, summary_to_text

_FIXTURES = Path(__file__).parent.parent / "fixtures" / "gpx"


def FIX(name: str) -> bytes:
    return (_FIXTURES / name).read_bytes()


def test_climb_fixture():
    s = analyze_gpx(FIX("climb.gpx"))
    assert s.distance_km == pytest.approx(10.0, abs=0.2)
    assert s.d_plus_m == pytest.approx(600, abs=30)
    assert len(s.climbs) == 2 and s.climbs[0].avg_grade_pct == pytest.approx(10, abs=1.5)
    assert s.climbs[0].start_km == pytest.approx(1.0, abs=0.3)
    assert s.climbs[0].gain_m == pytest.approx(300, abs=30)
    assert s.climbs[0].length_km == pytest.approx(3.0, abs=0.3)


def test_no_elevation_warns():
    s = analyze_gpx(FIX("flat_no_ele.gpx"))
    assert s.d_plus_m is None and s.d_minus_m is None and s.max_ele_m is None
    assert s.climbs == []
    assert s.warnings == ["Trace sans altitude : D+ à saisir manuellement"]
    assert "Trace sans altitude : D+ à saisir manuellement" in summary_to_text(s)


def test_broken_raises():
    with pytest.raises(GpxError, match="Fichier GPX illisible ou vide"):
        analyze_gpx(FIX("broken.gpx"))
    with pytest.raises(GpxError):
        analyze_gpx(b"")


def test_single_point_raises():
    one = b'<gpx version="1.1"><trk><trkseg><trkpt lat="45" lon="6"><ele>1</ele></trkpt></trkseg></trk></gpx>'
    with pytest.raises(GpxError):
        analyze_gpx(one)


def test_summary_text_mentions_climbs():
    t = summary_to_text(analyze_gpx(FIX("climb.gpx")))
    assert "montée" in t and "D+" in t and t.startswith("Parcours de 10.0 km")
