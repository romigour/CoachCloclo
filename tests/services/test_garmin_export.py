import json
from datetime import date

import pytest

from coach.analysis.zones import compute_zones
from coach.garmin.port import FakeGarminClient, GarminAuthRequired, GarminUnavailable
from coach.llm.schemas import Change
from coach.plan.models import AthleteSnapshot, Goal, Proposal
from coach.services import CoachError
from coach.services.garmin_export import (
    ExportError,
    apply_proposal,
    check_export,
    export_session,
    move_session,
    reject_proposal,
    retry_sync_error,
    unschedule_session,
)
from tests.llm.factories import make_session
from tests.plan.factories import make_db_session, make_goal

ZONES = compute_zones(
    threshold_pace_s_km=300, pred_10k_s=None, garmin_hr_zones=None, hr_max=190, hr_rest=50
)
D = date(2026, 11, 10)  # mardi de la semaine 3


@pytest.fixture
def fake_garmin():
    return FakeGarminClient()


@pytest.fixture
def goal(repo) -> Goal:
    repo.add(AthleteSnapshot(date=date(2026, 11, 1), zones_json=ZONES.model_dump_json()))
    return repo.add(make_goal())


@pytest.fixture
def session_w3(repo, goal):
    return repo.add(make_db_session(goal.id, week_index=3))


@pytest.fixture
def exported_session(repo, fake_garmin, session_w3):
    export_session(repo, fake_garmin, session_w3.id, D)
    fake_garmin.calls.clear()
    return repo.session(session_w3.id)


def proposal_of(repo, *changes: Change) -> Proposal:
    return repo.add(
        Proposal(
            analysis="a",
            changes_json=json.dumps([c.model_dump(mode="json") for c in changes]),
        )
    )


def modify(session_id, **overrides) -> Change:
    spec = make_session(week_index=3, title="Nouvelle séance", **overrides)
    return Change(op="modify", session_id=session_id, session=spec, reason="r")


def test_export_schedules_on_chosen_day(repo, fake_garmin, session_w3):
    export_session(repo, fake_garmin, session_w3.id, D)
    s = repo.session(session_w3.id)
    assert list(fake_garmin.calendar) == [D] and len(fake_garmin.calendar[D]) == 1
    assert s.status == "exported" and s.scheduled_date == D
    assert "S3 – Sortie facile" in json.dumps(fake_garmin.workouts[s.garmin_workout_id], ensure_ascii=False)
    assert fake_garmin.schedules[s.garmin_schedule_id] == (s.garmin_workout_id, D)


def test_export_outside_week_rejected(repo, fake_garmin, session_w3):
    with pytest.raises(ExportError, match="semaine"):
        export_session(repo, fake_garmin, session_w3.id, date(2026, 11, 16))
    assert fake_garmin.calls == [] and repo.session(session_w3.id).status == "todo"
    assert issubclass(ExportError, CoachError)


def test_export_without_snapshot_rejected(repo, fake_garmin):
    g = repo.add(make_goal())
    s = repo.add(make_db_session(g.id, week_index=3))
    with pytest.raises(ExportError, match="Synchronise"):
        export_session(repo, fake_garmin, s.id, D)
    assert fake_garmin.calls == []


def test_export_requires_todo(repo, fake_garmin, exported_session):
    with pytest.raises(ExportError):
        export_session(repo, fake_garmin, exported_session.id, D)


def test_export_returns_48h_warning(repo, fake_garmin, goal):
    a = repo.add(make_db_session(goal.id, week_index=3, order=1, type="VMA", title="VMA"))
    b = repo.add(make_db_session(goal.id, week_index=3, order=2, type="seuil", title="Seuil"))
    assert export_session(repo, fake_garmin, a.id, D) == []
    assert check_export(repo, b.id, date(2026, 11, 11)) != []
    n = len(fake_garmin.calls)
    warnings = export_session(repo, fake_garmin, b.id, date(2026, 11, 11))
    assert len(warnings) == 1 and "VMA" in warnings[0]
    assert len(fake_garmin.calls) == n + 2
    assert check_export(repo, b.id, date(2026, 11, 14)) == []


def test_check_export_writes_nothing(repo, fake_garmin, session_w3):
    assert check_export(repo, session_w3.id, D) == []
    assert fake_garmin.calls == [] and repo.session(session_w3.id).status == "todo"


def test_export_schedule_failure_deletes_upload(repo, goal, session_w3):
    g = FakeGarminClient(fail_on={"schedule"})
    with pytest.raises(GarminUnavailable):
        export_session(repo, g, session_w3.id, D)
    s = repo.session(session_w3.id)
    assert g.workouts == {} and s.status == "todo" and s.garmin_workout_id is None


def test_export_auth_error_propagates(repo, goal, session_w3):
    class Auth(FakeGarminClient):
        def upload_workout(self, workout):
            raise GarminAuthRequired("x")

    with pytest.raises(GarminAuthRequired):
        export_session(repo, Auth(), session_w3.id, D)
    assert repo.session(session_w3.id).status == "todo"


def test_move_and_unschedule(repo, fake_garmin, exported_session):
    new_day = date(2026, 11, 12)
    move_session(repo, fake_garmin, exported_session.id, new_day)
    assert list(fake_garmin.calendar) == [new_day]
    assert repo.session(exported_session.id).scheduled_date == new_day
    with pytest.raises(ExportError):
        move_session(repo, fake_garmin, exported_session.id, date(2026, 11, 20))
    unschedule_session(repo, fake_garmin, exported_session.id)
    s = repo.session(exported_session.id)
    assert fake_garmin.calendar == {} and fake_garmin.workouts == {}
    assert s.status == "todo" and s.scheduled_date is None
    assert s.garmin_workout_id is None and s.garmin_schedule_id is None


def test_move_requires_exported(repo, fake_garmin, session_w3):
    with pytest.raises(ExportError):
        move_session(repo, fake_garmin, session_w3.id, D)


def test_apply_proposal_replaces_exported_at_same_date(repo, fake_garmin, exported_session):
    old_w, old_s = exported_session.garmin_workout_id, exported_session.garmin_schedule_id
    p = proposal_of(repo, modify(exported_session.id))
    assert apply_proposal(repo, fake_garmin, p.id) == []
    s = repo.session(exported_session.id)
    assert s.status == "exported" and s.scheduled_date == D and s.title == "Nouvelle séance"
    assert s.garmin_workout_id != old_w and s.garmin_schedule_id != old_s
    assert list(fake_garmin.workouts) == [s.garmin_workout_id]
    assert fake_garmin.calendar == {D: [s.garmin_schedule_id]}
    assert fake_garmin.calls == ["upload_workout", "schedule", "unschedule", "delete_workout"]
    assert s.pending_old_workout_id is None and s.pending_old_schedule_id is None
    assert repo.pending_proposal() is None


def test_replace_failure_keeps_old_workout(repo, fake_garmin, exported_session):
    old_w, old_s = exported_session.garmin_workout_id, exported_session.garmin_schedule_id
    fake_garmin.fail_on = {"schedule"}
    p = proposal_of(repo, modify(exported_session.id))
    ids = apply_proposal(repo, fake_garmin, p.id)
    assert ids == [exported_session.id] and old_w in fake_garmin.workouts
    assert fake_garmin.calendar == {D: [old_s]} and list(fake_garmin.workouts) == [old_w]
    s = repo.session(exported_session.id)
    assert s.status == "sync_error" and s.sync_error
    assert s.title == "Nouvelle séance"
    assert (s.pending_old_workout_id, s.pending_old_schedule_id) == (old_w, old_s)
    # reprise
    fake_garmin.fail_on.clear()
    retry_sync_error(repo, fake_garmin, s.id)
    s = repo.session(s.id)
    assert s.status == "exported" and s.sync_error is None
    assert fake_garmin.calendar == {D: [s.garmin_schedule_id]}
    assert list(fake_garmin.workouts) == [s.garmin_workout_id]


def test_cleanup_failure_keeps_old_ids_for_retry(repo, fake_garmin, exported_session):
    old_w, old_s = exported_session.garmin_workout_id, exported_session.garmin_schedule_id
    fake_garmin.fail_on = {"unschedule"}
    p = proposal_of(repo, modify(exported_session.id))
    assert apply_proposal(repo, fake_garmin, p.id) == [exported_session.id]
    s = repo.session(exported_session.id)
    assert s.status == "sync_error" and s.garmin_schedule_id is not None
    assert s.pending_old_schedule_id == old_s and s.pending_old_workout_id == old_w
    new_w = s.garmin_workout_id
    fake_garmin.fail_on.clear()
    fake_garmin.calls.clear()
    retry_sync_error(repo, fake_garmin, s.id)
    assert fake_garmin.calls == ["unschedule", "delete_workout"]  # pas de nouvel upload
    s = repo.session(s.id)
    assert s.status == "exported" and s.garmin_workout_id == new_w
    assert list(fake_garmin.workouts) == [new_w]


def test_retry_auth_error_before_change_propagates(repo, fake_garmin, exported_session):
    fake_garmin.fail_on = {"schedule"}
    p = proposal_of(repo, modify(exported_session.id))
    apply_proposal(repo, fake_garmin, p.id)

    class Auth(FakeGarminClient):
        def upload_workout(self, workout):
            raise GarminAuthRequired("x")

    with pytest.raises(GarminAuthRequired):
        retry_sync_error(repo, Auth(), exported_session.id)
    assert repo.session(exported_session.id).status == "sync_error"


def test_retry_requires_sync_error(repo, fake_garmin, session_w3):
    with pytest.raises(ExportError):
        retry_sync_error(repo, fake_garmin, session_w3.id)


def test_remove_exported_cleans_garmin_then_deletes_row(repo, fake_garmin, exported_session):
    p = proposal_of(repo, Change(op="remove", session_id=exported_session.id, reason="r"))
    assert apply_proposal(repo, fake_garmin, p.id) == []
    assert fake_garmin.calls == ["unschedule", "delete_workout"]
    assert fake_garmin.calendar == {} and fake_garmin.workouts == {}
    with pytest.raises(KeyError):
        repo.session(exported_session.id)


def test_remove_exported_failure_keeps_row_in_sync_error(repo, fake_garmin, exported_session):
    fake_garmin.fail_on = {"delete_workout"}
    p = proposal_of(repo, Change(op="remove", session_id=exported_session.id, reason="r"))
    assert apply_proposal(repo, fake_garmin, p.id) == [exported_session.id]
    s = repo.session(exported_session.id)
    assert s.status == "sync_error" and s.sync_error and s.pending_removal
    fake_garmin.fail_on.clear()
    retry_sync_error(repo, fake_garmin, s.id)
    with pytest.raises(KeyError):
        repo.session(s.id)
    assert fake_garmin.workouts == {}


def test_todo_change_makes_no_garmin_call(repo, fake_garmin, goal, session_w3):
    other = repo.add(make_db_session(goal.id, week_index=3, order=2))
    added = Change(op="add", session=make_session(week_index=3, order=3, title="Ajoutée"), reason="r")
    p = proposal_of(
        repo,
        modify(session_w3.id),
        Change(op="remove", session_id=other.id, reason="r"),
        added,
    )
    assert apply_proposal(repo, fake_garmin, p.id) == []
    assert fake_garmin.calls == []
    s = repo.session(session_w3.id)
    assert s.title == "Nouvelle séance" and s.status == "todo" and s.id == session_w3.id
    week = repo.sessions(goal.id, 3)
    assert [x.title for x in week] == ["Nouvelle séance", "Ajoutée"]
    assert week[1].status == "todo"


def test_apply_rolls_back_on_unknown_session(repo, fake_garmin, goal, session_w3):
    p = proposal_of(repo, modify(session_w3.id), modify(9999))
    with pytest.raises(ExportError):
        apply_proposal(repo, fake_garmin, p.id)
    assert repo.session(session_w3.id).title == "Sortie facile"
    assert repo.pending_proposal().id == p.id


def test_proposal_must_be_pending(repo, fake_garmin, session_w3):
    p = proposal_of(repo, modify(session_w3.id))
    apply_proposal(repo, fake_garmin, p.id)
    with pytest.raises(ExportError):
        apply_proposal(repo, fake_garmin, p.id)
    with pytest.raises(ExportError):
        reject_proposal(repo, p.id)


def test_reject_changes_nothing(repo, fake_garmin, session_w3):
    p = proposal_of(repo, modify(session_w3.id))
    reject_proposal(repo, p.id)
    assert repo.session(session_w3.id).title == "Sortie facile"
    assert repo.pending_proposal() is None and fake_garmin.calls == []
    with pytest.raises(ExportError):
        apply_proposal(repo, fake_garmin, p.id)


def _sync_error_session(repo, fake_garmin, exported_session):
    fake_garmin.fail_on = {"schedule"}
    p = proposal_of(repo, modify(exported_session.id))
    apply_proposal(repo, fake_garmin, p.id)
    fake_garmin.fail_on.clear()
    fake_garmin.calls.clear()
    return repo.session(exported_session.id)


@pytest.mark.parametrize("op", ["modify", "remove"])
def test_proposal_on_sync_error_session_rejected(repo, fake_garmin, exported_session, op):
    s = _sync_error_session(repo, fake_garmin, exported_session)
    change = modify(s.id) if op == "modify" else Change(op="remove", session_id=s.id, reason="r")
    p = proposal_of(repo, change)
    with pytest.raises(ExportError, match="réessaie d'abord"):
        apply_proposal(repo, fake_garmin, p.id)
    assert repo.pending_proposal().id == p.id and fake_garmin.calls == []


@pytest.mark.parametrize("status", ["done", "missed"])
@pytest.mark.parametrize("op", ["modify", "remove"])
def test_proposal_on_done_or_missed_rejected(repo, fake_garmin, session_w3, status, op):
    session_w3.status = status
    repo.update(session_w3)
    change = modify(session_w3.id) if op == "modify" else Change(op="remove", session_id=session_w3.id, reason="r")
    p = proposal_of(repo, change)
    with pytest.raises(ExportError, match="historique"):
        apply_proposal(repo, fake_garmin, p.id)
    assert repo.session(session_w3.id).title == "Sortie facile"
    assert repo.pending_proposal().id == p.id


def test_conversion_failure_changes_nothing(repo, goal, fake_garmin, session_w3):
    # zones sans allure : un workout cible allure ne peut pas être converti
    no_pace = compute_zones(
        threshold_pace_s_km=None, pred_10k_s=None, garmin_hr_zones=None, hr_max=190, hr_rest=50
    )
    assert no_pace.pace is None
    repo.add(AthleteSnapshot(date=date(2026, 11, 2), zones_json=no_pace.model_dump_json()))
    export_session(repo, fake_garmin, session_w3.id, D)  # cible FC : convertible
    fake_garmin.calls.clear()
    p = proposal_of(repo, modify(session_w3.id, target_kind="pace"))
    with pytest.raises(ExportError, match="Conversion"):
        apply_proposal(repo, fake_garmin, p.id)
    s = repo.session(session_w3.id)
    assert s.title == "Sortie facile" and s.status == "exported"
    assert repo.pending_proposal().id == p.id and fake_garmin.calls == []


def test_one_failure_does_not_stop_other_sessions(repo, goal):
    class FailFirstUpload(FakeGarminClient):
        n = 0

        def upload_workout(self, workout):
            self.n += 1
            if self.n == 3:  # 2 exports initiaux, puis le premier remplacement
                raise GarminUnavailable("boum")
            return super().upload_workout(workout)

    g = FailFirstUpload()
    a = repo.add(make_db_session(goal.id, week_index=3, order=1))
    b = repo.add(make_db_session(goal.id, week_index=3, order=2, title="B"))
    export_session(repo, g, a.id, D)
    export_session(repo, g, b.id, date(2026, 11, 12))
    p = proposal_of(repo, modify(a.id), modify(b.id))
    assert apply_proposal(repo, g, p.id) == [a.id]
    assert repo.session(a.id).status == "sync_error"
    sb = repo.session(b.id)
    assert sb.status == "exported" and sb.title == "Nouvelle séance"


def test_preconversion_error_aborts_before_commit(repo, goal, fake_garmin, session_w3, monkeypatch):
    export_session(repo, fake_garmin, session_w3.id, D)
    p = proposal_of(repo, modify(session_w3.id))
    import coach.services.garmin_export as ge

    def boom(*a, **k):
        raise ValueError("conversion cassée")

    monkeypatch.setattr(ge, "session_to_workout_json", boom, raising=True)
    # la pré-conversion échoue avant toute écriture
    with pytest.raises(ExportError, match="conversion cassée"):
        apply_proposal(repo, fake_garmin, p.id)
    assert repo.pending_proposal().id == p.id


def test_retry_with_past_date_rejected(repo, goal, exported_session):
    g = FakeGarminClient(fail_on={"schedule"}, today=date(2026, 11, 20))
    g.workouts[exported_session.garmin_workout_id] = {}
    g.schedules[exported_session.garmin_schedule_id] = (exported_session.garmin_workout_id, D)
    p = proposal_of(repo, modify(exported_session.id))
    apply_proposal(repo, g, p.id)
    g.fail_on.clear()
    g.calls.clear()
    with pytest.raises(ExportError, match="Date passée"):
        retry_sync_error(repo, g, exported_session.id)
    assert g.calls == [] and repo.session(exported_session.id).status == "sync_error"


def test_unschedule_failure_keeps_schedule_cleared(repo, fake_garmin, exported_session):
    fake_garmin.fail_on = {"delete_workout"}
    with pytest.raises(GarminUnavailable):
        unschedule_session(repo, fake_garmin, exported_session.id)
    s = repo.session(exported_session.id)
    assert s.garmin_schedule_id is None and s.garmin_workout_id is not None
    fake_garmin.fail_on.clear()
    unschedule_session(repo, fake_garmin, exported_session.id)
    assert repo.session(exported_session.id).status == "todo" and fake_garmin.workouts == {}


def test_valueerror_after_commit_becomes_sync_error(repo, goal, fake_garmin, exported_session, monkeypatch):
    import coach.services.garmin_export as ge

    def boom(*a, **k):
        raise ValueError("conversion cassée")

    p = proposal_of(repo, modify(exported_session.id))
    monkeypatch.setattr(ge, "_upload_and_schedule", boom)
    assert apply_proposal(repo, fake_garmin, p.id) == [exported_session.id]
    s = repo.session(exported_session.id)
    assert s.status == "sync_error" and "conversion cassée" in s.sync_error
