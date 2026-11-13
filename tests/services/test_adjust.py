import json
from datetime import date

import pytest
from sqlmodel import select

from coach.analysis.zones import compute_zones
from coach.llm.provider import FakeLLMProvider, LLMInvalidResponse
from coach.llm.prompts import NEW_GOAL_ID
from coach.llm.schemas import AdjustmentResponse, GoalEstimate
from coach.plan.models import Event, Goal, Proposal
from coach.services.adjust import ask_adjustment, save_proposal
from tests.services.test_goals import monday_garmin  # noqa: F401 (fixture)
from tests.services.test_sync import METRICS, accepted_plan, adjustment_json, fake_garmin  # noqa: F401

TODAY = date(2026, 11, 4)


def _zones():
    return compute_zones(
        threshold_pace_s_km=METRICS.threshold_pace_s_km, pred_10k_s=None, garmin_hr_zones=None,
        hr_max=METRICS.hr_max, hr_rest=METRICS.hr_rest,
    )


def test_ask_adjustment_writes_nothing(repo, coach_home, fake_garmin, accepted_plan):
    adj = ask_adjustment(
        repo, fake_garmin, FakeLLMProvider([adjustment_json()]), accepted_plan, _zones(),
        repo.sessions(accepted_plan.id), TODAY,
    )
    assert repo.pending_proposal() is None and adj.analysis


def test_ask_adjustment_passes_change_note(repo, coach_home, fake_garmin, accepted_plan):
    llm = FakeLLMProvider([adjustment_json()])
    ask_adjustment(
        repo, fake_garmin, llm, accepted_plan, _zones(), repo.sessions(accepted_plan.id), TODAY,
        change_note="Course avancée d'une semaine",
    )
    assert "Course avancée d'une semaine" in llm.calls[0]


def test_save_proposal_stales_previous(repo):
    with repo.transaction() as db:
        first = save_proposal(db, AdjustmentResponse(analysis="A", changes=[]))
    with repo.transaction() as db:
        second = save_proposal(db, AdjustmentResponse(analysis="B", changes=[]))
    with repo.transaction() as db:
        status = {p.id: p.status for p in db.exec(select(Proposal)).all()}
    assert status == {first: "stale", second: "pending"}


def test_ask_adjustment_uses_received_cycle_constraints(repo, coach_home, fake_garmin, accepted_plan):
    """Les contraintes viennent du `cycle` reçu (copie modifiée), pas de la base."""
    edited = accepted_plan.model_copy(update={"available_days_json": '["jeudi", "samedi", "dimanche"]'})
    llm = FakeLLMProvider([adjustment_json(), adjustment_json()])
    with pytest.raises(LLMInvalidResponse):
        ask_adjustment(repo, fake_garmin, llm, edited, _zones(), repo.sessions(accepted_plan.id), TODAY)
    assert "Jours possibles : jeudi, samedi, dimanche" in llm.calls[0]
    assert "n'est pas un jour possible" in llm.calls[1]


def test_ask_adjustment_retries_when_session_falls_in_stored_unavailability(
    repo, coach_home, fake_garmin, accepted_plan
):
    """Les imprévus enregistrés en base sont transmis à Claude et contrôlés (séances de la semaine 2 gardées)."""
    repo.add(Event(
        cycle_id=accepted_plan.id, kind="unavailable", start_date=date(2026, 11, 9), end_date=date(2026, 11, 15),
    ))
    llm = FakeLLMProvider([adjustment_json(), adjustment_json()])
    with pytest.raises(LLMInvalidResponse):
        ask_adjustment(
            repo, fake_garmin, llm, accepted_plan, _zones(), repo.sessions(accepted_plan.id), TODAY,
        )
    assert "- indisponible du 09/11/2026 au 15/11/2026" in llm.calls[0]
    assert "tombe pendant indisponibilité du 09/11 au 15/11" in llm.calls[1]


def test_ask_adjustment_reads_goals_unless_given(repo, coach_home, fake_garmin, accepted_plan):
    """Sans `goals`, l'objectif vient de la base ; sinon la copie modifiée transmise est décrite."""
    llm = FakeLLMProvider([adjustment_json(), adjustment_json()])
    sessions = repo.sessions(accepted_plan.id)
    ask_adjustment(repo, fake_garmin, llm, accepted_plan, _zones(), sessions, TODAY)
    assert "le 2027-01-31" in llm.calls[0] and "Temps visé" not in llm.calls[0]
    edited = repo.goals_in(accepted_plan)[0].model_copy(update={"target_time_s": 14400})
    ask_adjustment(repo, fake_garmin, llm, accepted_plan, _zones(), sessions, TODAY, goals=[edited])
    assert "Temps visé : 4 h 00" in llm.calls[1]


def test_ask_adjustment_horizon_excludes_given_goals(repo, coach_home, fake_garmin, accepted_plan, monkeypatch):
    """Course avancée : l'objectif transmis (copie) n'apparaît pas aussi à l'horizon à son ancienne date."""
    import coach.services.adjust as adjust_module
    from tests.plan.factories import make_goal

    later = repo.add(make_goal(race_date=date(2027, 5, 30)))
    goal = repo.goals_in(accepted_plan)[0]
    edited_cycle = accepted_plan.model_copy(update={"end_date": date(2027, 1, 24)})
    edited = goal.model_copy(update={"race_date": date(2027, 1, 24)})
    seen = {}
    real = adjust_module.build_adjustment_prompt

    def spy(cycle, goals, horizon, *args, **kwargs):
        seen["goals"], seen["horizon"] = [g.id for g in goals], [g.id for g in horizon]
        return real(cycle, goals, horizon, *args, **kwargs)

    monkeypatch.setattr(adjust_module, "build_adjustment_prompt", spy)
    sessions = repo.sessions(accepted_plan.id)
    assert [g.id for g in repo.horizon_goals(edited_cycle)] == [goal.id, later.id]  # sans exclusion
    ask_adjustment(
        repo, fake_garmin, FakeLLMProvider([adjustment_json()]), edited_cycle, _zones(), sessions, TODAY,
        goals=[edited],
    )
    assert seen == {"goals": [goal.id], "horizon": [later.id]}


# --- estimations des objectifs ----------------------------------------------------------------


def _estimate_json(*estimates, changes=None) -> str:
    return AdjustmentResponse(
        analysis="ok", changes=changes or [],
        estimated_times=[GoalEstimate(goal_id=i, seconds=s) for i, s in estimates],
    ).model_dump_json()


def test_ask_adjustment_requires_estimate_for_claude_goal_without_time(
    repo, coach_home, fake_garmin, accepted_plan
):
    """Un objectif `claude` sans temps intégré au cycle (ici nouveau, id provisoire 0) doit être estimé."""
    from tests.plan.factories import make_goal

    existing = repo.goals_in(accepted_plan)[0]
    new = make_goal(type="route", distance_km=10, d_plus_m=0, race_date=date(2026, 12, 20),
                    priority="secondaire", target_source="claude")
    llm = FakeLLMProvider([adjustment_json(), _estimate_json((NEW_GOAL_ID, 3000), (99, 1))])
    adj = ask_adjustment(
        repo, fake_garmin, llm, accepted_plan, _zones(), repo.sessions(accepted_plan.id), TODAY,
        goals=[new, existing],
    )
    assert "Pour chaque objectif sans temps visé (ids 0 (2026-12-20))" in llm.calls[0]
    assert "estimated_times : estimation manquante pour l'objectif 0" in llm.calls[1]
    assert [(e.goal_id, e.seconds) for e in adj.estimated_times] == [(0, 3000)]  # estimations non demandées ignorées


def test_ask_adjustment_rejects_session_on_race_day(repo, coach_home, fake_garmin, accepted_plan):
    """Les séances du jour d'une course du cycle sont refusées (mardi 10/11 : séances de la semaine 2)."""
    from tests.plan.factories import make_goal

    sessions = repo.sessions(accepted_plan.id)
    s = next(x for x in sessions if x.week_index == 2 and x.order == 1)  # mardi 10/11
    race = make_goal(race_date=date(2026, 11, 10), priority="plaisir", target_source="user", target_time_s=3600)
    llm = FakeLLMProvider([adjustment_json(), adjustment_json()])
    with pytest.raises(LLMInvalidResponse):
        ask_adjustment(
            repo, fake_garmin, llm, accepted_plan, _zones(), sessions, TODAY,
            goals=[race, *repo.goals_in(accepted_plan)],
        )
    assert f"séance {s.id} : tombe le jour de la course du 10/11" in llm.calls[1]
    assert "semaine 2 : 3 séances pour 2 possibles (1 course(s) cette semaine)" in llm.calls[1]


def test_save_proposal_stores_estimates(repo):
    adj = AdjustmentResponse(analysis="A", changes=[], estimated_times=[GoalEstimate(goal_id=4, seconds=3000)])
    with repo.transaction() as db:
        pid = save_proposal(db, adj)
    with repo.transaction() as db:
        assert json.loads(db.get(Proposal, pid).estimates_json) == [{"goal_id": 4, "seconds": 3000}]


def test_accept_proposal_applies_estimates(repo, coach_home, fake_garmin, accepted_plan):
    """À l'acceptation, les estimations vont aux objectifs encore en mode `claude`."""
    from coach.services.garmin_export import apply_proposal
    from tests.plan.factories import make_goal

    claude = repo.add(make_goal(race_date=date(2026, 12, 20), target_source="claude"))
    user = repo.add(make_goal(race_date=date(2026, 12, 6), target_source="user", target_time_s=7000))
    archived = repo.add(make_goal(race_date=date(2026, 12, 13), target_source="claude", status="archived"))
    estimates = [{"goal_id": g.id, "seconds": 9000} for g in (claude, user, archived)] + [{"goal_id": 999, "seconds": 1}]
    p = repo.add(Proposal(analysis="a", changes_json="[]", estimates_json=json.dumps(estimates)))
    apply_proposal(repo, fake_garmin, p.id)
    with repo.transaction() as db:
        got = {g.id: (g.target_time_s, g.target_source) for g in (db.get(Goal, x.id) for x in (claude, user, archived))}
    assert got == {claude.id: (9000, "claude"), user.id: (7000, "user"), archived.id: (None, "claude")}


def test_add_goal_estimate_applied_on_accept(repo, coach_home, monday_garmin):
    """Ajout d'un Secondaire sans temps : l'estimation porte l'id provisoire, enregistrée sous le vrai id."""
    from coach.services.garmin_export import apply_proposal
    from coach.services.goals import add_goal
    from coach.llm.schemas import Change
    from tests.services.test_goals import accepted_goal, other_input

    accepted_goal(repo, monday_garmin)
    week7 = next(s for s in repo.sessions(repo.active_cycle().id) if s.week_index == 7 and s.order == 3)
    remove = Change(op="remove", session_id=week7.id, reason="course dimanche")
    llm = FakeLLMProvider([_estimate_json((NEW_GOAL_ID, 3000), changes=[remove])])
    goal, result = add_goal(repo, monday_garmin, llm, other_input())
    assert goal.target_time_s is None  # pas avant l'acceptation
    with repo.transaction() as db:
        assert json.loads(db.get(Proposal, result.proposal_id).estimates_json) == [{"goal_id": goal.id, "seconds": 3000}]
    apply_proposal(repo, monday_garmin, result.proposal_id)
    with repo.transaction() as db:
        g = db.get(Goal, goal.id)
    assert (g.target_time_s, g.target_source) == (3000, "claude")
