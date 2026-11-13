import pytest
from pydantic import ValidationError

from coach.llm.schemas import (
    HARD_TYPES,
    AdjustmentResponse,
    Change,
    GoalEstimate,
    PlanResponse,
    RepeatSpec,
    StepSpec,
    validate_adjustment,
    validate_plan,
)
from tests.llm.factories import make_plan, make_session


def test_step_requires_exactly_one_length():
    with pytest.raises(ValidationError):
        StepSpec(kind="active", duration_s=60, distance_m=200, zone="VMA")
    with pytest.raises(ValidationError):
        StepSpec(kind="active", zone="VMA")


def test_repeat_bounds():
    step = StepSpec(kind="active", duration_s=60, zone="VMA")
    with pytest.raises(ValidationError):
        RepeatSpec(repeat=1, steps=[step])
    with pytest.raises(ValidationError):
        RepeatSpec(repeat=31, steps=[step])
    with pytest.raises(ValidationError):
        RepeatSpec(repeat=5, steps=[])


def test_zone_must_match_target_kind():
    with pytest.raises(ValidationError):
        make_session(target_kind="hr", steps=[StepSpec(kind="active", duration_s=600, zone="seuil")])
    with pytest.raises(ValidationError):
        make_session(target_kind="pace", steps=[StepSpec(kind="active", duration_s=600, zone="Z3")])


def test_zone_inside_repeat_is_checked_and_none_zone_ok():
    rep = RepeatSpec(repeat=4, steps=[StepSpec(kind="active", distance_m=400, zone="Z4")])
    with pytest.raises(ValidationError):
        make_session(target_kind="pace", steps=[rep])
    s = make_session(steps=[StepSpec(kind="warmup", duration_s=600)])
    assert s.steps[0].zone is None


def test_json_roundtrip_picks_right_union_member():
    session = make_session(
        type="VMA",
        steps=[
            StepSpec(kind="warmup", duration_s=600, zone="Z2"),
            RepeatSpec(
                repeat=6,
                steps=[
                    StepSpec(kind="active", duration_s=60, zone="Z5"),
                    StepSpec(kind="recovery", duration_s=60, zone="Z1"),
                ],
            ),
        ],
    )
    plan = make_plan(1, [0])
    plan.weeks[0].sessions.append(session)
    back = PlanResponse.model_validate_json(plan.model_dump_json())
    assert back == plan
    steps = back.weeks[0].sessions[0].steps
    assert isinstance(steps[0], StepSpec) and isinstance(steps[1], RepeatSpec)


def test_extra_fields_forbidden():
    with pytest.raises(ValidationError):
        StepSpec(kind="active", duration_s=60, zone="VMA", bogus=1)


def test_hard_types():
    assert HARD_TYPES == {"seuil", "VMA", "côtes", "sortie_longue"}


def test_change_shape():
    s = make_session()
    with pytest.raises(ValidationError):
        Change(op="modify", session_id=1, reason="r")
    with pytest.raises(ValidationError):
        Change(op="add", session_id=1, session=s, reason="r")
    with pytest.raises(ValidationError):
        Change(op="remove", session_id=1, session=s, reason="r")
    with pytest.raises(ValidationError):
        Change(op="remove", reason="r")
    Change(op="modify", session_id=1, session=s, reason="r")
    Change(op="add", session=s, reason="r")
    Change(op="remove", session_id=1, reason="r")


def test_validate_plan_ok():
    plan = make_plan(n_weeks=2, per_week=[3, 3])
    assert validate_plan(plan, n_weeks=2, sessions_per_week=3, pace_available=True) == []


def test_validate_plan_too_many_sessions():
    plan = make_plan(n_weeks=2, per_week=[3, 4])
    errs = validate_plan(plan, n_weeks=2, sessions_per_week=3, pace_available=True)
    assert any("semaine 2" in e for e in errs)


def test_validate_plan_week_numbering():
    plan = make_plan(n_weeks=2, per_week=[1, 1])
    plan.weeks[1].week_index = 3
    assert validate_plan(plan, n_weeks=2, sessions_per_week=3, pace_available=True)
    assert validate_plan(make_plan(1, [1]), n_weeks=2, sessions_per_week=3, pace_available=True)


def test_validate_plan_duplicate_order():
    plan = make_plan(n_weeks=1, per_week=[2])
    plan.weeks[0].sessions[1].order = 1
    errs = validate_plan(plan, n_weeks=1, sessions_per_week=3, pace_available=True)
    assert any("semaine 1" in e for e in errs)


def test_validate_plan_pace_without_data():
    assert validate_plan(
        make_plan(n_weeks=1, per_week=[1], target_kind="pace"),
        n_weeks=1,
        sessions_per_week=3,
        pace_available=False,
    )
    assert not validate_plan(
        make_plan(n_weeks=1, per_week=[1], target_kind="pace"),
        n_weeks=1,
        sessions_per_week=3,
        pace_available=True,
    )


def _adj(*changes):
    return AdjustmentResponse(analysis="x", changes=list(changes))


def test_validate_adjustment_rejects_unknown_or_done_session():
    adj = _adj(Change(op="remove", session_id=99, reason="r"))
    assert validate_adjustment(
        adj, editable_ids={1, 2}, current_week=3, sessions_per_week=4, n_weeks=52, counts_by_week={3: 4}, pace_available=True
    )


def test_validate_adjustment_rejects_add_in_past_week():
    adj = _adj(Change(op="add", session=make_session(week_index=2), reason="r"))
    assert validate_adjustment(
        adj, editable_ids=set(), current_week=3, sessions_per_week=4, n_weeks=52, counts_by_week={}, pace_available=True
    )


def test_validate_adjustment_week_overflow_after_add():
    adj = _adj(Change(op="add", session=make_session(week_index=3), reason="r"))
    errs = validate_adjustment(
        adj, editable_ids=set(), current_week=3, sessions_per_week=4, n_weeks=52, counts_by_week={3: 4}, pace_available=True
    )
    assert any("semaine 3" in e for e in errs)
    ok = validate_adjustment(
        adj, editable_ids=set(), current_week=3, sessions_per_week=4, n_weeks=52, counts_by_week={3: 3}, pace_available=True
    )
    assert ok == []


def test_validate_adjustment_remove_frees_slot_when_week_known():
    adj = _adj(
        Change(op="remove", session_id=5, reason="r"),
        Change(op="add", session=make_session(week_index=3), reason="r"),
    )
    kwargs = dict(editable_ids={5}, current_week=3, sessions_per_week=4, n_weeks=52, counts_by_week={3: 4}, pace_available=True)
    assert validate_adjustment(adj, **kwargs)
    assert validate_adjustment(adj, **kwargs, week_of_session={5: 3}) == []


def test_validate_adjustment_modify_moves_week():
    adj = _adj(Change(op="modify", session_id=5, session=make_session(week_index=4), reason="r"))
    errs = validate_adjustment(
        adj,
        editable_ids={5},
        current_week=3,
        sessions_per_week=4,
        n_weeks=52, counts_by_week={3: 1, 4: 4},
        pace_available=True,
        week_of_session={5: 3},
    )
    assert any("semaine 4" in e for e in errs)


def test_validate_adjustment_pace_without_data():
    adj = _adj(Change(op="add", session=make_session(week_index=3, target_kind="pace"), reason="r"))
    assert validate_adjustment(
        adj, editable_ids=set(), current_week=3, sessions_per_week=4, n_weeks=52, counts_by_week={}, pace_available=False
    )


def test_validate_plan_session_week_must_match_parent_week():
    plan = make_plan(n_weeks=2, per_week=[1, 1])
    plan.weeks[1].sessions[0].week_index = 1
    errs = validate_plan(plan, n_weeks=2, sessions_per_week=3, pace_available=True)
    assert any("semaine 2" in e and "week_index" in e for e in errs)


_ADJ_KW = dict(current_week=3, sessions_per_week=4, n_weeks=52, counts_by_week={3: 2, 4: 1}, pace_available=True)


def test_validate_adjustment_rejects_duplicate_session_ids():
    adj = _adj(
        Change(op="modify", session_id=5, session=make_session(week_index=3), reason="r"),
        Change(op="remove", session_id=5, reason="r"),
    )
    errs = validate_adjustment(adj, editable_ids={5}, week_of_session={5: 3}, **_ADJ_KW)
    assert any("5" in e and "plusieurs" in e for e in errs)


def test_validate_adjustment_rejects_modify_into_past_week():
    adj = _adj(Change(op="modify", session_id=5, session=make_session(week_index=2), reason="r"))
    errs = validate_adjustment(adj, editable_ids={5}, week_of_session={5: 3}, **_ADJ_KW)
    assert any("semaine 2" in e for e in errs)


def test_validate_adjustment_exported_session_cannot_change_week():
    adj = _adj(Change(op="modify", session_id=5, session=make_session(week_index=4), reason="r"))
    kwargs = dict(editable_ids={5}, week_of_session={5: 3}, **_ADJ_KW)
    assert validate_adjustment(adj, **kwargs) == []  # séance todo : changement de semaine permis
    errs = validate_adjustment(adj, **kwargs, exported_ids={5})
    assert any("exportée" in e for e in errs)
    same_week = _adj(Change(op="modify", session_id=5, session=make_session(week_index=3), reason="r"))
    assert validate_adjustment(same_week, **kwargs, exported_ids={5}) == []


def test_validate_plan_requires_estimate():
    plan = make_plan(n_weeks=2, per_week=[1, 1])
    errs = validate_plan(plan, n_weeks=2, sessions_per_week=3, pace_available=True, estimate_min_s={1: 1000})
    assert errs == ["estimated_times : estimation manquante pour l'objectif 1"]


def test_validate_plan_rejects_implausible_estimate():
    plan = make_plan(n_weeks=2, per_week=[1, 1], estimated_time_s=600)
    errs = validate_plan(plan, n_weeks=2, sessions_per_week=3, pace_available=True, estimate_min_s={1: 1000})
    assert errs == ["estimated_times : 600 s invraisemblable pour l'objectif 1 (au moins 1000 s)"]


def test_validate_plan_accepts_plausible_estimate():
    plan = make_plan(n_weeks=2, per_week=[1, 1], estimated_time_s=1000)
    assert validate_plan(plan, n_weeks=2, sessions_per_week=3, pace_available=True, estimate_min_s={1: 1000}) == []


def test_validate_plan_ignores_estimate_when_not_required():
    plan = make_plan(n_weeks=2, per_week=[1, 1])
    assert plan.estimated_times == []
    assert validate_plan(plan, n_weeks=2, sessions_per_week=3, pace_available=True, estimate_min_s=None) == []
    assert validate_plan(plan, n_weeks=2, sessions_per_week=3, pace_available=True, estimate_min_s={}) == []


def test_validate_plan_estimates_per_goal():
    """Chaque objectif attendu a son estimation, au-dessus de son propre plancher."""
    plan = make_plan(n_weeks=2, per_week=[1, 1])
    plan.estimated_times = [GoalEstimate(goal_id=3, seconds=5000), GoalEstimate(goal_id=9, seconds=100)]
    errs = validate_plan(
        plan, n_weeks=2, sessions_per_week=3, pace_available=True, estimate_min_s={3: 1500, 5: 3000, 9: 1500}
    )
    assert errs == [
        "estimated_times : estimation manquante pour l'objectif 5",
        "estimated_times : 100 s invraisemblable pour l'objectif 9 (au moins 1500 s)",
    ]


def test_validate_adjustment_estimates_per_goal():
    adj = _adj()
    kw = dict(editable_ids=set(), **_ADJ_KW)
    assert validate_adjustment(adj, **kw) == []
    assert validate_adjustment(adj, **kw, estimate_min_s={4: 1500}) == [
        "estimated_times : estimation manquante pour l'objectif 4"
    ]
    adj.estimated_times = [GoalEstimate(goal_id=4, seconds=1499)]
    assert validate_adjustment(adj, **kw, estimate_min_s={4: 1500}) == [
        "estimated_times : 1499 s invraisemblable pour l'objectif 4 (au moins 1500 s)"
    ]
    adj.estimated_times = [GoalEstimate(goal_id=4, seconds=1500)]
    assert validate_adjustment(adj, **kw, estimate_min_s={4: 1500}) == []


def test_responses_carry_estimated_times():
    assert "estimated_time_s" not in PlanResponse.model_fields
    assert AdjustmentResponse(analysis="a", changes=[]).estimated_times == []
    with pytest.raises(ValidationError):
        GoalEstimate(goal_id=1, seconds=10, extra=1)


def test_adjustment_rejects_week_beyond_plan():
    adj = _adj(Change(op="add", session=make_session(week_index=15), reason="r"))
    errs = validate_adjustment(
        adj, editable_ids=set(), current_week=3, sessions_per_week=4, counts_by_week={},
        pace_available=True, n_weeks=14,
    )
    assert any("semaine 15, au-delà de la dernière semaine du plan (14)" in e for e in errs)


def test_session_sport_defaults_to_run_and_old_change_loads():
    assert make_session().sport == "run"
    assert make_session(sport="bike").sport == "bike"
    old = make_session().model_dump(mode="json")
    del old["sport"]  # ancienne proposition en base : sans champ sport
    change = Change.model_validate({"op": "modify", "session_id": 1, "session": old, "reason": "r"})
    assert change.session.sport == "run"
    with pytest.raises(ValidationError):
        make_session(sport="swim")


def test_validate_plan_first_week_and_fixed_counts():
    # semaines 3 et 4 seulement ; deux séances fixes en semaine 3 sur 3 par semaine
    plan = make_plan(4, [0, 0, 1, 3])
    plan.weeks = plan.weeks[2:]
    kwargs = dict(n_weeks=4, sessions_per_week=3, pace_available=True, first_week=3)
    assert validate_plan(plan, **kwargs, fixed_counts={3: 2}) == []
    errs = validate_plan(plan, **kwargs, fixed_counts={3: 2, 4: 1})
    assert errs == ["semaine 4 : 3 séances pour 2 demandées (1 fixée)"]
    errs = validate_plan(make_plan(4, [1, 1, 1, 1]), **kwargs)
    assert any("numérotées de 3 à 4" in e for e in errs)
