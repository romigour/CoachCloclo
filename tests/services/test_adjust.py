from datetime import date

import pytest
from sqlmodel import select

from coach.analysis.zones import compute_zones
from coach.llm.provider import FakeLLMProvider, LLMInvalidResponse
from coach.llm.schemas import AdjustmentResponse
from coach.plan.models import Proposal
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


def test_ask_adjustment_uses_received_goal_constraints(repo, coach_home, fake_garmin, accepted_plan):
    """Les contraintes viennent du `goal` reçu (copie modifiée), pas de la base."""
    edited = accepted_plan.model_copy(update={"available_days_json": '["jeudi", "samedi", "dimanche"]'})
    llm = FakeLLMProvider([adjustment_json(), adjustment_json()])
    with pytest.raises(LLMInvalidResponse):
        ask_adjustment(repo, fake_garmin, llm, edited, _zones(), repo.sessions(accepted_plan.id), TODAY)
    assert "Jours possibles : jeudi, samedi, dimanche" in llm.calls[0]
    assert "n'est pas un jour possible" in llm.calls[1]
