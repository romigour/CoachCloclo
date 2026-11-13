from datetime import date

import pytest
from sqlmodel import select

from coach.analysis.zones import compute_zones
from coach.llm.provider import FakeLLMProvider, LLMInvalidResponse
from coach.llm.schemas import AdjustmentResponse
from coach.plan.models import Event, Proposal
from coach.services.adjust import ask_adjustment, save_proposal
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
