"""Scénario de bout en bout : la saison réelle de l'athlète (ultra en mai, trail et semi au printemps)."""

from datetime import date

import pytest

from coach.garmin.port import FakeGarminClient
from coach.llm.provider import FakeLLMProvider, LLMInvalidResponse
from coach.llm.schemas import GoalEstimate, PlanResponse, WeekSpec
from coach.services.goals import GoalError, GoalInput, add_goal
from coach.services.plans import generate_plan
from tests.llm.factories import make_session
from tests.services.test_goals import METRICS

TODAY = date(2027, 1, 4)  # lundi : semaine 1 du cycle
SEMI = date(2027, 3, 21)  # dimanche, 6 jours avant le trail
TRAIL_20 = date(2027, 3, 27)  # samedi
TRAIL_30 = date(2027, 3, 28)  # dimanche, lendemain
ULTRA = date(2027, 5, 22)  # samedi
N_WEEKS = 20
RACES = {SEMI, TRAIL_20, TRAIL_30, ULTRA}
ESTIMATES = {1: 100_000, 2: 9_000, 3: 12_000, 4: 7_000}  # objectif -> secondes (ultra, trail 20, 30 km, semi)
DAYS = ["mardi", "mercredi", "jeudi", "vendredi"]  # jamais un jour de course


def goal(**overrides) -> GoalInput:
    data = {"type": "trail", "distance_km": 20, "d_plus_m": 800, "race_date": TRAIL_20, "priority": "secondaire"}
    data.update(overrides)
    return GoalInput(**data)


def plan_json(per_week: dict[int, list[str]]) -> str:
    """Plan de 20 semaines : 4 séances par semaine sauf `per_week` (semaine -> jours suggérés)."""
    weeks = []
    for w in range(1, N_WEEKS + 1):
        days = per_week.get(w, DAYS)
        weeks.append(WeekSpec(
            week_index=w, focus=f"Semaine {w}",
            sessions=[make_session(week_index=w, order=o, suggested_day=d) for o, d in enumerate(days, start=1)],
        ))
    return PlanResponse(
        summary="Saison", weeks=weeks, estimated_times=[GoalEstimate(goal_id=i, seconds=t) for i, t in ESTIMATES.items()]
    ).model_dump_json()


# semaine 11 : semi le dimanche 21 (1 course) ; semaine 12 : trail 20 km et 30 km (2 courses) ; semaine 20 : ultra
GOOD = {11: DAYS[:3], 12: ["mardi", "jeudi"], 20: DAYS[:3]}


@pytest.fixture
def season(repo):
    garmin = FakeGarminClient(metrics=METRICS, today=TODAY)
    llm = FakeLLMProvider([])
    add_goal(repo, garmin, llm, goal(
        distance_km=100, d_plus_m=6000, race_date=ULTRA, priority="principal", sessions_per_week=4))
    return repo, garmin


def test_season_goals_and_gap_rule(season):
    repo, garmin = season
    cycle = repo.active_cycle()
    assert (cycle.plan_start, cycle.end_date, cycle.sessions_per_week) == (TODAY, ULTRA, 4)

    add_goal(repo, garmin, FakeLLMProvider([]), goal())  # trail 20 km Secondaire, samedi
    add_goal(repo, garmin, FakeLLMProvider([]), goal(distance_km=30, race_date=TRAIL_30, priority="plaisir"))

    with pytest.raises(GoalError) as e:  # semi Secondaire à 6 jours du trail Secondaire
        add_goal(repo, garmin, FakeLLMProvider([]), goal(type="route", distance_km=21.1, d_plus_m=0, race_date=SEMI))
    assert str(e.value) == (
        "Trail de 20 km du 27/03/2027 (Secondaire) est à 6 jours : passe l'un des deux en Plaisir ou déplace-le"
    )
    add_goal(repo, garmin, FakeLLMProvider([]),
             goal(type="route", distance_km=21.1, d_plus_m=0, race_date=SEMI, priority="plaisir"))
    assert {g.race_date for g in repo.upcoming_goals()} == RACES
    assert repo.active_cycle().end_date == ULTRA  # les courses du printemps ne déplacent pas la fin du cycle


def _full_season(repo, garmin):
    add_goal(repo, garmin, FakeLLMProvider([]), goal())
    add_goal(repo, garmin, FakeLLMProvider([]), goal(distance_km=30, race_date=TRAIL_30, priority="plaisir"))
    add_goal(repo, garmin, FakeLLMProvider([]),
             goal(type="route", distance_km=21.1, d_plus_m=0, race_date=SEMI, priority="plaisir"))


def test_generated_plan_respects_race_days(season):
    repo, garmin = season
    _full_season(repo, garmin)
    llm = FakeLLMProvider([plan_json(GOOD)])
    plan = generate_plan(repo, garmin, llm)
    assert len(plan.weeks) == N_WEEKS and len(llm.calls) == 1
    cycle_id = repo.active_cycle().id
    sessions = repo.sessions(cycle_id)
    assert all(s.suggested_day not in ("samedi", "dimanche") for s in sessions if s.week_index in (11, 12))
    assert sum(1 for s in sessions if s.week_index == 12) == 4 - 2  # sessions_per_week − 2 courses


def test_session_on_race_day_is_rejected(season):
    repo, garmin = season
    _full_season(repo, garmin)
    on_race_day = plan_json({**GOOD, 12: ["mardi", "samedi"]})  # samedi 27/03 = jour du trail
    llm = FakeLLMProvider([on_race_day, plan_json(GOOD)])
    generate_plan(repo, garmin, llm)
    assert len(llm.calls) == 2  # première réponse refusée, seconde acceptée
    assert "tombe le jour de la course du 27/03" in llm.calls[1]


def test_too_many_sessions_in_double_race_week_is_rejected(season):
    repo, garmin = season
    _full_season(repo, garmin)
    too_many = plan_json({**GOOD, 12: ["mardi", "mercredi", "jeudi"]})  # 3 séances + 2 courses > 4
    llm = FakeLLMProvider([too_many, plan_json(GOOD)])
    generate_plan(repo, garmin, llm)
    assert len(llm.calls) == 2
    assert "semaine 12 : 3 séances pour 2 possibles (2 course(s) cette semaine)" in llm.calls[1]


def test_two_invalid_answers_raise(season):
    repo, garmin = season
    _full_season(repo, garmin)
    bad = plan_json({**GOOD, 12: ["mardi", "samedi", "dimanche"]})
    with pytest.raises(LLMInvalidResponse):
        generate_plan(repo, garmin, FakeLLMProvider([bad, bad]))
    assert repo.sessions(repo.active_cycle().id) == []
