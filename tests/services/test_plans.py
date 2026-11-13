from datetime import date

import pytest

from coach.garmin.port import FakeGarminClient, Metrics
from coach.llm.provider import FakeLLMProvider, LLMInvalidResponse
from coach.llm.schemas import PlanResponse, WeekSpec
from coach.plan.models import ALL_DAYS, Cycle, Goal, Proposal, Session
from coach.services import CoachError
from coach.services.context import refresh_snapshot
from coach.services.goals import GoalError
from coach.services.plans import PlanSettingsUpdate, accept_plan, generate_plan, update_plan_settings
from tests.llm.factories import make_session, valid_plan_json
from tests.services.test_goals import METRICS, _proposals, first_goal, monday_garmin  # noqa: F401 (fixture)
from tests.services.test_goals import accepted_goal as _accepted_goal
from tests.services.test_sync import adjustment_json


@pytest.fixture
def fake_garmin():
    return FakeGarminClient(metrics=METRICS)


def _cid(repo) -> int:
    """Id du cycle actif."""
    return repo.active_cycle().id


def _active_goal(repo) -> Goal | None:
    """Objectif à venir (un seul ici)."""
    goals = repo.upcoming_goals()
    return goals[0] if goals else None


def _goal(repo, fake_garmin, **overrides) -> Goal:
    return first_goal(repo, fake_garmin, **overrides)


def test_generate_plan_persists_sessions(repo, fake_garmin):
    goal = _goal(repo, fake_garmin)
    llm = FakeLLMProvider([valid_plan_json(n_weeks=14, per_week=3)])
    plan = generate_plan(repo, fake_garmin, llm)
    sessions = repo.sessions(_cid(repo))
    assert len(plan.weeks) == 14
    assert len(sessions) == 42 and all(s.status == "todo" for s in sessions)
    assert repo.latest_snapshot().hr_max == 190


def test_generate_plan_invalid_twice_raises_and_persists_nothing(repo, fake_garmin):
    goal = _goal(repo, fake_garmin)
    with pytest.raises(LLMInvalidResponse):
        generate_plan(repo, fake_garmin, FakeLLMProvider(["{}", "{}"]))
    assert repo.sessions(_cid(repo)) == []


def test_regenerate_replaces_todo_and_resets_accepted(repo, fake_garmin):
    goal = _goal(repo, fake_garmin)
    generate_plan(repo, fake_garmin, FakeLLMProvider([valid_plan_json(14, 3)]))
    accept_plan(repo)
    assert repo.active_cycle().plan_accepted is True
    generate_plan(repo, fake_garmin, FakeLLMProvider([valid_plan_json(14, 2)]))
    assert len(repo.sessions(_cid(repo))) == 28
    assert repo.active_cycle().plan_accepted is False


def test_refresh_snapshot_without_hr_max(repo):
    with pytest.raises(CoachError, match="FC max inconnue"):
        refresh_snapshot(repo, FakeGarminClient(metrics=Metrics()))


def test_refresh_snapshot_relays_real_zone_error(repo):
    with pytest.raises(CoachError, match="FC repos inconnue") as e:
        refresh_snapshot(repo, FakeGarminClient(metrics=Metrics(hr_max=190)))
    assert "FC max" not in str(e.value)


def test_generation_prompt_gives_today(repo, fake_garmin):
    goal = _goal(repo, fake_garmin)  # aujourd'hui : mercredi 4 novembre 2026
    llm = FakeLLMProvider([valid_plan_json(n_weeks=14, per_week=3)])
    generate_plan(repo, fake_garmin, llm)
    assert "Aujourd'hui : mercredi 4 novembre 2026 (semaine 1)" in llm.calls[0]


def test_generate_or_accept_without_cycle_rejected(repo, fake_garmin):
    llm = FakeLLMProvider([valid_plan_json(14, 3)])
    with pytest.raises(GoalError, match="Aucun plan en cours"):
        generate_plan(repo, fake_garmin, llm)
    with pytest.raises(GoalError, match="Aucun plan en cours"):
        accept_plan(repo)
    assert llm.calls == []


def test_generate_saves_claude_estimate(repo, fake_garmin):
    goal = _goal(repo, fake_garmin)
    generate_plan(repo, fake_garmin, FakeLLMProvider([valid_plan_json(14, 3, estimated_time_s=19800)]))
    assert _active_goal(repo).target_time_s == 19800


def test_regenerate_reestimates(repo, fake_garmin):
    goal = _goal(repo, fake_garmin)
    generate_plan(repo, fake_garmin, FakeLLMProvider([valid_plan_json(14, 3, estimated_time_s=19800)]))
    generate_plan(repo, fake_garmin, FakeLLMProvider([valid_plan_json(14, 3, estimated_time_s=20400)]))
    g = _active_goal(repo)
    assert (g.target_time_s, g.target_source) == (20400, "claude")


def test_generate_keeps_user_time(repo, fake_garmin):
    goal = _goal(repo, fake_garmin, target_time_s=18000)
    generate_plan(repo, fake_garmin, FakeLLMProvider([valid_plan_json(14, 3, estimated_time_s=1)]))
    g = _active_goal(repo)
    assert (g.target_time_s, g.target_source) == (18000, "user")


def test_generate_claude_mode_requires_estimate(repo, fake_garmin):
    goal = _goal(repo, fake_garmin)
    llm = FakeLLMProvider([valid_plan_json(14, 3, estimated_time_s=None)] * 2)
    with pytest.raises(LLMInvalidResponse):
        generate_plan(repo, fake_garmin, llm)


def _plan_from(first_week: int, per_week: dict[int, int]) -> str:
    """Plan des semaines `first_week`.. avec `per_week[w]` séances (orders 1..k)."""
    weeks = [
        WeekSpec(week_index=w, focus=f"Semaine {w}",
                 sessions=[make_session(week_index=w, order=o) for o in range(1, k + 1)])
        for w, k in sorted(per_week.items()) if w >= first_week
    ]
    return PlanResponse(summary="Suite", weeks=weeks, estimated_time_s=19800).model_dump_json()


def test_regenerate_keeps_fixed_sessions(repo, fake_garmin):
    _goal(repo, fake_garmin)
    generate_plan(repo, fake_garmin, FakeLLMProvider([valid_plan_json(14, 3)]))
    accept_plan(repo)
    cid = _cid(repo)
    sessions = repo.sessions(cid)
    with repo.transaction() as db:
        done = db.get(Session, sessions[0].id)  # semaine 1, séance 1
        done.status = "done"
        exported = db.get(Session, next(s.id for s in sessions if s.week_index == 3 and s.order == 1))
        exported.status, exported.scheduled_date = "exported", date(2026, 11, 17)
        exported.garmin_workout_id, exported.garmin_schedule_id = 301, 401
        db.add(done)
        db.add(exported)
    old_ids = {s.id for s in sessions}
    week3_garmin = FakeGarminClient(metrics=METRICS, today=date(2026, 11, 18))  # mercredi, semaine 3
    # semaine 3 : la séance exportée compte, deux séances au plus ; une 3e est refusée puis corrigée
    too_many = _plan_from(3, {w: 3 for w in range(3, 15)})
    llm = FakeLLMProvider([too_many, _plan_from(3, {3: 2, **{w: 3 for w in range(4, 15)}})])
    plan = generate_plan(repo, week3_garmin, llm)
    assert [w.week_index for w in plan.weeks] == list(range(3, 15))
    assert "Semaines 3 à 14 seulement : les séances suivantes sont fixées et comptent dans leur semaine :" in llm.calls[0]
    assert f"id={exported.id} | semaine 3" in llm.calls[0] and f"id={done.id} |" not in llm.calls[0]
    assert "semaine 3 : 3 séances pour 2 demandées (1 fixée)" in llm.calls[1]
    after = repo.sessions(cid)
    kept = {s.id for s in after if s.week_index < 3} | {exported.id}
    assert {s.id for s in after} & old_ids == kept  # semaines 1-2 intactes, todo des semaines ≥ 3 remplacées
    assert len(after) == 42
    assert [s.status for s in after if s.week_index == 3].count("todo") == 2
    cycle = repo.active_cycle()
    assert (cycle.plan_accepted, cycle.needs_generation) == (False, False)


# --- disponibilités ------------------------------------------------------------------------


def test_generate_plan_retries_on_unavailable_day(repo, fake_garmin):
    _goal(repo, fake_garmin, available_days=["mardi", "jeudi", "samedi"])
    bad = valid_plan_json(n_weeks=14, per_week=3).replace('"mardi"', '"lundi"')
    llm = FakeLLMProvider([bad, valid_plan_json(n_weeks=14, per_week=3)])
    generate_plan(repo, fake_garmin, llm)
    assert "lundi n'est pas un jour possible" in llm.calls[1]
    assert "Jours possibles : mardi, jeudi, samedi" in llm.calls[0]


def test_update_plan_settings_creates_proposal_with_note(repo, monday_garmin):
    _accepted_goal(repo, monday_garmin)
    llm = FakeLLMProvider([adjustment_json()])
    days = ["mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    # les séances existantes sont toutes le mardi : aucune n'est sur un jour retiré
    _, pid = update_plan_settings(repo, monday_garmin, llm, PlanSettingsUpdate(available_days=days))
    assert repo.active_cycle().available_days() == days
    assert "jours possibles : mardi, mercredi" in llm.calls[0]
    assert _proposals(repo) == [(pid, "pending")]


def test_update_plan_settings_removed_day_forces_claude_to_move_sessions(repo, monday_garmin):
    _accepted_goal(repo, monday_garmin)
    llm = FakeLLMProvider([adjustment_json(), adjustment_json()])
    with pytest.raises(LLMInvalidResponse):
        update_plan_settings(
            repo, monday_garmin, llm,
            PlanSettingsUpdate(available_days=["lundi", "mercredi", "jeudi"]),  # mardi retiré
        )
    assert "mardi n'est pas un jour possible" in llm.calls[1]
    assert repo.active_cycle().available_days() == list(ALL_DAYS)


def test_update_plan_settings_clears_long_run_day(repo, monday_garmin):
    _accepted_goal(repo, monday_garmin, long_run_day="mardi")
    assert repo.active_cycle().long_run_day == "mardi"
    llm = FakeLLMProvider([adjustment_json()])
    update_plan_settings(repo, monday_garmin, llm, PlanSettingsUpdate(long_run_day=""))
    assert repo.active_cycle().long_run_day is None
    assert "plus de jour imposé pour la sortie longue" in llm.calls[0]


def test_update_plan_settings_rejections(repo, monday_garmin):
    _accepted_goal(repo, monday_garmin)
    llm = FakeLLMProvider([])
    with pytest.raises(GoalError, match="au moins 3 jours possibles"):
        update_plan_settings(repo, monday_garmin, llm, PlanSettingsUpdate(available_days=["mardi", "jeudi"]))
    with pytest.raises(GoalError, match="sortie longue doit faire partie"):
        update_plan_settings(
            repo, monday_garmin, llm,
            PlanSettingsUpdate(available_days=["mardi", "jeudi", "samedi"], long_run_day="dimanche"),
        )
    with pytest.raises(GoalError, match="Aucune modification"):
        update_plan_settings(repo, monday_garmin, llm, PlanSettingsUpdate(available_days=list(ALL_DAYS)))
    assert llm.calls == []


def test_update_plan_settings_requires_accepted_plan(repo, monday_garmin):
    llm = FakeLLMProvider([])
    with pytest.raises(GoalError, match="Aucun plan en cours"):
        update_plan_settings(repo, monday_garmin, llm, PlanSettingsUpdate(include_bike=True))
    _goal(repo, monday_garmin)
    with pytest.raises(GoalError, match="validé"):
        update_plan_settings(repo, monday_garmin, llm, PlanSettingsUpdate(include_bike=True))
    assert llm.calls == []


def test_generate_plan_makes_pending_stale(repo, fake_garmin):
    _goal(repo, fake_garmin)
    old = repo.add(Proposal(analysis="avant", changes_json="[]"))
    generate_plan(repo, fake_garmin, FakeLLMProvider([valid_plan_json(14, 3)]))
    assert _proposals(repo) == [(old.id, "stale")]


def test_generate_ignores_fixed_sessions_after_end(repo, fake_garmin):
    _goal(repo, fake_garmin)
    generate_plan(repo, fake_garmin, FakeLLMProvider([valid_plan_json(14, 3)]))
    cid = _cid(repo)
    sessions = repo.sessions(cid)
    with repo.transaction() as db:
        done = db.get(Session, sessions[0].id)
        done.status = "done"
        late = db.get(Session, next(s.id for s in sessions if s.week_index == 13 and s.order == 1))
        late.status, late.scheduled_date = "exported", date(2027, 1, 26)
        c = db.get(Cycle, cid)
        c.end_date = date(2027, 1, 17)  # 11 semaines : la séance exportée est au-delà
        g = db.get(Goal, _active_goal(repo).id)
        g.race_date = c.end_date
        db.add_all([done, late, c, g])
    llm = FakeLLMProvider([_plan_from(1, {1: 2, **{w: 3 for w in range(2, 12)}})])
    generate_plan(repo, fake_garmin, llm)
    assert f"id={late.id} |" not in llm.calls[0] and f"id={done.id} | semaine 1" in llm.calls[0]
