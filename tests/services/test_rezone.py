import json
from datetime import date

import pytest

from coach.analysis.zones import Zones, compute_zones, hr_zones
from coach.export.garmin_workout import session_to_workout_json
from coach.garmin.port import FakeGarminClient
from coach.llm.schemas import StepSpec
from coach.plan.models import AthleteSnapshot
from coach.services.garmin_export import export_session
from coach.services.rezone import RESEND_MIN_BPM, Rezone, needs_resend, resend_for_zones
from tests.plan.factories import make_activity, make_cycle, make_db_session

T = date(2026, 11, 23)  # lundi de la semaine 5 du cycle (début 26/10)
PACE = compute_zones(threshold_pace_s_km=300, pred_10k_s=None, hr_max=182, hr_rest=55).pace


def zones_rest(x: int) -> Zones:
    """Zones dont la FC vient de `hr_zones(182, x)`."""
    return Zones(pace=PACE, hr=hr_zones(182, x), source=["lactate_threshold", "karvonen"])


def _hr_session(cycle_id: int, zone: str = "Z2", title: str = "EF 40 min Z2", order: int = 1, week: int = 5):
    return make_db_session(
        cycle_id,
        week_index=week,
        order=order,
        title=title,
        steps=[StepSpec(kind="active", duration_s=2400, zone=zone)],
    )


@pytest.fixture
def g():
    return FakeGarminClient()  # aujourd'hui côté Garmin : 04/11, tout export de novembre est permis


@pytest.fixture
def cycle(repo):
    repo.add(AthleteSnapshot(date=date(2026, 11, 1), zones_json=zones_rest(55).model_dump_json()))
    return repo.add(make_cycle())


def _export(repo, g, session, d: date) -> int:
    s = repo.add(session)
    export_session(repo, g, s.id, d)
    return s.id


@pytest.fixture
def sid(repo, g, cycle):
    """Séance FC « EF 40 min Z2 » exportée demain avec les zones de FC repos 55."""
    return _export(repo, g, _hr_session(cycle.id), date(2026, 11, 24))


def test_threshold_value():
    assert RESEND_MIN_BPM == 2


def test_resent_when_zone_moves_2_bpm(repo, g, sid):
    old_workout = repo.session(sid).garmin_workout_id
    r = resend_for_zones(repo, g, zones_rest(47), T)
    s = repo.session(sid)
    assert r == Rezone(resent=1, failed=[]) and s.status == "exported" and s.garmin_workout_id != old_workout
    assert old_workout not in g.workouts and list(g.workouts) == [s.garmin_workout_id]
    assert json.loads(s.export_hr_zones_json)["Z2"] == list(hr_zones(182, 47)["Z2"])
    step = g.workouts[s.garmin_workout_id]["workoutSegments"][0]["workoutSteps"][0]
    assert (step["targetValueOne"], step["targetValueTwo"]) == hr_zones(182, 47)["Z2"]
    assert s.scheduled_date == date(2026, 11, 24) and s.pending_old_workout_id is None


def test_not_resent_below_threshold(repo, g, cycle):
    # 55 -> 54 : Z4 passe de (157, 169) à (156, 169), le workout change mais l'écart est < 2 bpm
    sid = _export(repo, g, _hr_session(cycle.id, zone="Z4", title="Seuil Z4"), date(2026, 11, 24))
    s = repo.session(sid)
    assert session_to_workout_json(s.to_spec(), zones_rest(54), name="x") != session_to_workout_json(
        s.to_spec(), zones_rest(55), name="x"
    )
    assert not needs_resend(s, zones_rest(54))
    calls = list(g.calls)
    assert resend_for_zones(repo, g, zones_rest(54), T) == Rezone(resent=0, failed=[])
    assert g.calls == calls and repo.session(sid).garmin_workout_id == s.garmin_workout_id


def test_unchanged_workout_not_resent(repo, g, sid):
    # 55 -> 54 : Z2 identique, rien à renvoyer
    assert not needs_resend(repo.session(sid), zones_rest(54))
    assert resend_for_zones(repo, g, zones_rest(54), T) == Rezone(resent=0, failed=[])


def test_pace_session_never_resent(repo, g, cycle):
    sid = _export(repo, g, make_db_session(cycle.id, week_index=5, target_kind="pace"), date(2026, 11, 24))
    old_workout = repo.session(sid).garmin_workout_id
    assert not needs_resend(repo.session(sid), zones_rest(47))
    assert resend_for_zones(repo, g, zones_rest(47), T) == Rezone(resent=0, failed=[])
    assert repo.session(sid).garmin_workout_id == old_workout


def test_past_and_done_sessions_untouched(repo, g, cycle):
    past = _export(repo, g, _hr_session(cycle.id, week=4), date(2026, 11, 22))  # dimanche dernier
    done = _export(repo, g, _hr_session(cycle.id, order=2), date(2026, 11, 25))
    s = repo.session(done)
    s.status = "done"
    repo.update(s)
    todo = repo.add(_hr_session(cycle.id, order=3))
    before = {i: repo.session(i).garmin_workout_id for i in (past, done)}
    calls = list(g.calls)
    assert resend_for_zones(repo, g, zones_rest(47), T) == Rezone(resent=0, failed=[])
    assert g.calls == calls
    assert {i: repo.session(i).garmin_workout_id for i in (past, done)} == before
    assert repo.session(todo.id).status == "todo"


def test_today_session_resent_without_activity_today(repo, g, cycle):
    sid = _export(repo, g, _hr_session(cycle.id), T)
    old_workout = repo.session(sid).garmin_workout_id
    assert resend_for_zones(repo, g, zones_rest(47), T) == Rezone(resent=1, failed=[])
    s = repo.session(sid)
    assert s.garmin_workout_id != old_workout and s.scheduled_date == T


def test_today_session_not_resent_when_activity_today(repo, g, cycle):
    sid = _export(repo, g, _hr_session(cycle.id), T)
    old_workout = repo.session(sid).garmin_workout_id
    repo.add(make_activity(date=T))
    assert resend_for_zones(repo, g, zones_rest(47), T) == Rezone(resent=0, failed=[])
    assert repo.session(sid).garmin_workout_id == old_workout


def test_legacy_export_without_zones_resent_once(repo, g, sid):
    s = repo.session(sid)
    s.export_hr_zones_json = None  # export antérieur à l'enregistrement des zones
    repo.update(s)
    old_workout = s.garmin_workout_id
    assert resend_for_zones(repo, g, zones_rest(55), T) == Rezone(resent=1, failed=[])
    s = repo.session(sid)
    assert s.garmin_workout_id != old_workout and old_workout not in g.workouts
    assert json.loads(s.export_hr_zones_json)["Z2"] == list(hr_zones(182, 55)["Z2"])
    assert resend_for_zones(repo, g, zones_rest(55), T) == Rezone(resent=0, failed=[])


def test_legacy_pace_export_without_zones_not_resent(repo, g, cycle):
    sid = _export(repo, g, make_db_session(cycle.id, week_index=5, target_kind="pace"), date(2026, 11, 24))
    s = repo.session(sid)
    s.export_hr_zones_json = None
    repo.update(s)
    assert not needs_resend(s, zones_rest(47))


def test_resend_failure_leaves_sync_error(repo, g, sid):
    old_workout = repo.session(sid).garmin_workout_id
    g.fail_on = {"upload_workout"}
    r = resend_for_zones(repo, g, zones_rest(47), T)
    s = repo.session(sid)
    assert r == Rezone(resent=0, failed=[sid])
    assert s.status == "sync_error" and s.pending_old_workout_id == old_workout
    assert old_workout in g.workouts


def test_no_active_cycle_resends_nothing(repo, g):
    assert resend_for_zones(repo, g, zones_rest(47), T) == Rezone(resent=0, failed=[])
