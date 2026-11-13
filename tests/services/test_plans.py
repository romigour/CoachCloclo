from datetime import date

import pytest

from coach.garmin.port import FakeGarminClient, Metrics
from coach.llm.provider import FakeLLMProvider, LLMInvalidResponse
from coach.llm.schemas import GoalEstimate, PlanResponse, WeekSpec
from coach.plan.models import ALL_DAYS, Cycle, Goal, Proposal, Session
from coach.services import CoachError
from coach.services.context import refresh_snapshot
from coach.services.goals import GoalError
from coach.services.plans import PlanSettingsUpdate, accept_plan, generate_plan, update_plan_settings
from tests.llm.factories import make_plan, make_session, valid_plan_json
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
    assert len(sessions) == 41 and all(s.status == "todo" for s in sessions)
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
    assert len(repo.sessions(_cid(repo))) == 27
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


def _plan_from(first_week: int, per_week: dict[int, int], estimates: dict[int, int] | None = None) -> str:
    """Plan des semaines `first_week`.. avec `per_week[w]` séances (orders 1..k) ; `estimates`
    (goal_id -> secondes) vaut par défaut 5 h 30 pour l'objectif 1."""
    weeks = [
        WeekSpec(week_index=w, focus=f"Semaine {w}",
                 sessions=[make_session(week_index=w, order=o, suggested_day="jeudi") for o in range(1, k + 1)])
        for w, k in sorted(per_week.items()) if w >= first_week
    ]
    estimates = {1: 19800} if estimates is None else estimates
    return PlanResponse(
        summary="Suite", weeks=weeks,
        estimated_times=[GoalEstimate(goal_id=i, seconds=t) for i, t in estimates.items()],
    ).model_dump_json()


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
    too_many = _plan_from(3, {**{w: 3 for w in range(3, 14)}, 14: 2})
    llm = FakeLLMProvider([too_many, _plan_from(3, {3: 2, **{w: 3 for w in range(4, 14)}, 14: 2})])
    plan = generate_plan(repo, week3_garmin, llm)
    assert [w.week_index for w in plan.weeks] == list(range(3, 15))
    assert "Semaines 3 à 14 seulement : les séances suivantes sont fixées et comptent dans leur semaine :" in llm.calls[0]
    assert f"id={exported.id} | semaine 3" in llm.calls[0] and f"id={done.id} |" not in llm.calls[0]
    assert "semaine 3 : 3 séances pour 2 demandées (1 fixée)" in llm.calls[1]
    after = repo.sessions(cid)
    kept = {s.id for s in after if s.week_index < 3} | {exported.id}
    assert {s.id for s in after} & old_ids == kept  # semaines 1-2 intactes, todo des semaines ≥ 3 remplacées
    assert len(after) == 41
    assert [s.status for s in after if s.week_index == 3].count("todo") == 2
    cycle = repo.active_cycle()
    assert (cycle.plan_accepted, cycle.needs_generation) == (False, False)


# --- disponibilités ------------------------------------------------------------------------


def test_generate_plan_retries_on_unavailable_day(repo, fake_garmin):
    _goal(repo, fake_garmin, available_days=["mardi", "jeudi", "samedi"])
    bad = valid_plan_json(n_weeks=14, per_week=3).replace('"jeudi"', '"lundi"')
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
    llm = FakeLLMProvider([_plan_from(1, {1: 2, **{w: 3 for w in range(2, 11)}, 11: 2})])
    generate_plan(repo, fake_garmin, llm)
    assert f"id={late.id} |" not in llm.calls[0] and f"id={done.id} | semaine 1" in llm.calls[0]


# --- plusieurs objectifs -----------------------------------------------------------------------


def _two_goals(repo, garmin) -> tuple[Goal, Goal]:
    """Principal au 07/02/2027 (semaine 14) et Secondaire au 20/12/2026 (dimanche, semaine 7), sans temps."""
    from coach.services.goals import add_goal
    from tests.services.test_goals import other_input

    principal = _goal(repo, garmin)
    secondary, result = add_goal(repo, garmin, FakeLLMProvider([]), other_input())  # brouillon : pas d'appel
    assert result.needs_generation
    return principal, secondary


def _plan_json(per_week: dict[int, int], estimates: dict[int, int]) -> str:
    from tests.llm.factories import make_plan

    plan = make_plan(14, [per_week.get(w, 3) for w in range(1, 15)])
    plan.estimated_times = [GoalEstimate(goal_id=i, seconds=s) for i, s in estimates.items()]
    return plan.model_dump_json()


def test_generate_saves_estimates_per_goal(repo, fake_garmin):
    principal, secondary = _two_goals(repo, fake_garmin)
    ok = _plan_json({7: 2, 14: 2}, {principal.id: 19800, secondary.id: 2700})
    llm = FakeLLMProvider([_plan_json({7: 2, 14: 2}, {principal.id: 19800}), ok])
    generate_plan(repo, fake_garmin, llm)
    assert "Objectifs du cycle :" in llm.calls[0] and "priorité Secondaire" in llm.calls[0]
    assert f"ids {secondary.id} (2026-12-20), {principal.id} (2027-02-07)" in llm.calls[0]
    assert f"estimated_times : estimation manquante pour l'objectif {secondary.id}" in llm.calls[1]
    times = {g.id: (g.target_time_s, g.target_source) for g in repo.upcoming_goals()}
    assert times == {principal.id: (19800, "claude"), secondary.id: (2700, "claude")}


def test_generate_rejects_implausible_estimate_per_goal(repo, fake_garmin):
    principal, secondary = _two_goals(repo, fake_garmin)
    bad = _plan_json({7: 2, 14: 2}, {principal.id: 19800, secondary.id: 600})  # 10 km en 10 min
    llm = FakeLLMProvider([bad, bad])
    with pytest.raises(LLMInvalidResponse):
        generate_plan(repo, fake_garmin, llm)
    assert (
        f"estimated_times : 600 s invraisemblable pour l'objectif {secondary.id} (au moins 1500 s)"
    ) in llm.calls[1]


def test_generate_counts_races_in_their_week(repo, fake_garmin):
    principal, secondary = _two_goals(repo, fake_garmin)
    estimates = {principal.id: 19800, secondary.id: 2700}
    llm = FakeLLMProvider([_plan_json({14: 2}, estimates), _plan_json({7: 2, 14: 2}, estimates)])
    generate_plan(repo, fake_garmin, llm)
    assert "semaine 7 : 3 séances pour 2 possibles (1 course(s) cette semaine)" in llm.calls[1]
    assert len(repo.sessions(_cid(repo))) == 40


def test_generate_rejects_session_on_race_day(repo, fake_garmin):
    principal, secondary = _two_goals(repo, fake_garmin)
    plan = PlanResponse.model_validate_json(_plan_json({7: 2, 14: 2}, {principal.id: 19800, secondary.id: 2700}))
    plan.weeks[6].sessions[1].suggested_day = "dimanche"
    llm = FakeLLMProvider([plan.model_dump_json(), _plan_json({7: 2, 14: 2}, {principal.id: 19800, secondary.id: 2700})])
    generate_plan(repo, fake_garmin, llm)
    assert "semaine 7, séance 2 : tombe le jour de la course du 20/12" in llm.calls[1]


def test_accept_rejected_while_plan_must_be_regenerated(repo, fake_garmin):
    """Cycle à régénérer (needs_generation) : le plan affiché est périmé, il ne peut pas être validé."""
    _goal(repo, fake_garmin)
    with pytest.raises(GoalError, match="Le plan doit d'abord être recalculé"):
        accept_plan(repo)
    assert repo.active_cycle().plan_accepted is False
    generate_plan(repo, fake_garmin, FakeLLMProvider([valid_plan_json(14, 3)]))
    accept_plan(repo)
    assert repo.active_cycle().plan_accepted is True


def test_generate_rejects_session_before_today(repo, fake_garmin):
    """Aujourd'hui mercredi 04/11 : une séance de la semaine 1 placée le mardi est déjà passée."""
    _goal(repo, fake_garmin)
    past = valid_plan_json(14, 3).replace('"jeudi"', '"mardi"')
    llm = FakeLLMProvider([past, valid_plan_json(14, 3)])
    generate_plan(repo, fake_garmin, llm)
    assert "semaine 1, séance 1 : tombe avant aujourd'hui (03/11)" in llm.calls[1]
    assert "semaine 2, séance 1 : tombe avant aujourd'hui" not in llm.calls[1]


def test_generate_rejects_session_after_cycle_end(repo, fake_garmin):
    """Course (fin du cycle) le mercredi 03/02/2027 : une séance le jeudi de la semaine 14 est refusée."""
    _goal(repo, fake_garmin, race_date=date(2027, 2, 3))
    late = make_plan(14, [3] * 13 + [1], estimated_time_s=19800)
    ok = late.model_copy(deep=True)
    ok.weeks[-1].sessions[0].suggested_day = "lundi"
    llm = FakeLLMProvider([late.model_dump_json(), ok.model_dump_json()])
    generate_plan(repo, fake_garmin, llm)
    assert "semaine 14, séance 1 : tombe après la fin du cycle (03/02)" in llm.calls[1]
