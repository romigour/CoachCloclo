from datetime import date

from coach.analysis.compliance import (
    estimate_duration_min,
    hard_session_warnings,
    mark_missed,
    match_activities,
)
from coach.llm.schemas import RepeatSpec, StepSpec
from tests.llm.factories import make_session
from tests.plan.factories import make_activity, make_db_session, make_goal

TUE = date(2026, 11, 10)  # semaine 3 : 2026-11-09 .. 2026-11-15
WED = date(2026, 11, 11)


def _session(id_, status="exported", scheduled=TUE, week=3, **kw):
    s = make_db_session(1, week_index=week, **kw)
    s.id = id_
    s.status = status
    s.scheduled_date = scheduled
    s.est_duration_min = 45.0
    return s


def _act(id_, d=TUE, **kw):
    a = make_activity(garmin_activity_id=id_, date=d, **kw)
    a.id = id_
    return a


def test_exported_session_matches_adjacent_day():
    s = _session(1, scheduled=TUE)
    a = _act(10, d=WED)
    assert match_activities([s], [a], make_goal()) == [(1, 10)]


def test_cycling_ignored():
    s = _session(1)
    a = _act(10, type_key="cycling")
    assert match_activities([s], [a], make_goal()) == []


def test_two_runs_same_day_pick_closest_duration():
    s = _session(1)
    short = _act(10, duration_s=20 * 60)
    long_ = _act(11, duration_s=50 * 60)
    assert match_activities([s], [short, long_], make_goal()) == [(1, 11)]


def test_todo_session_matches_within_week_only():
    goal = make_goal()
    s = _session(1, status="todo", scheduled=None)
    same_week = _act(10, d=date(2026, 11, 14))
    other_week = _act(11, d=date(2026, 11, 17))
    assert match_activities([s], [other_week], goal) == []
    assert match_activities([s], [same_week, other_week], goal) == [(1, 10)]


def test_activity_used_once():
    s1 = _session(1, scheduled=TUE)
    s2 = _session(2, scheduled=TUE)
    a = _act(10)
    pairs = match_activities([s1, s2], [a], make_goal())
    assert len(pairs) == 1
    assert pairs[0][1] == 10


def test_already_attached_activity_ignored():
    s = _session(1)
    a = _act(10)
    a.session_id = 99
    assert match_activities([s], [a], make_goal()) == []


def test_exported_processed_before_todo():
    goal = make_goal()
    todo = _session(1, status="todo", scheduled=None)
    exported = _session(2, status="exported", scheduled=TUE)
    a = _act(10)
    assert match_activities([todo, exported], [a], goal) == [(2, 10)]


def test_estimate_falls_back_when_est_missing():
    s = _session(1)
    s.est_duration_min = None
    a = _act(10, duration_s=600)
    assert match_activities([s], [a], make_goal()) == [(1, 10)]


def test_mark_missed_only_finished_weeks():
    goal = make_goal()
    old = _session(1, status="todo", scheduled=None, week=2)
    old_exported = _session(2, status="exported", scheduled=date(2026, 11, 3), week=2)
    current = _session(3, status="todo", scheduled=None, week=3)
    done = _session(4, status="done", scheduled=None, week=2)
    missed = mark_missed([old, old_exported, current, done], goal, date(2026, 11, 11))
    assert sorted(missed) == [1, 2]


def test_estimate_duration_min():
    spec = make_session(
        steps=[
            StepSpec(kind="warmup", duration_s=600, zone="Z2"),
            RepeatSpec(
                repeat=3,
                steps=[
                    StepSpec(kind="active", duration_s=120, zone="Z4"),
                    StepSpec(kind="recovery", distance_m=500, zone="Z1"),
                ],
            ),
        ]
    )
    s = make_db_session(1, steps=spec.steps)
    assert s.est_duration_min is None
    # 600 + 3 * (120 + 500 m * 0.36 s/m = 180) = 1500 s = 25 min
    assert estimate_duration_min(s) == 25.0


def test_warning_consecutive_hard_days():
    vma = _session(1, status="todo", type="VMA", scheduled=None)
    ef = _session(2, status="todo", type="EF", scheduled=None)
    seuil = _session(3, type="seuil", scheduled=TUE, title="Seuil 3x10")
    msgs = hard_session_warnings(vma, WED, [seuil])
    assert msgs == ["Séance dure à moins de 48 h de « Seuil 3x10 » (2026-11-10)"]
    assert not hard_session_warnings(vma, date(2026, 11, 12), [seuil])
    assert not hard_session_warnings(ef, WED, [seuil])


def test_warning_ignores_same_session():
    vma = _session(1, type="VMA", scheduled=TUE)
    assert not hard_session_warnings(vma, TUE, [vma])


def test_sync_error_session_with_date_matches_like_exported():
    s = _session(1, status="sync_error")
    a = _act(10)
    assert match_activities([s], [a], make_goal()) == [(1, 10)]


def test_sync_error_pending_removal_not_matched():
    s = _session(1, status="sync_error")
    s.pending_removal = True
    assert match_activities([s], [_act(10)], make_goal()) == []


def test_mark_missed_includes_sync_error_but_not_pending_removal():
    goal = make_goal()
    err = _session(1, status="sync_error", scheduled=date(2026, 11, 3), week=2)
    removing = _session(2, status="sync_error", scheduled=date(2026, 11, 3), week=2)
    removing.pending_removal = True
    assert mark_missed([err, removing], goal, date(2026, 11, 11)) == [1]
