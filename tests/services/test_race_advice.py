import json
from datetime import date

import pytest

from coach.analysis.race_plan import RaceSettings
from coach.garmin.port import FakeGarminClient, Metrics
from coach.llm.provider import FakeLLMProvider, LLMInvalidResponse
from coach.llm.usage import CallUsage
from coach.services.goals import GoalInput, GoalUpdate, add_goal, update_goal
from coach.services.race_advice import ask_race_advice
from coach.services.race_strategy import get_race_view, save_settings

METRICS = Metrics(hr_max=190, hr_rest=50, pred_10k_s=2880)
USAGE = CallUsage(mode="cli", model="m", input_tokens=100, output_tokens=10, cost_usd=0.5, duration_ms=1000)


def advice_json(text="Pars prudemment, sans regarder la montre les premiers hectomètres.") -> str:
    return json.dumps(
        {
            "tips": [
                {"title": "Départ", "text": text},
                {"title": "Genou", "text": "Raccourcis la foulée dans les descentes."},
                {"title": "Final", "text": "Garde de la lucidité pour la fin."},
            ]
        }
    )


@pytest.fixture
def garmin():
    return FakeGarminClient(metrics=METRICS)


def make_goal(repo, garmin, notes=None):
    data = GoalInput(
        type="route", distance_km=10, d_plus_m=0, race_date=date(2027, 2, 7), sessions_per_week=3,
        target_time_s=2700, notes=notes,
    )
    return add_goal(repo, garmin, data)[0]


def test_ask_race_advice_saves_and_marks_fresh(repo, coach_home, garmin):
    goal = make_goal(repo, garmin, notes="Genou fragile")
    llm = FakeLLMProvider([advice_json()], usage=USAGE)
    view = ask_race_advice(repo, garmin, llm, goal.id)
    assert [t.title for t in view.advice.tips] == ["Départ", "Genou", "Final"]
    assert view.advice_at is not None and view.advice_stale is False
    assert "Genou fragile" in llm.calls[0]
    strategy = repo.race_strategy(goal.id)
    assert strategy.advice_json and strategy.advice_hash and strategy.advice_at
    stored = json.loads(strategy.view_json)  # la copie mobile porte les conseils
    assert stored["advice"]["tips"][0]["title"] == "Départ" and stored["advice_stale"] is False
    again = get_race_view(repo, garmin, goal.id)
    assert again.advice == view.advice and again.advice_stale is False
    assert [u.kind for u in repo.llm_usages()] == ["race_advice"]


def test_no_advice_is_not_stale(repo, coach_home, garmin):
    goal = make_goal(repo, garmin)
    view = get_race_view(repo, garmin, goal.id)
    assert view.advice is None and view.advice_at is None and view.advice_stale is False


def test_advice_stale_after_target_change(repo, coach_home, garmin):
    goal = make_goal(repo, garmin)
    ask_race_advice(repo, garmin, FakeLLMProvider([advice_json()]), goal.id)
    update_goal(repo, garmin, goal.id, GoalUpdate(target_time="44:00"))
    view = get_race_view(repo, garmin, goal.id)
    assert view.advice is not None and view.advice_stale is True


def test_advice_stale_after_notes_change_in_mobile_copy(repo, coach_home, garmin):
    goal = make_goal(repo, garmin)
    ask_race_advice(repo, garmin, FakeLLMProvider([advice_json()]), goal.id)
    update_goal(repo, garmin, goal.id, GoalUpdate(notes="Genou fragile"))
    stored = json.loads(repo.race_strategy(goal.id).view_json)  # copie rafraîchie sans relire la page
    assert stored["advice_stale"] is True


def test_advice_not_stale_after_start_time_change(repo, coach_home, garmin):
    goal = make_goal(repo, garmin)
    ask_race_advice(repo, garmin, FakeLLMProvider([advice_json()]), goal.id)
    view = save_settings(repo, garmin, goal.id, RaceSettings(start_time="09:15", carbs_g_h=60, water_ml_h=500))
    assert view.advice is not None and view.advice_stale is False


def test_invented_figure_retried_then_rejected(repo, coach_home, garmin):
    goal = make_goal(repo, garmin)
    bad = advice_json("Pars à 4:05/km.")
    llm = FakeLLMProvider([bad, bad])
    with pytest.raises(LLMInvalidResponse):
        ask_race_advice(repo, garmin, llm, goal.id)
    assert "4:05/km" in llm.calls[1]  # la relance cite le chiffre refusé
    assert repo.race_strategy(goal.id).advice_json is None


def test_advice_may_cite_guide_figures(repo, coach_home, garmin):
    goal = make_goal(repo, garmin)
    pace = get_race_view(repo, garmin, goal.id).guide.avg_pace_s_km
    text = f"Ton allure moyenne de {pace // 60}:{pace % 60:02d}/km est réaliste."
    view = ask_race_advice(repo, garmin, FakeLLMProvider([advice_json(text)]), goal.id)
    assert view.advice.tips[0].text == text
