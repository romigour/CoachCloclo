import pytest
from pydantic import ValidationError

from coach.llm.schemas import (
    HARD_TYPES,
    AdjustmentResponse,
    Change,
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
        adj, editable_ids={1, 2}, current_week=3, sessions_per_week=4, counts_by_week={3: 4}, pace_available=True
    )


def test_validate_adjustment_rejects_add_in_past_week():
    adj = _adj(Change(op="add", session=make_session(week_index=2), reason="r"))
    assert validate_adjustment(
        adj, editable_ids=set(), current_week=3, sessions_per_week=4, counts_by_week={}, pace_available=True
    )


def test_validate_adjustment_week_overflow_after_add():
    adj = _adj(Change(op="add", session=make_session(week_index=3), reason="r"))
    errs = validate_adjustment(
        adj, editable_ids=set(), current_week=3, sessions_per_week=4, counts_by_week={3: 4}, pace_available=True
    )
    assert any("semaine 3" in e for e in errs)
    ok = validate_adjustment(
        adj, editable_ids=set(), current_week=3, sessions_per_week=4, counts_by_week={3: 3}, pace_available=True
    )
    assert ok == []


def test_validate_adjustment_remove_frees_slot_when_week_known():
    adj = _adj(
        Change(op="remove", session_id=5, reason="r"),
        Change(op="add", session=make_session(week_index=3), reason="r"),
    )
    kwargs = dict(editable_ids={5}, current_week=3, sessions_per_week=4, counts_by_week={3: 4}, pace_available=True)
    assert validate_adjustment(adj, **kwargs)
    assert validate_adjustment(adj, **kwargs, week_of_session={5: 3}) == []


def test_validate_adjustment_modify_moves_week():
    adj = _adj(Change(op="modify", session_id=5, session=make_session(week_index=4), reason="r"))
    errs = validate_adjustment(
        adj,
        editable_ids={5},
        current_week=3,
        sessions_per_week=4,
        counts_by_week={3: 1, 4: 4},
        pace_available=True,
        week_of_session={5: 3},
    )
    assert any("semaine 4" in e for e in errs)


def test_validate_adjustment_pace_without_data():
    adj = _adj(Change(op="add", session=make_session(week_index=3, target_kind="pace"), reason="r"))
    assert validate_adjustment(
        adj, editable_ids=set(), current_week=3, sessions_per_week=4, counts_by_week={}, pace_available=False
    )


def test_validate_plan_session_week_must_match_parent_week():
    plan = make_plan(n_weeks=2, per_week=[1, 1])
    plan.weeks[1].sessions[0].week_index = 1
    errs = validate_plan(plan, n_weeks=2, sessions_per_week=3, pace_available=True)
    assert any("semaine 2" in e and "week_index" in e for e in errs)


_ADJ_KW = dict(current_week=3, sessions_per_week=4, counts_by_week={3: 2, 4: 1}, pace_available=True)


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
