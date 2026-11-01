from coach.analysis.laps import compare_session
from coach.analysis.zones import Zones
from coach.garmin.port import LapSummary
from coach.llm.schemas import RepeatSpec, StepSpec
from tests.llm.factories import make_session

ZONES = Zones(
    pace={"VMA": (220, 235), "récup": (350, 400)},
    hr={"Z5": (171, 190)},
    source=[],
)

# orders Garmin : échauffement 1, groupe 2, actif 3, récup 4, retour au calme 5
INTERVALS = make_session(
    type="VMA",
    target_kind="pace",
    steps=[
        StepSpec(kind="warmup", duration_s=900),
        RepeatSpec(
            repeat=6,
            steps=[
                StepSpec(kind="active", distance_m=400, zone="VMA"),
                StepSpec(kind="recovery", distance_m=200),
            ],
        ),
        StepSpec(kind="cooldown", duration_s=600),
    ],
)
FULL_ORDERS = [1] + [3, 4] * 6 + [5]


def lap(i, order, dur, dist, hr=None):
    return LapSummary(
        index=i,
        duration_s=dur,
        distance_m=dist,
        avg_hr=hr,
        avg_pace_s_km=dur / (dist / 1000) if dist else None,
        step_order=order,
        raw={"x": 1},
    )


def laps_for(orders):
    return [lap(i + 1, o, 100, 400) for i, o in enumerate(orders)]


def test_one_lap_per_step_matches_all():
    result = compare_session(INTERVALS, laps_for(FULL_ORDERS), ZONES)
    assert result.followed_workout is True
    assert result.target_kind == "pace"
    assert len(result.steps) == 14
    assert all(s.done for s in result.steps)
    assert result.laps[0].raw == {}


def test_manual_lap_inside_step_is_merged():
    laps = [lap(1, 1, 300, 1000), lap(2, 1, 300, 1000), lap(3, 3, 90, 400)]
    result = compare_session(INTERVALS, laps, ZONES)
    warmup = result.steps[0]
    assert (warmup.duration_s, warmup.distance_m, warmup.avg_pace_s_km) == (600, 2000, 300)
    assert result.steps[1].done and result.steps[1].distance_m == 400


def test_merged_hr_is_duration_weighted():
    laps = [lap(1, 1, 100, 300, hr=150), lap(2, 1, 300, 900, hr=170)]
    assert compare_session(INTERVALS, laps, ZONES).steps[0].avg_hr == 165


def test_skipped_step_is_not_done():
    result = compare_session(INTERVALS, laps_for([1, 4]), ZONES)
    assert result.followed_workout is True
    assert result.steps[1].done is False  # actif 1 jamais couru
    assert result.steps[1].avg_hr is None and result.steps[1].duration_s is None
    assert result.steps[2].done is True  # récup 1


def test_stopped_early_leaves_remaining_not_done():
    result = compare_session(INTERVALS, laps_for([1, 3, 4]), ZONES)
    assert [s.done for s in result.steps] == [True] * 3 + [False] * 11
    assert len(result.steps) == 14


def test_going_back_falls_back_to_degraded():
    result = compare_session(INTERVALS, laps_for([1, 5, 3]), ZONES)
    assert result.followed_workout is False
    assert result.steps == []
    assert len(result.laps) == 3 and result.laps[0].raw == {}


def test_lap_without_step_order_is_degraded():
    laps = laps_for([1, 3, 4])
    laps[1] = laps[1].model_copy(update={"step_order": None})
    result = compare_session(INTERVALS, laps, ZONES)
    assert result.followed_workout is False and result.steps == []


def test_unknown_step_order_is_degraded():
    result = compare_session(INTERVALS, laps_for([1, 9]), ZONES)
    assert result.followed_workout is False and result.steps == []


def test_no_laps_is_degraded_with_empty_list():
    result = compare_session(INTERVALS, [], ZONES)
    assert result.followed_workout is False
    assert result.steps == [] and result.laps == []


def test_single_step_repeat_laps_are_iterations():
    spec = make_session(steps=[RepeatSpec(repeat=3, steps=[StepSpec(kind="active", duration_s=60)])])
    result = compare_session(spec, laps_for([2, 2, 2]), ZONES)
    assert [(s.iteration, s.done) for s in result.steps] == [(1, True), (2, True), (3, True)]
    merged = compare_session(spec, laps_for([2, 2, 2, 2]), ZONES)
    assert [s.done for s in merged.steps] == [True] * 3
    assert merged.steps[2].duration_s == 200 and merged.steps[0].duration_s == 100


def _one_active(pace_s_km):
    spec = make_session(target_kind="pace", steps=[StepSpec(kind="active", distance_m=1000, zone="VMA")])
    return compare_session(spec, [lap(1, 1, pace_s_km, 1000)], ZONES).steps[0]


def test_pace_verdicts_at_bounds():
    assert _one_active(220).verdict == "in"
    assert _one_active(235).verdict == "in"
    assert _one_active(219).verdict == "fast"
    assert _one_active(236).verdict == "slow"
    step = _one_active(220)
    assert (step.target_low, step.target_high) == (220, 235)


def test_hr_verdicts():
    spec = make_session(target_kind="hr", steps=[StepSpec(kind="active", duration_s=300, zone="Z5")])

    def verdict(hr):
        return compare_session(spec, [lap(1, 1, 300, 1000, hr=hr)], ZONES).steps[0].verdict

    assert verdict(170) == "hr_low"
    assert verdict(191) == "hr_high"
    assert verdict(171) == "in"


def test_no_verdict_without_zone_or_data():
    no_zone = make_session(steps=[StepSpec(kind="active", distance_m=1000)])
    assert compare_session(no_zone, [lap(1, 1, 300, 1000)], ZONES).steps[0].verdict is None

    hr_spec = make_session(target_kind="hr", steps=[StepSpec(kind="active", duration_s=300, zone="Z5")])
    assert compare_session(hr_spec, [lap(1, 1, 300, 1000)], ZONES).steps[0].verdict is None

    pace_spec = make_session(target_kind="pace", steps=[StepSpec(kind="active", distance_m=1000, zone="VMA")])
    laps = [lap(1, 1, 230, 1000)]
    assert compare_session(pace_spec, laps, None).steps[0].verdict is None
    no_pace = ZONES.model_copy(update={"pace": None})
    assert compare_session(pace_spec, laps, no_pace).steps[0].verdict is None


def test_zero_distance_lap_has_no_pace_verdict():
    spec = make_session(target_kind="pace", steps=[StepSpec(kind="recovery", duration_s=60, zone="récup")])
    step = compare_session(spec, [lap(1, 1, 60, 0)], ZONES).steps[0]
    assert step.done and step.verdict is None and step.avg_pace_s_km is None


def test_planned_volume_is_reported():
    result = compare_session(INTERVALS, [lap(1, 1, 900, 2000), lap(2, 3, 90, 412)], ZONES)
    assert result.steps[1].planned_distance_m == 400
    assert result.steps[1].distance_m == 412
    assert result.steps[0].planned_duration_s == 900
