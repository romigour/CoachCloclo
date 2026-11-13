import json
from datetime import date, datetime, timedelta

import pytest
from sqlmodel import select

from coach.config import load_settings
from coach.garmin.port import ActivitySummary, FakeGarminClient, LapSummary, Metrics
from coach.llm.provider import FakeLLMProvider, LLMUsageLimit
from coach.llm.schemas import AdjustmentResponse, Change
from coach.plan.models import Activity, Event, Proposal
from coach.services.events import delete_event
from tests.llm.factories import make_session
from coach.services.sync import SyncResult, sync
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


def test_sync_matches_and_creates_proposal(repo, coach_home, fake_garmin, accepted_plan):
    llm = FakeLLMProvider([adjustment_json(analysis="Tout va bien")])
    r = sync(repo, fake_garmin, llm, now=NOW)
    assert isinstance(r, SyncResult)
    assert (r.new_activities, r.matched, r.missed) == (1, 1, 0)
    done = [s for s in repo.sessions(accepted_plan.id) if s.status == "done"]
    assert len(done) == 1
    act = repo.activity_by_garmin_id(1)
    assert act.session_id == done[0].id and act.match_source == "auto"
    pending = repo.pending_proposal()
    assert r.proposal_id == pending.id
    assert pending.analysis == "Tout va bien" and json.loads(pending.changes_json) == []
    assert load_settings().last_sync_at == NOW


def test_sync_without_news_creates_no_proposal(repo, coach_home, fake_garmin, accepted_plan):
    llm = FakeLLMProvider([adjustment_json()])
    sync(repo, fake_garmin, llm, now=NOW)
    r = sync(repo, fake_garmin, llm, now=NOW + timedelta(hours=1))
    assert r.proposal_id is None and len(llm.calls) == 1
    assert (r.new_activities, r.matched, r.missed) == (0, 0, 0)


def test_new_proposal_makes_previous_stale(repo, coach_home, fake_garmin, accepted_plan):
    llm = FakeLLMProvider([adjustment_json(analysis="un"), adjustment_json(analysis="deux")])
    r1 = sync(repo, fake_garmin, llm, now=NOW)
    fake_garmin._activities.append(run_summary(garmin_id=2, d=date(2026, 11, 4)))
    r2 = sync(repo, fake_garmin, llm, now=NOW + timedelta(hours=2))
    assert r2.proposal_id not in (None, r1.proposal_id)
    assert repo.pending_proposal().id == r2.proposal_id
    with repo.transaction() as db:
        assert db.get(Proposal, r1.proposal_id).status == "stale"
        assert db.get(Proposal, r2.proposal_id).status == "pending"


def test_llm_failure_keeps_matching(repo, coach_home, fake_garmin, accepted_plan):
    with pytest.raises(LLMUsageLimit):
        sync(repo, fake_garmin, FailingLLM(LLMUsageLimit()), now=NOW)
    assert any(s.status == "done" for s in repo.sessions(accepted_plan.id))
    assert repo.activity_by_garmin_id(1).session_id is not None
    assert load_settings().last_sync_at == NOW
    assert repo.pending_proposal() is None


def test_llm_failure_keeps_previous_pending(repo, coach_home, fake_garmin, accepted_plan):
    sync(repo, fake_garmin, FakeLLMProvider([adjustment_json()]), now=NOW)
    before = repo.pending_proposal()
    fake_garmin._activities.append(run_summary(garmin_id=2, d=date(2026, 11, 4)))
    with pytest.raises(LLMUsageLimit):
        sync(repo, fake_garmin, FailingLLM(LLMUsageLimit()), now=NOW + timedelta(hours=2))
    assert repo.pending_proposal().id == before.id


def test_no_proposal_before_plan_accepted(repo, coach_home, fake_garmin, draft_plan):
    llm = FakeLLMProvider([adjustment_json()])
    r = sync(repo, fake_garmin, llm, now=NOW)
    assert r.proposal_id is None and llm.calls == []
    assert r.matched == 1 and repo.pending_proposal() is None


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
    assert r.missed == 3 and r.matched == 0
    statuses = [s.status for s in repo.sessions(accepted_plan.id, week_index=1)]
    assert statuses == ["missed"] * 3
    assert r.proposal_id is not None


def test_proposal_changes_serialized(repo, coach_home, fake_garmin, accepted_plan):
    target = repo.sessions(accepted_plan.id, week_index=2)[0]
    change = Change(op="remove", session_id=target.id, reason="Trop chargé")
    llm = FakeLLMProvider([adjustment_json([change])])
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
    with pytest.raises(LLMUsageLimit):
        sync(repo, fake_garmin, FailingLLM(LLMUsageLimit()), now=NOW)
    assert load_settings().proposal_due is True
    llm = FakeLLMProvider([adjustment_json()])
    r = sync(repo, fake_garmin, llm, now=NOW + timedelta(hours=1))
    assert r.matched == 0 and r.proposal_id is not None and len(llm.calls) == 1
    assert load_settings().proposal_due is False
    r3 = sync(repo, fake_garmin, llm, now=NOW + timedelta(hours=2))
    assert r3.proposal_id is None and len(llm.calls) == 1


def test_overlap_window_two_days(repo, coach_home, accepted_plan):
    from coach.config import Settings, save_settings

    save_settings(Settings(last_sync_at=datetime(2026, 11, 3, 8, 0)))
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


def test_sync_fetches_laps_of_matched_activities(repo, coach_home, accepted_plan):
    free = run_summary(garmin_id=2, d=date(2026, 11, 1))  # hors séance : non rattachée
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
    laps = {1: [LapSummary(index=0, duration_s=600, distance_m=1800)]}
    garmin = FakeGarminClient(
        metrics=METRICS, activities=[run_summary()], today=date(2026, 11, 4), laps=laps, fail_on={"activity_laps"}
    )
    r = sync(repo, garmin, FakeLLMProvider([adjustment_json()]), now=NOW)
    assert r.matched == 1
    activity = repo.activity_by_garmin_id(1)
    assert repo.laps(activity.id) is None

    garmin.fail_on.clear()
    sync(repo, garmin, FakeLLMProvider([adjustment_json()]), now=NOW)
    assert len(repo.laps(activity.id)) == 1


def test_proposal_prompt_contains_step_detail(repo, coach_home, accepted_plan):
    laps = {1: [LapSummary(index=0, duration_s=600, distance_m=1800, avg_hr=140, step_order=1)]}
    garmin = FakeGarminClient(metrics=METRICS, activities=[run_summary()], today=date(2026, 11, 4), laps=laps)
    llm = FakeLLMProvider([adjustment_json()])
    sync(repo, garmin, llm, now=NOW)
    assert "· échauffement" in llm.calls[0]


def test_sync_skips_proposal_during_open_injury(repo, coach_home, fake_garmin, accepted_plan):
    repo.add(Event(cycle_id=accepted_plan.id, kind="injury", start_date=date(2026, 11, 3)))
    llm = FakeLLMProvider([adjustment_json()])
    r = sync(repo, fake_garmin, llm, now=NOW)
    assert r.matched == 1 and r.proposal_id is None and llm.calls == []
    assert load_settings().proposal_due is True


def test_deleting_open_injury_resumes_sync_proposals(repo, coach_home, fake_garmin, accepted_plan):
    injury = repo.add(Event(cycle_id=accepted_plan.id, kind="injury", start_date=date(2026, 11, 3)))
    assert sync(repo, fake_garmin, FakeLLMProvider([adjustment_json()]), now=NOW).proposal_id is None
    delete_event(repo, injury.id)
    r = sync(repo, fake_garmin, FakeLLMProvider([adjustment_json()]), now=NOW)
    assert r.proposal_id is not None and load_settings().proposal_due is False
