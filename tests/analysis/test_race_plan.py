from datetime import date

import pytest

from coach.analysis.gpx import ProfilePoint
from coach.analysis.race_plan import RaceBasis, grade_multiplier, predict_run_time, step_eq_km


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
