from datetime import date

from coach.analysis.compliance import (
    CYCLING_TYPES,
    RUNNING_TYPES,
    activity_types_for,
    hard_session_warnings,
    mark_missed,
)
from tests.plan.factories import make_db_session, make_cycle

TUE = date(2026, 11, 10)  # semaine 3 : 2026-11-09 .. 2026-11-15
WED = date(2026, 11, 11)


def _session(id_, status="exported", scheduled=TUE, week=3, **kw):
    s = make_db_session(1, week_index=week, **kw)
    s.id = id_
    s.status = status
    s.scheduled_date = scheduled
    s.est_duration_min = 45.0
    return s


def test_mark_missed_only_finished_weeks():
    cycle = make_cycle()
    old = _session(1, status="todo", scheduled=None, week=2)
    old_exported = _session(2, status="exported", scheduled=date(2026, 11, 3), week=2)
    current = _session(3, status="todo", scheduled=None, week=3)
    done = _session(4, status="done", scheduled=None, week=2)
    missed = mark_missed([old, old_exported, current, done], cycle, date(2026, 11, 11))
    assert sorted(missed) == [1, 2]


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


def test_mark_missed_includes_sync_error_but_not_pending_removal():
    cycle = make_cycle()
    err = _session(1, status="sync_error", scheduled=date(2026, 11, 3), week=2)
    removing = _session(2, status="sync_error", scheduled=date(2026, 11, 3), week=2)
    removing.pending_removal = True
    assert mark_missed([err, removing], cycle, date(2026, 11, 11)) == [1]


def test_sync_error_awaiting_cleanup_never_missed():
    # d'anciens ids Garmin restent à nettoyer : la synchro (sans écriture Garmin) n'y touche pas
    cycle = make_cycle()
    s = _session(1, status="sync_error", scheduled=date(2026, 11, 3), week=2)
    s.pending_old_workout_id = 1000
    assert mark_missed([s], cycle, date(2026, 11, 11)) == []
    s.pending_old_workout_id, s.pending_old_schedule_id = None, 5000
    assert mark_missed([s], cycle, date(2026, 11, 11)) == []


def test_warning_counts_scheduled_sync_error_as_exported():
    vma = _session(1, status="todo", type="VMA", scheduled=None)
    err = _session(2, status="sync_error", type="seuil", scheduled=TUE, title="Seuil")
    assert hard_session_warnings(vma, WED, [err])
    err.pending_removal = True
    assert not hard_session_warnings(vma, WED, [err])


def test_activity_types_for_sport():
    assert activity_types_for("run") == RUNNING_TYPES
    assert activity_types_for("bike") == CYCLING_TYPES
    assert "indoor_cycling" in CYCLING_TYPES
