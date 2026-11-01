from datetime import date

import pytest

from coach.analysis.gpx import ProfilePoint
from coach.analysis.race_plan import (
    RaceBasis,
    grade_multiplier,
    predict_run_time,
    split_segments,
    step_eq_km,
)


def test_grade_multiplier():
    assert grade_multiplier(0) == pytest.approx(1)
    assert grade_multiplier(0.10) == pytest.approx(1.658, abs=0.01)
    assert grade_multiplier(-0.05) == 0.8  # borne basse
    assert grade_multiplier(-0.30) == 0.8
    assert grade_multiplier(0.60) == grade_multiplier(0.45) <= 6


def test_step_eq_km_flat_and_climb():
    flat = [ProfilePoint(km=i * 0.05, ele_m=100) for i in range(21)]
    assert sum(step_eq_km(flat)) == pytest.approx(1.0)
    climb = [ProfilePoint(km=i * 0.05, ele_m=100 + 5 * i) for i in range(21)]  # +10 %
    assert sum(step_eq_km(climb)) == pytest.approx(1.658, abs=0.01)


B = dict(captured_on=date(2026, 11, 1), threshold_pace_s_km=None, hr={})


def test_predict_nearest_reference_riegel():
    b = RaceBasis(pred_5k_s=None, pred_10k_s=2880, pred_half_s=None, pred_marathon_s=None, **B)
    assert predict_run_time(10, b) == 2880
    assert predict_run_time(21.0975, b) == round(2880 * 2.10975**1.06)
    b2 = b.model_copy(update={"pred_half_s": 6400})
    assert predict_run_time(20, b2) == round(6400 * (20 / 21.0975) ** 1.06)


def test_predict_ultra_switches_exponent():
    b = RaceBasis(pred_5k_s=None, pred_10k_s=None, pred_half_s=None, pred_marathon_s=13500, **B)
    assert predict_run_time(60, b) == round(13500 * (60 / 42.195) ** 1.10)


def test_predict_threshold_fallback_and_none():
    b = RaceBasis(
        pred_5k_s=None,
        pred_10k_s=None,
        pred_half_s=None,
        pred_marathon_s=None,
        captured_on=date(2026, 11, 1),
        threshold_pace_s_km=300,
        hr={},
    )
    assert predict_run_time(42.195, b) == round(42.195 * 300 * 1.09)
    assert predict_run_time(10, b.model_copy(update={"threshold_pace_s_km": None})) is None


def _prof(parts: list[tuple[float, float]]) -> list[ProfilePoint]:
    """Profil synthétique : points tous les 0,05 km depuis le km 0 (alt. 100), parties (longueur km, pente)."""
    pts = [ProfilePoint(km=0.0, ele_m=100.0)]
    start = 0.0
    for length, grade in parts:
        end = start + length
        steps = max(1, round(length / 0.05))
        base = pts[-1].ele_m
        for i in range(1, steps + 1):
            km = end if i == steps else start + i * 0.05
            pts.append(ProfilePoint(km=km, ele_m=base + grade * (km - start) * 1000))
        start = end
    return pts


def test_split_kinds():
    s = split_segments(_prof([(1, 0), (3, 0.10), (1, -0.30), (1, 0)]), 6)
    assert [x.kind for x in s] == ["plat", "montée", "descente", "plat"]
    assert s[1].d_plus_m == pytest.approx(300, abs=15)


def test_short_bump_absorbed():
    s = split_segments(_prof([(2, 0), (0.3, 0.10), (2, 0)]), 4.3)
    assert [x.kind for x in s] == ["plat"]


def test_at_most_25_contiguous():
    s = split_segments(_prof([(0.6, 0.08), (0.6, -0.08)] * 30), 36)
    assert len(s) <= 25
    assert s[0].start_km == 0 and s[-1].end_km == pytest.approx(36)
    assert all(a.end_km == b.start_km for a, b in zip(s, s[1:]))


def test_tiny_flat_course_single_segment():
    s = split_segments(_prof([(0.3, 0)]), 0.3)
    assert len(s) == 1 and s[0].end_km == pytest.approx(0.3)


@pytest.mark.parametrize("dist,n,first", [(10, 10, 1), (42.195, 21, 2), (100, 20, 5), (180, 18, 10)])
def test_slices_without_profile(dist, n, first):
    s = split_segments(None, dist)
    assert len(s) == n and s[0].end_km == first and s[-1].end_km == dist
    assert all(x.kind == "plat" and x.eq_km == pytest.approx(x.end_km - x.start_km) for x in s)
