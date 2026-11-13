"""Clôture des objectifs et du cycle, préparation du cycle suivant."""

import json
from datetime import date

import pytest
from sqlmodel import select

from coach.garmin.port import FakeGarminClient
from coach.llm.provider import FakeLLMProvider
from coach.plan import calendar
from coach.plan.models import Cycle, Event, Goal, Proposal
from coach.services.cycles import NextCycleInput, close_passed, prepare_next_cycle
from coach.services.events import EventError, resume_injury
from coach.services.goals import GoalError
from coach.services.plans import PlanSettingsUpdate, generate_plan
from tests.llm.factories import valid_plan_json
from tests.plan.factories import make_cycle, make_goal
from tests.services.test_goals import METRICS

RACE = date(2027, 5, 23)  # dimanche : Principal du cycle terminé
NEXT = date(2027, 8, 29)  # dimanche : objectif à venir
DAYS = ["mardi", "jeudi", "samedi", "dimanche"]


def _garmin(today: date) -> FakeGarminClient:
    return FakeGarminClient(metrics=METRICS, today=today)


def _finished(repo, *, status: str = "done") -> Cycle:
    """Cycle qui finit au Principal du 23/05/2027 (couru) ; un objectif reste à venir le 29/08/2027."""
    cycle = repo.add(
        make_cycle(
            plan_start=date(2027, 3, 1), end_date=RACE, status=status, plan_accepted=True,
            sessions_per_week=4, available_days_json=json.dumps(DAYS), long_run_day="dimanche", include_bike=True,
        )
    )
    repo.add(make_goal(race_date=date(2027, 4, 11), priority="plaisir", status="done", distance_km=10))
    repo.add(make_goal(race_date=RACE, status="done" if status == "done" else "active"))
    repo.add(make_goal(race_date=NEXT, type="route", distance_km=21.1, d_plus_m=0,
                       target_time_s=6000, target_source="user"))
    return cycle


# --- clôture ------------------------------------------------------------------------------------


def test_close_passed_marks_goals_and_cycle(repo):
    cycle = _finished(repo, status="active")
    repo.add(Proposal(analysis="a", changes_json="[]", status="pending"))
    close_passed(repo, date(2027, 5, 24))
    assert repo.active_cycle() is None
    with repo.transaction() as db:
        assert db.get(Cycle, cycle.id).status == "done"
        assert all(p.status == "stale" for p in db.exec(select(Proposal)).all())
    assert [g.race_date for g in repo.upcoming_goals()] == [NEXT]


def test_close_passed_keeps_goal_of_the_day(repo):
    _finished(repo, status="active")
    close_passed(repo, RACE)
    assert repo.active_cycle() is not None
    assert [g.race_date for g in repo.upcoming_goals()] == [RACE, NEXT]


# --- préparation du cycle suivant ---------------------------------------------------------------


def test_prepare_next_cycle_dates_and_settings(repo):
    prev = _finished(repo)
    cycle = prepare_next_cycle(repo, _garmin(date(2027, 5, 24)))
    assert cycle.status == "active" and repo.active_cycle().id == cycle.id
    assert (cycle.plan_start, cycle.end_date) == (date(2027, 5, 24), NEXT)
    assert cycle.sessions_per_week == 4 and cycle.available_days() == DAYS
    assert cycle.long_run_day == "dimanche" and cycle.include_bike is True
    assert cycle.needs_generation is True and cycle.plan_accepted is False
    principal = next(g for g in repo.past_goals() if g.race_date == RACE)
    assert cycle.recovery_from_goal_id == principal.id
    assert cycle.id != prev.id


def test_prepare_next_cycle_overrides_settings(repo):
    _finished(repo)
    data = PlanSettingsUpdate(available_days=["lundi", "mercredi", "vendredi", "dimanche"], long_run_day="",
                              include_bike=False)
    cycle = prepare_next_cycle(repo, _garmin(date(2027, 5, 24)), data)
    assert cycle.available_days() == ["lundi", "mercredi", "vendredi", "dimanche"]
    assert cycle.long_run_day is None and cycle.include_bike is False


def test_prepare_next_cycle_changes_sessions_per_week(repo):
    _finished(repo)
    cycle = prepare_next_cycle(repo, _garmin(date(2027, 5, 24)), NextCycleInput(sessions_per_week=3))
    assert cycle.sessions_per_week == 3 and cycle.available_days() == DAYS


def test_prepare_next_cycle_checks_sessions_against_days(repo):
    _finished(repo)
    with pytest.raises(GoalError, match="au moins 5 jours"):
        prepare_next_cycle(repo, _garmin(date(2027, 5, 24)), NextCycleInput(sessions_per_week=5))
    with pytest.raises(ValueError):
        NextCycleInput(sessions_per_week=8)
    assert repo.active_cycle() is None


def test_prepare_next_cycle_includes_race_before_next_monday(repo):
    """Cycle fini un mardi, Plaisir le samedi suivant : la course appartient au nouveau cycle."""
    repo.add(make_cycle(plan_start=date(2027, 3, 1), end_date=date(2027, 5, 18), status="done"))
    repo.add(make_goal(race_date=date(2027, 5, 18), status="done"))
    plaisir = repo.add(make_goal(race_date=date(2027, 5, 22), priority="plaisir", distance_km=10))
    repo.add(make_goal(race_date=NEXT))
    garmin = _garmin(date(2027, 5, 19))
    cycle = prepare_next_cycle(repo, garmin)
    assert (cycle.plan_start, cycle.end_date) == (date(2027, 5, 17), NEXT)
    assert plaisir.id in [g.id for g in repo.goals_in(cycle)]


def test_prepare_next_cycle_rejects_bad_settings(repo):
    _finished(repo)
    with pytest.raises(GoalError, match="au moins 4 jours"):
        prepare_next_cycle(repo, _garmin(date(2027, 5, 24)), PlanSettingsUpdate(available_days=["lundi"]))
    assert repo.active_cycle() is None


def test_prepare_next_cycle_late_starts_this_week(repo):
    _finished(repo)
    cycle = prepare_next_cycle(repo, _garmin(date(2027, 6, 2)))  # mercredi, 10 jours après la course
    assert cycle.plan_start == date(2027, 5, 31)


def test_prepare_next_cycle_closes_passed_first(repo):
    """Synchro pas encore faite : la préparation clôt d'abord le cycle passé."""
    _finished(repo, status="active")
    cycle = prepare_next_cycle(repo, _garmin(date(2027, 5, 24)))
    assert cycle.plan_start == date(2027, 5, 24) and cycle.end_date == NEXT


def test_prepare_next_cycle_copies_open_injury(repo):
    prev = _finished(repo)
    repo.add(Event(cycle_id=prev.id, kind="injury", start_date=date(2027, 5, 20), note="mollet"))
    repo.add(Event(cycle_id=prev.id, kind="unavailable", start_date=date(2027, 5, 1), end_date=date(2027, 5, 2)))
    cycle = prepare_next_cycle(repo, _garmin(date(2027, 5, 24)))
    copied = repo.open_injury(cycle.id)
    assert copied is not None and copied.id != repo.open_injury(prev.id).id
    assert (copied.start_date, copied.end_date, copied.note) == (date(2027, 5, 20), None, "mollet")
    assert [e.kind for e in repo.events(cycle.id)] == ["injury"]


def test_prepare_next_cycle_without_goal_is_error(repo):
    _finished(repo)
    with repo.transaction() as db:
        g = db.exec(select(Goal).where(Goal.race_date == NEXT)).one()
        g.status = "archived"
        db.add(g)
    with pytest.raises(GoalError, match="Aucun objectif à venir"):
        prepare_next_cycle(repo, _garmin(date(2027, 5, 24)))
    assert repo.active_cycle() is None


def test_prepare_next_cycle_with_active_cycle_is_error(repo):
    _finished(repo)
    prepare_next_cycle(repo, _garmin(date(2027, 5, 24)))
    with pytest.raises(GoalError, match="Un cycle est déjà en cours"):
        prepare_next_cycle(repo, _garmin(date(2027, 5, 24)))


def test_generation_prompt_has_recovery_note(repo):
    _finished(repo)
    garmin = _garmin(date(2027, 5, 24))
    cycle = prepare_next_cycle(repo, garmin)
    n = calendar.n_weeks(cycle.plan_start, cycle.end_date)
    llm = FakeLLMProvider([valid_plan_json(n, 3, estimated_time_s=None)])
    generate_plan(repo, garmin, llm)
    prompt = llm.calls[0]
    note = "Commence par une récupération adaptée à Trail de 42 km couru le 23/05/2027."
    assert note in prompt
    # juste après la ligne des objectifs
    assert prompt.index(note) < prompt.index("Construis un plan")


def test_generation_prompt_without_recovery_has_no_note(repo):
    _finished(repo)
    garmin = _garmin(date(2027, 5, 24))
    cycle = prepare_next_cycle(repo, garmin)
    with repo.transaction() as db:
        c = db.get(Cycle, cycle.id)
        c.recovery_from_goal_id = None
        db.add(c)
    n = calendar.n_weeks(cycle.plan_start, cycle.end_date)
    llm = FakeLLMProvider([valid_plan_json(n, 3, estimated_time_s=None)])
    generate_plan(repo, garmin, llm)
    assert "récupération adaptée" not in llm.calls[0]


# --- arrêt d'un cycle terminé -------------------------------------------------------------------


def test_resume_injury_of_finished_cycle_is_error(repo):
    prev = _finished(repo)
    old = repo.add(Event(cycle_id=prev.id, kind="injury", start_date=date(2027, 5, 20)))
    garmin = _garmin(date(2027, 5, 24))
    with pytest.raises(EventError, match="Cet arrêt appartient à un cycle terminé"):
        resume_injury(repo, garmin, FakeLLMProvider([]), old.id, date(2027, 5, 24))
    cycle = prepare_next_cycle(repo, garmin)
    with pytest.raises(EventError, match="Cet arrêt appartient à un cycle terminé"):
        resume_injury(repo, garmin, FakeLLMProvider([]), old.id, date(2027, 5, 24))
    assert repo.open_injury(prev.id) is not None
    # la copie, elle, appartient au nouveau cycle : la reprise est enregistrée (Claude n'est pas
    # sollicité tant que le plan n'est pas généré)
    copied = repo.open_injury(cycle.id)
    result = resume_injury(repo, garmin, FakeLLMProvider([]), copied.id, date(2027, 5, 24))
    assert result.event_id == copied.id and repo.open_injury(cycle.id) is None
