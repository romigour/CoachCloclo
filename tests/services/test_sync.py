import json
from datetime import date, datetime, timedelta

import pytest
from sqlmodel import select

from coach.garmin.port import ActivitySummary, FakeGarminClient, LapSummary, Metrics
from coach.llm.provider import FakeLLMProvider, LLMUsageLimit
from coach.llm.schemas import AdjustmentResponse, Change
from coach.plan.models import Activity, Cycle, Event, Proposal, Session
from coach.services.events import delete_event
from tests.llm.factories import make_session
from coach.services.sync import (
    SyncResult,
    SyncState,
    add_pending_done,
    load_sync_state,
    save_sync_state,
    sync,
)
from tests.plan.factories import make_cycle, make_db_session, make_goal

NOW = datetime(2026, 11, 4, 8, 0)
METRICS = Metrics(hr_max=190, hr_rest=50, threshold_pace_s_km=300)


class FailingLLM:
    """LLM de test qui lève toujours l'exception donnée."""

    def __init__(self, exc: Exception):
        self.exc = exc

    def complete(self, system: str, prompt: str) -> str:
        raise self.exc


def run_summary(garmin_id=1, d=date(2026, 11, 3), **overrides) -> ActivitySummary:
    data = {
        "garmin_id": garmin_id,
        "date": d,
        "type_key": "running",
        "duration_s": 2700,
        "distance_m": 9000,
        "raw": {},
    }
    data.update(overrides)
    return ActivitySummary(**data)


def adjustment_json(changes=None, analysis="Bonne semaine.") -> str:
    return AdjustmentResponse(analysis=analysis, changes=changes or []).model_dump_json()


@pytest.fixture
def fake_garmin():
    return FakeGarminClient(metrics=METRICS, activities=[run_summary()], today=date(2026, 11, 4))


def _cycle_with_sessions(repo, accepted: bool):
    """Cycle actif (objectif au 31/01/2027) avec deux semaines de séances."""
    cycle = repo.add(make_cycle(plan_start=date(2026, 11, 2), plan_accepted=accepted))
    repo.add(make_goal(plan_start=date(2026, 11, 2), race_date=cycle.end_date))
    for w in (1, 2):
        for o in (1, 2, 3):
            s = make_db_session(cycle.id, week_index=w, order=o)
            if w == 1 and o in (1, 2):  # envoyées sur la montre mardi et mercredi : rattachables
                s.status = "exported"
                s.scheduled_date = date(2026, 11, 2 + o)
                s.est_duration_min = 45.0
            repo.add(s)
    return cycle


@pytest.fixture
def accepted_plan(repo):
    return _cycle_with_sessions(repo, True)


@pytest.fixture
def draft_plan(repo):
    return _cycle_with_sessions(repo, False)


def _attach(repo, cycle, garmin_id=1, d=date(2026, 11, 3), index=0) -> int:
    """Rattachement manuel tel que le fait l'API : activité reliée, séance réalisée, en attente d'analyse.

    L'activité `garmin_id` est créée si elle n'est pas encore importée ; retourne l'id de la séance."""
    sid = repo.sessions(cycle.id)[index].id
    act = repo.activity_by_garmin_id(garmin_id)
    if act is None:
        act = repo.add(
            Activity(garmin_activity_id=garmin_id, date=d, type_key="running", duration_s=2700, distance_m=9000)
        )
    with repo.transaction() as db:
        a = db.get(Activity, act.id)
        a.session_id, a.match_source = sid, "manual"
        db.add(a)
        s = db.get(Session, sid)
        s.status = "done"
        db.add(s)
    add_pending_done(repo, sid)
    return sid


def test_sync_never_attaches(repo, coach_home, fake_garmin, accepted_plan):
    llm = FakeLLMProvider([adjustment_json()])
    r = sync(repo, fake_garmin, llm, now=NOW)
    assert isinstance(r, SyncResult)
    assert (r.new_activities, r.missed, r.proposal_id) == (1, 0, None) and llm.calls == []
    assert repo.activity_by_garmin_id(1).session_id is None
    assert not any(s.status == "done" for s in repo.sessions(accepted_plan.id))


def test_sync_sends_manually_attached_session_to_claude(repo, coach_home, fake_garmin, accepted_plan):
    sid = _attach(repo, accepted_plan)
    llm = FakeLLMProvider([adjustment_json(analysis="Tout va bien")])
    r = sync(repo, fake_garmin, llm, now=NOW)
    assert (r.new_activities, r.missed) == (0, 0)
    assert f"- prévu : {repo.session(sid).title}" in llm.calls[0]
    assert repo.session(sid).status == "done" and repo.activity_by_garmin_id(1).match_source == "manual"
    assert load_sync_state(repo).pending_done == []
    pending = repo.pending_proposal()
    assert r.proposal_id == pending.id
    assert pending.analysis == "Tout va bien" and json.loads(pending.changes_json) == []
    assert load_sync_state(repo).last_sync_at == NOW


def test_sync_without_news_creates_no_proposal(repo, coach_home, fake_garmin, accepted_plan):
    _attach(repo, accepted_plan)
    llm = FakeLLMProvider([adjustment_json()])
    sync(repo, fake_garmin, llm, now=NOW)
    r = sync(repo, fake_garmin, llm, now=NOW + timedelta(hours=1))
    assert r.proposal_id is None and len(llm.calls) == 1
    assert (r.new_activities, r.missed) == (0, 0)


def test_sync_ignores_stale_pending_done(repo, coach_home, fake_garmin, accepted_plan):
    add_pending_done(repo, repo.sessions(accepted_plan.id)[0].id)  # jamais passée « réalisée »
    add_pending_done(repo, 99999)  # séance inexistante
    llm = FakeLLMProvider([adjustment_json()])
    r = sync(repo, fake_garmin, llm, now=NOW)
    assert r.proposal_id is None and llm.calls == []
    assert load_sync_state(repo).pending_done == []


def test_load_sync_state_without_pending_done(repo, coach_home):
    repo.set_state("sync", {"last_sync_at": None, "proposal_due": False})
    assert load_sync_state(repo).pending_done == []


def test_new_proposal_makes_previous_stale(repo, coach_home, fake_garmin, accepted_plan):
    _attach(repo, accepted_plan)
    llm = FakeLLMProvider([adjustment_json(analysis="un"), adjustment_json(analysis="deux")])
    r1 = sync(repo, fake_garmin, llm, now=NOW)
    _attach(repo, accepted_plan, garmin_id=2, d=date(2026, 11, 4), index=1)
    r2 = sync(repo, fake_garmin, llm, now=NOW + timedelta(hours=2))
    assert r2.proposal_id not in (None, r1.proposal_id)
    assert repo.pending_proposal().id == r2.proposal_id
    with repo.transaction() as db:
        assert db.get(Proposal, r1.proposal_id).status == "stale"
        assert db.get(Proposal, r2.proposal_id).status == "pending"


def test_llm_failure_keeps_pending_done(repo, coach_home, fake_garmin, accepted_plan):
    sid = _attach(repo, accepted_plan)
    with pytest.raises(LLMUsageLimit):
        sync(repo, fake_garmin, FailingLLM(LLMUsageLimit()), now=NOW)
    assert repo.session(sid).status == "done"
    assert load_sync_state(repo).pending_done == [sid]
    assert load_sync_state(repo).last_sync_at == NOW
    assert repo.pending_proposal() is None


def test_llm_failure_keeps_previous_pending(repo, coach_home, fake_garmin, accepted_plan):
    _attach(repo, accepted_plan)
    sync(repo, fake_garmin, FakeLLMProvider([adjustment_json()]), now=NOW)
    before = repo.pending_proposal()
    _attach(repo, accepted_plan, garmin_id=2, d=date(2026, 11, 4), index=1)
    with pytest.raises(LLMUsageLimit):
        sync(repo, fake_garmin, FailingLLM(LLMUsageLimit()), now=NOW + timedelta(hours=2))
    assert repo.pending_proposal().id == before.id


def test_no_proposal_before_plan_accepted(repo, coach_home, fake_garmin, draft_plan):
    sid = _attach(repo, draft_plan)
    llm = FakeLLMProvider([adjustment_json()])
    r = sync(repo, fake_garmin, llm, now=NOW)
    assert r.proposal_id is None and llm.calls == []
    assert repo.pending_proposal() is None and load_sync_state(repo).pending_done == [sid]


def test_duplicate_activities_not_reimported(repo, coach_home, fake_garmin, accepted_plan):
    llm = FakeLLMProvider([adjustment_json()])
    r1 = sync(repo, fake_garmin, llm, now=NOW)
    r2 = sync(repo, fake_garmin, llm, now=NOW + timedelta(hours=1))
    assert r1.new_activities == 1 and r2.new_activities == 0
    with repo.transaction() as db:
        assert len(db.exec(select(Activity)).all()) == 1


def test_missed_sessions_marked(repo, coach_home, accepted_plan):
    garmin = FakeGarminClient(metrics=METRICS, today=date(2026, 11, 10))  # semaine 1 terminée
    llm = FakeLLMProvider([adjustment_json()])
    r = sync(repo, garmin, llm, now=datetime(2026, 11, 10, 8, 0))
    assert r.missed == 3
    statuses = [s.status for s in repo.sessions(accepted_plan.id, week_index=1)]
    assert statuses == ["missed"] * 3
    assert r.proposal_id is not None


def test_proposal_changes_serialized(repo, coach_home, fake_garmin, accepted_plan):
    target = repo.sessions(accepted_plan.id, week_index=2)[0]
    change = Change(op="remove", session_id=target.id, reason="Trop chargé")
    llm = FakeLLMProvider([adjustment_json([change])])
    _attach(repo, accepted_plan)
    sync(repo, fake_garmin, llm, now=NOW)
    changes = json.loads(repo.pending_proposal().changes_json)
    assert changes[0]["op"] == "remove" and changes[0]["session_id"] == target.id


def test_first_sync_window_is_56_days(repo, coach_home, accepted_plan):
    old = run_summary(garmin_id=9, d=date(2026, 11, 4) - timedelta(days=60))
    recent = run_summary(garmin_id=10, d=date(2026, 11, 4) - timedelta(days=50))
    garmin = FakeGarminClient(metrics=METRICS, activities=[old, recent], today=date(2026, 11, 4))
    r = sync(repo, garmin, FakeLLMProvider([adjustment_json()]), now=NOW)
    assert r.new_activities == 1


def test_proposal_retried_after_llm_failure(repo, coach_home, fake_garmin, accepted_plan):
    _attach(repo, accepted_plan)
    with pytest.raises(LLMUsageLimit):
        sync(repo, fake_garmin, FailingLLM(LLMUsageLimit()), now=NOW)
    assert load_sync_state(repo).proposal_due is True
    llm = FakeLLMProvider([adjustment_json()])
    r = sync(repo, fake_garmin, llm, now=NOW + timedelta(hours=1))
    assert r.proposal_id is not None and len(llm.calls) == 1
    assert load_sync_state(repo).proposal_due is False
    r3 = sync(repo, fake_garmin, llm, now=NOW + timedelta(hours=2))
    assert r3.proposal_id is None and len(llm.calls) == 1


def test_overlap_window_two_days(repo, coach_home, accepted_plan):
    save_sync_state(repo, SyncState(last_sync_at=datetime(2026, 11, 3, 8, 0)))
    inside = run_summary(garmin_id=20, d=date(2026, 11, 1))
    outside = run_summary(garmin_id=21, d=date(2026, 10, 31))
    garmin = FakeGarminClient(metrics=METRICS, activities=[inside, outside], today=date(2026, 11, 4))
    r = sync(repo, garmin, FakeLLMProvider([adjustment_json()]), now=NOW)
    assert r.new_activities == 1
    assert repo.activity_by_garmin_id(20) is not None and repo.activity_by_garmin_id(21) is None


def test_pending_removal_excluded_from_week_counts(repo, coach_home, fake_garmin, accepted_plan):
    # semaine 2 : 3 séances ; l'une est en cours de retrait -> Claude peut en ajouter une
    week2 = repo.sessions(accepted_plan.id, week_index=2)
    gone = week2[0]
    gone.status = "sync_error"
    gone.pending_removal = True
    repo.update(gone)
    add = Change(op="add", session=make_session(week_index=2, order=4, title="Ajout"), reason="r")
    llm = FakeLLMProvider([adjustment_json([add])])
    _attach(repo, accepted_plan)
    r = sync(repo, fake_garmin, llm, now=NOW)
    assert r.proposal_id is not None
    with repo.transaction() as db:
        assert db.get(Proposal, r.proposal_id).status == "pending"


def test_exported_session_moved_to_other_week_is_retried(repo, coach_home, fake_garmin, accepted_plan):
    target = repo.sessions(accepted_plan.id, week_index=2)[0]
    target.status = "exported"
    target.scheduled_date = date(2026, 11, 10)
    repo.update(target)
    moved = Change(op="modify", session_id=target.id, session=make_session(week_index=3), reason="r")
    llm = FakeLLMProvider([adjustment_json([moved]), adjustment_json()])
    _attach(repo, accepted_plan)
    r = sync(repo, fake_garmin, llm, now=NOW)
    assert len(llm.calls) == 2 and "exportée" in llm.calls[1]
    assert r.proposal_id is not None


def test_sync_refreshes_personal_records(repo, coach_home):
    from coach.garmin.port import PersonalRecordSummary

    garmin = FakeGarminClient(
        metrics=METRICS,
        activities=[run_summary()],
        today=date(2026, 11, 4),
        personal_records=[PersonalRecordSummary(kind="5k", value=1200.0)],
    )
    sync(repo, garmin, FakeLLMProvider([]), now=NOW)
    assert [r.kind for r in repo.records()] == ["5k"]


def test_sync_fetches_laps_of_attached_activities(repo, coach_home, accepted_plan):
    _attach(repo, accepted_plan)
    free = run_summary(garmin_id=2, d=date(2026, 11, 1))  # non rattachée
    garmin = FakeGarminClient(
        metrics=METRICS,
        activities=[run_summary(), free],
        today=date(2026, 11, 4),
        laps={1: [LapSummary(index=0, duration_s=600, distance_m=1800)], 2: [LapSummary(index=0, duration_s=60, distance_m=200)]},
    )
    sync(repo, garmin, FakeLLMProvider([adjustment_json()]), now=NOW)
    matched = repo.activity_by_garmin_id(1)
    assert matched.session_id is not None and len(repo.laps(matched.id)) == 1
    assert repo.laps(repo.activity_by_garmin_id(2).id) is None


def test_sync_survives_laps_error_and_retries_next_time(repo, coach_home, accepted_plan):
    _attach(repo, accepted_plan)
    laps = {1: [LapSummary(index=0, duration_s=600, distance_m=1800)]}
    garmin = FakeGarminClient(
        metrics=METRICS, activities=[run_summary()], today=date(2026, 11, 4), laps=laps, fail_on={"activity_laps"}
    )
    sync(repo, garmin, FakeLLMProvider([adjustment_json()]), now=NOW)
    activity = repo.activity_by_garmin_id(1)
    assert repo.laps(activity.id) is None

    garmin.fail_on.clear()
    sync(repo, garmin, FakeLLMProvider([adjustment_json()]), now=NOW)
    assert len(repo.laps(activity.id)) == 1


def test_proposal_prompt_contains_step_detail(repo, coach_home, accepted_plan):
    laps = {1: [LapSummary(index=0, duration_s=600, distance_m=1800, avg_hr=140, step_order=1)]}
    garmin = FakeGarminClient(metrics=METRICS, activities=[run_summary()], today=date(2026, 11, 4), laps=laps)
    llm = FakeLLMProvider([adjustment_json()])
    _attach(repo, accepted_plan)
    sync(repo, garmin, llm, now=NOW)
    assert "· échauffement" in llm.calls[0]


def test_sync_skips_proposal_during_open_injury(repo, coach_home, fake_garmin, accepted_plan):
    repo.add(Event(cycle_id=accepted_plan.id, kind="injury", start_date=date(2026, 11, 3)))
    sid = _attach(repo, accepted_plan)
    llm = FakeLLMProvider([adjustment_json()])
    r = sync(repo, fake_garmin, llm, now=NOW)
    assert r.proposal_id is None and llm.calls == []
    state = load_sync_state(repo)
    assert state.proposal_due is True and state.pending_done == [sid]


def test_deleting_open_injury_resumes_sync_proposals(repo, coach_home, fake_garmin, accepted_plan):
    injury = repo.add(Event(cycle_id=accepted_plan.id, kind="injury", start_date=date(2026, 11, 3)))
    _attach(repo, accepted_plan)
    assert sync(repo, fake_garmin, FakeLLMProvider([adjustment_json()]), now=NOW).proposal_id is None
    delete_event(repo, injury.id)
    r = sync(repo, fake_garmin, FakeLLMProvider([adjustment_json()]), now=NOW)
    assert r.proposal_id is not None and load_sync_state(repo).proposal_due is False


# --- clôture des objectifs et du cycle ---------------------------------------------------------


def _short_cycle(repo):
    """Cycle validé qui finit au Principal du mardi 03/11/2026, séance du jour de course exportée."""
    cycle = repo.add(make_cycle(plan_start=date(2026, 10, 19), end_date=date(2026, 11, 3), plan_accepted=True))
    repo.add(make_goal(race_date=date(2026, 11, 3)))
    repo.add(make_goal(race_date=date(2027, 3, 7)))  # objectif suivant, hors du cycle
    s = make_db_session(cycle.id, week_index=3, order=1)
    s.status = "exported"
    s.scheduled_date = date(2026, 11, 3)
    s.est_duration_min = 45.0
    repo.add(s)
    return cycle


def test_sync_marks_passed_secondary_done_keeps_cycle(repo, coach_home, fake_garmin, accepted_plan):
    secondary = repo.add(make_goal(race_date=date(2026, 11, 3), priority="secondaire", distance_km=10))
    _attach(repo, accepted_plan)
    llm = FakeLLMProvider([adjustment_json()])
    r = sync(repo, fake_garmin, llm, now=NOW)
    assert secondary.id not in [g.id for g in repo.upcoming_goals()]
    assert [g.id for g in repo.past_goals()] == [secondary.id]
    assert repo.active_cycle().id == accepted_plan.id
    assert r.proposal_id is not None and len(llm.calls) == 1


def test_sync_closes_cycle_after_principal(repo, coach_home, fake_garmin):
    cycle = _short_cycle(repo)
    _attach(repo, cycle)
    old = repo.add(Proposal(analysis="a", changes_json="[]", status="pending"))
    llm = FakeLLMProvider([adjustment_json()])
    r = sync(repo, fake_garmin, llm, now=NOW)
    assert repo.active_cycle() is None
    with repo.transaction() as db:
        assert db.get(Cycle, cycle.id).status == "done"
        assert db.get(Proposal, old.id).status == "stale"
    assert r.proposal_id is None and llm.calls == [] and repo.pending_proposal() is None
    assert [g.race_date for g in repo.upcoming_goals()] == [date(2027, 3, 7)]
    state = load_sync_state(repo)
    assert state.proposal_due is False and state.pending_done == []


def test_sync_retries_removal_of_done_cycle_sessions(repo, coach_home, fake_garmin):
    """Une séance d'un cycle terminé restée à retirer de la montre est nettoyée à la synchro suivante."""
    from coach.plan.models import Session

    done = repo.add(make_cycle(plan_start=date(2026, 9, 7), end_date=date(2026, 11, 1), status="done"))
    fake_garmin.workouts[700] = {}
    fake_garmin.schedules[701] = (700, date(2026, 11, 5))
    fake_garmin.calendar[date(2026, 11, 5)] = [701]
    s = make_db_session(done.id, week_index=8, order=1)
    s.status, s.sync_error, s.pending_removal = "sync_error", "Synchronisation Garmin échouée : x", True
    s.pending_old_workout_id, s.pending_old_schedule_id = 700, 701
    s = repo.add(s)
    # remplacement inachevé d'une séance encore à venir : seul le nettoyage des anciens ids reste à faire
    fake_garmin.workouts[710] = {}
    replaced = make_db_session(done.id, week_index=8, order=2)
    replaced.status, replaced.sync_error, replaced.scheduled_date = "sync_error", "x", date(2026, 11, 6)
    replaced.garmin_workout_id, replaced.garmin_schedule_id = 720, 721
    replaced.pending_old_workout_id = 710
    replaced = repo.add(replaced)
    sync(repo, fake_garmin, FakeLLMProvider([]), now=NOW)
    with repo.transaction() as db:
        assert db.get(Session, s.id) is None
        assert db.get(Session, replaced.id).status == "exported"
    assert fake_garmin.workouts == {} and fake_garmin.schedules == {}


def test_sync_does_not_propose_for_pending_goal_change(repo, coach_home, accepted_plan):
    from tests.services.test_adjust import _pend

    _pend(repo, accepted_plan.id, "L'athlète a ajouté un objectif.")
    llm = FakeLLMProvider([])
    r = sync(repo, FakeGarminClient(metrics=METRICS, today=date(2026, 11, 2)), llm, now=NOW)
    assert r.proposal_id is None and llm.calls == []
    assert repo.active_cycle().adjust_due is True


def test_sync_proposal_consumes_pending_notes(repo, coach_home, fake_garmin, accepted_plan):
    from tests.services.test_adjust import _pend

    _pend(repo, accepted_plan.id, "L'athlète a ajouté un objectif.")
    _attach(repo, accepted_plan)
    llm = FakeLLMProvider([adjustment_json()])
    r = sync(repo, fake_garmin, llm, now=NOW)
    assert r.proposal_id is not None and "L'athlète a ajouté un objectif." in llm.calls[0]
    cycle = repo.active_cycle()
    assert cycle.adjust_due is False and cycle.adjust_notes() == []


# --- rattachement manuel pendant une synchro en cours ---------------------------------------


class _AttachDuringClaudeLLM:
    """Claude simulé pendant la réponse duquel l'athlète rattache une autre sortie (autre requête)."""

    def __init__(self, repo, cycle):
        self.repo, self.cycle, self.sid = repo, cycle, None

    def complete(self, system: str, prompt: str) -> str:
        self.sid = _attach(self.repo, self.cycle, garmin_id=2, d=date(2026, 11, 4), index=1)
        return adjustment_json()


def test_manual_match_during_claude_call_survives_sync(repo, coach_home, fake_garmin, accepted_plan):
    first = _attach(repo, accepted_plan)
    llm = _AttachDuringClaudeLLM(repo, accepted_plan)
    r = sync(repo, fake_garmin, llm, now=NOW)
    assert r.proposal_id is not None and llm.sid != first
    assert load_sync_state(repo).pending_done == [llm.sid]


class _AttachDuringImportGarmin(FakeGarminClient):
    """Garmin simulé pendant l'import duquel l'athlète rattache une sortie (autre requête)."""

    def activities(self, since, until):
        self.sid = _attach(self.repo, self.cycle, garmin_id=2, d=date(2026, 11, 4), index=1)
        return super().activities(since, until)


def test_manual_match_during_import_survives_sync(repo, coach_home, accepted_plan):
    garmin = _AttachDuringImportGarmin(metrics=METRICS, activities=[run_summary()], today=date(2026, 11, 4))
    garmin.repo, garmin.cycle = repo, accepted_plan
    first = _attach(repo, accepted_plan)
    r = sync(repo, garmin, FakeLLMProvider([adjustment_json()]), now=NOW)
    assert r.proposal_id is not None and garmin.sid != first
    assert load_sync_state(repo).pending_done == [garmin.sid]


def test_sync_reports_resent(repo, coach_home):
    """La FC repos saisie passe de 55 à 47 : la séance FC à venir est renvoyée avec les nouvelles zones."""
    from coach.analysis.zones import hr_zones
    from coach.plan.models import AthleteSnapshot
    from coach.services.garmin_export import export_session
    from coach.services.rest_hr import save_manual
    from tests.services.test_rezone import zones_rest

    g = FakeGarminClient(metrics=Metrics(hr_max=182, hr_rest=55, threshold_pace_s_km=300), today=date(2026, 11, 4))
    repo.add(AthleteSnapshot(date=date(2026, 11, 1), hr_rest=55, zones_json=zones_rest(55).model_dump_json()))
    cycle = repo.add(make_cycle(plan_start=date(2026, 11, 2), plan_accepted=False))
    sid = repo.add(make_db_session(cycle.id, week_index=1, order=1)).id
    export_session(repo, g, sid, date(2026, 11, 5))
    old_workout = repo.session(sid).garmin_workout_id
    save_manual(repo, 47)
    result = sync(repo, g, FakeLLMProvider([]), now=NOW)
    assert (result.resent, result.hr_rest) == (1, 47)
    s = repo.session(sid)
    assert s.status == "exported" and s.garmin_workout_id != old_workout and old_workout not in g.workouts
    assert json.loads(s.export_hr_zones_json)["Z2"] == list(hr_zones(182, 47)["Z2"])


def test_sync_resend_failure_does_not_fail_sync(repo, coach_home):
    from coach.plan.models import AthleteSnapshot
    from coach.services.garmin_export import export_session
    from coach.services.rest_hr import save_manual
    from tests.services.test_rezone import zones_rest

    g = FakeGarminClient(metrics=Metrics(hr_max=182, hr_rest=55, threshold_pace_s_km=300), today=date(2026, 11, 4))
    repo.add(AthleteSnapshot(date=date(2026, 11, 1), hr_rest=55, zones_json=zones_rest(55).model_dump_json()))
    cycle = repo.add(make_cycle(plan_start=date(2026, 11, 2), plan_accepted=False))
    sid = repo.add(make_db_session(cycle.id, week_index=1, order=1)).id
    export_session(repo, g, sid, date(2026, 11, 5))
    save_manual(repo, 47)
    g.fail_on = {"upload_workout"}
    result = sync(repo, g, FakeLLMProvider([]), now=NOW)
    assert (result.resent, result.hr_rest) == (0, 47)
    assert repo.session(sid).status == "sync_error"
