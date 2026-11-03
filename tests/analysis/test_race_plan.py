from datetime import date

import pytest

from coach.analysis.gpx import ProfilePoint
from coach.analysis.race_plan import (
    LATE,
    NO_TIME,
    STALE,
    AidStation,
    RaceBasis,
    RaceSettings,
    build_race_plan,
    grade_multiplier,
    predict_run_time,
    race_hr_zone,
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


BASIS = RaceBasis(captured_on=date(2026, 11, 1), pred_5k_s=None, pred_10k_s=2880, pred_half_s=None,
                  pred_marathon_s=None, threshold_pace_s_km=None,
                  hr={"Z1": (100, 120), "Z2": (120, 140), "Z3": (140, 160), "Z4": (160, 175), "Z5": (175, 190)})
TODAY = date(2026, 11, 2)


def plan(**kw):
    args = dict(distance_km=10, trail=False, profile=None, basis=BASIS, settings=RaceSettings(), today=TODAY)
    return build_race_plan(**{**args, **kw})


def test_flat_route_falls_back_on_prediction_and_pace_targets():
    p = plan()
    assert p.target_time_s is None and p.reference_time_s == 2880 and len(p.segments) == 10
    s = p.segments[0]
    assert (s.time_s, s.pace_s_km, s.target_kind, s.target_low, s.target_high) == (288, 288, "pace", 283, 293)
    assert p.segments[-1].clock == "08:48" and p.aid_passages == [] and p.nutrition == []


def test_target_time_rescales():
    p = plan(target_time_s=2700)
    assert p.target_time_s == p.reference_time_s == 2700 and p.segments[0].time_s == 270
    assert "predicted_time_s" not in p.model_dump()


def test_climb_slower_than_flat():
    p = plan(trail=True, distance_km=6, profile=_prof([(1, 0), (3, 0.10), (1, -0.30), (1, 0)]))
    flat, up = p.segments[0], p.segments[1]
    assert up.pace_s_km > flat.pace_s_km and up.target_kind == "hr"


STATION = AidStation(km=5, name="Col", kind="complet", cutoff="08:50", stop_min=3)


def test_aid_passage_margin_and_nutrition():
    p = plan(trail=True, settings=RaceSettings(aid_stations=[STATION]))
    assert p.stops_s == 180 and p.reference_time_s == 3060
    a = p.aid_passages[0].passage
    assert (a.elapsed_s, a.clock, a.margin_min, a.status) == (1440, "08:24", 26, "serré")
    assert [(n.from_name, n.to_name, n.duration_s, n.carbs_g, n.water_ml) for n in p.nutrition] == [
        ("Départ", "Col", 1440, 24, 200), ("Col", "Arrivée", 1440, 24, 200)]


def test_late_cutoff_warns_and_capacity_alert():
    st = STATION.model_copy(update={"cutoff": "08:20"})
    p = plan(trail=True, settings=RaceSettings(aid_stations=[st], carry_ml=100))
    assert p.aid_passages[0].passage.status == "hors délai"
    assert LATE.format("Col") in p.warnings and all(n.over_capacity for n in p.nutrition)


def test_passage_and_cutoff_warning_follow_the_target_time():
    st = STATION.model_copy(update={"cutoff": "08:25"})  # prédit 08:24, visé 08:28:30
    p = plan(trail=True, settings=RaceSettings(aid_stations=[st]), target_time_s=3600)
    assert p.aid_passages[0].passage.elapsed_s == 1710
    assert p.aid_passages[0].passage.status == "hors délai" and LATE.format("Col") in p.warnings


def test_target_not_above_stops_rejected():
    with pytest.raises(ValueError, match="arrêts"):
        plan(trail=True, settings=RaceSettings(aid_stations=[STATION]), target_time_s=180)


def test_no_reference_time():
    b = BASIS.model_copy(update={"pred_10k_s": None})
    p = plan(basis=b)
    assert p.reference_time_s is None and p.segments[0].time_s is None and NO_TIME in p.warnings


def test_stale_basis_warns():
    assert STALE.format(date(2026, 11, 1)) in plan(today=date(2026, 12, 5)).warnings


def test_stale_basis_ignored_on_road_with_target():
    late = date(2026, 12, 5)
    assert not any(w.startswith("Données") for w in plan(today=late, target_time_s=2700).warnings)
    assert STALE.format(date(2026, 11, 1)) in plan(today=late, trail=True, target_time_s=2700).warnings


def test_clock_wraps_after_midnight():
    assert plan(settings=RaceSettings(start_time="23:30")).segments[-1].clock == "00:18"


@pytest.mark.parametrize("t,z", [(5000, "Z4"), (10000, "Z3"), (14400, "Z3"), (20000, "Z2")])
def test_race_hr_zone(t, z):
    assert race_hr_zone(t) == z


def test_cutoff_before_start_is_next_day():
    st = STATION.model_copy(update={"cutoff": "02:00"})
    p = plan(trail=True, settings=RaceSettings(start_time="22:00", aid_stations=[st]))
    a = p.aid_passages[0].passage
    assert (a.clock, a.margin_min, a.status) == ("22:24", 216, "ok")
    assert LATE.format("Col") not in p.warnings


def test_negative_margin_floored():
    st = STATION.model_copy(update={"cutoff": "08:28"})  # arrivée visée 08:28:30
    p = plan(trail=True, settings=RaceSettings(aid_stations=[st]), target_time_s=3600)
    t = p.aid_passages[0].passage
    assert (t.margin_min, t.status) == (-1, "hors délai")
