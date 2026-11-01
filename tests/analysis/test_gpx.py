from pathlib import Path

import pytest

from coach.analysis.gpx import GpxError, _detect_climbs, _smooth, analyze_gpx, profile, summary_to_text, waypoints

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


def _km(n: int) -> list[float]:
    """Une mesure tous les 100 m."""
    return [i * 0.1 for i in range(n)]


def test_small_dip_inside_climb_does_not_split():
    # montée 100 -> 200, creux de 10 m (< 20), remontée jusqu'à 300, puis descente
    ele = [100, 150, 200, 190, 250, 300, 250, 200]
    climbs = _detect_climbs(_km(len(ele)), [float(e) for e in ele])
    assert len(climbs) == 1
    assert climbs[0].gain_m == 200 and climbs[0].start_km == 0.0


def test_big_dip_splits_climb():
    ele = [100.0, 160.0, 130.0, 100.0, 170.0, 230.0]
    assert len(_detect_climbs(_km(len(ele)), ele)) == 2


def test_gain_of_50m_or_less_is_not_a_climb():
    ele = [100.0, 120.0, 150.0, 120.0, 100.0]
    assert _detect_climbs(_km(len(ele)), ele) == []


def test_climb_still_rising_at_end_is_closed():
    ele = [100.0, 100.0, 160.0, 220.0, 280.0]
    climbs = _detect_climbs(_km(len(ele)), ele)
    assert len(climbs) == 1
    assert climbs[0].gain_m == 180 and climbs[0].start_km == pytest.approx(0.1)
    assert climbs[0].length_km == pytest.approx(0.3)


def test_smooth_attenuates_spike_and_shrinks_window_at_edges():
    out = _smooth([0.0, 0.0, 100.0, 0.0, 0.0])
    assert out[2] == pytest.approx(20.0)
    assert out[0] == pytest.approx(100 / 3) and out[1] == pytest.approx(25.0)  # fenêtres de 3 et 4 points
    assert _smooth([10.0, 20.0]) == [15.0, 15.0]


def test_profile_resampled_every_50_m():
    p = profile(FIX("climb.gpx"))
    assert p[0].km == 0
    assert p[-1].km == pytest.approx(analyze_gpx(FIX("climb.gpx")).distance_km, abs=0.01)
    assert all(b.km - a.km == pytest.approx(0.05, abs=1e-6) for a, b in zip(p, p[1:-1]))
    top = max((x for x in p if x.km < 5), key=lambda x: x.ele_m)  # 1er sommet : les deux sont à égalité
    assert top.ele_m == pytest.approx(400, abs=15) and top.km == pytest.approx(4.0, abs=0.2)


def test_profile_none_without_elevation():
    assert profile(FIX("flat_no_ele.gpx")) is None


def test_profile_broken_raises():
    with pytest.raises(GpxError):
        profile(FIX("broken.gpx"))


def test_waypoints_projected_and_filtered():
    w = waypoints(FIX("trail_wpt.gpx"))
    assert [x.name for x in w] == ["Ravito Col"]  # départ/arrivée à km 0 / fin, parking hors trace
    assert w[0].km == pytest.approx(4.0, abs=0.05)


def test_waypoints_empty_when_none():
    assert waypoints(FIX("climb.gpx")) == []
