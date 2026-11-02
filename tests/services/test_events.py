from datetime import date

import pytest
from pydantic import ValidationError

from coach.plan.models import Event
from coach.services import CoachError
from coach.services.events import EventError, EventInput, build_event
from tests.plan.factories import make_db_session, make_goal

TODAY = date(2026, 11, 3)


@pytest.fixture
def goal(repo):
    return repo.add(make_goal())  # plan du lundi 2026-10-26 au 2027-01-31 (15 semaines)


def build(repo, goal, **data):
    return build_event(repo, goal, EventInput(**data), TODAY)


def test_event_error_is_coach_error():
    assert issubclass(EventError, CoachError)


def test_unavailable_valid_writes_nothing(repo, goal):
    e = build(repo, goal, kind="unavailable", start_date=date(2026, 11, 5), end_date=date(2026, 11, 8), note="voyage")
    assert (e.goal_id, e.kind, e.start_date, e.end_date, e.note) == (
        goal.id,
        "unavailable",
        date(2026, 11, 5),
        date(2026, 11, 8),
        "voyage",
    )
    assert e.id is None and repo.events(goal.id) == []


def test_unavailable_single_day_ok(repo, goal):
    assert build(repo, goal, kind="unavailable", start_date=date(2026, 11, 5), end_date=date(2026, 11, 5))


@pytest.mark.parametrize("dates", [{}, {"start_date": date(2026, 11, 5)}, {"end_date": date(2026, 11, 5)}])
def test_unavailable_requires_both_dates(repo, goal, dates):
    with pytest.raises(EventError, match="Indique les dates de début et de fin"):
        build(repo, goal, kind="unavailable", **dates)


def test_unavailable_end_before_start(repo, goal):
    with pytest.raises(EventError, match="La fin doit être après le début"):
        build(repo, goal, kind="unavailable", start_date=date(2026, 11, 8), end_date=date(2026, 11, 5))


def test_injury_open_and_closed(repo, goal):
    assert build(repo, goal, kind="injury", start_date=date(2026, 11, 3)).end_date is None
    e = build(repo, goal, kind="injury", start_date=date(2026, 11, 3), end_date=date(2026, 11, 10))
    assert e.end_date == date(2026, 11, 10)


def test_injury_requires_start(repo, goal):
    with pytest.raises(EventError, match="Indique la date de début"):
        build(repo, goal, kind="injury")


def test_injury_end_before_start(repo, goal):
    with pytest.raises(EventError, match="La fin doit être après le début"):
        build(repo, goal, kind="injury", start_date=date(2026, 11, 8), end_date=date(2026, 11, 5))


def test_second_open_injury_refused(repo, goal):
    repo.add(Event(goal_id=goal.id, kind="injury", start_date=date(2026, 10, 30)))
    with pytest.raises(EventError, match="Un arrêt est déjà en cours : signale d'abord la reprise"):
        build(repo, goal, kind="injury", start_date=date(2026, 11, 3))


def test_open_injury_of_other_goal_or_closed_does_not_block(repo, goal):
    repo.add(Event(goal_id=goal.id + 1, kind="injury", start_date=date(2026, 10, 30)))
    repo.add(Event(goal_id=goal.id, kind="injury", start_date=date(2026, 10, 1), end_date=date(2026, 10, 10)))
    assert build(repo, goal, kind="injury", start_date=date(2026, 11, 3))


def test_light_week_valid(repo, goal):
    e = build(repo, goal, kind="light_week", start_date=date(2026, 11, 2), max_sessions=2, days=["jeudi", "mardi"])
    assert e.end_date == date(2026, 11, 8)
    assert e.max_sessions == 2
    assert e.days() == ["mardi", "jeudi"]  # ordre de la semaine


def test_light_week_days_optional_and_zero_sessions(repo, goal):
    e = build(repo, goal, kind="light_week", start_date=date(2026, 11, 2), max_sessions=0)
    assert e.days() is None and e.max_sessions == 0


def test_light_week_end_date_is_computed(repo, goal):
    e = build(repo, goal, kind="light_week", start_date=date(2026, 11, 2), end_date=date(2026, 12, 25), max_sessions=1)
    assert e.end_date == date(2026, 11, 8)


@pytest.mark.parametrize("start", [None, date(2026, 11, 3), date(2026, 10, 19), date(2027, 2, 1)])
def test_light_week_needs_a_plan_monday(repo, goal, start):
    with pytest.raises(EventError, match="Choisis une semaine du plan"):
        build(repo, goal, kind="light_week", start_date=start, max_sessions=2)


def test_light_week_first_and_last_weeks_ok(repo, goal):
    assert build(repo, goal, kind="light_week", start_date=date(2026, 10, 26), max_sessions=1)
    assert build(repo, goal, kind="light_week", start_date=date(2027, 1, 25), max_sessions=1)


def test_light_week_requires_max_sessions(repo, goal):
    with pytest.raises(EventError, match="Indique le nombre de séances maximum"):
        build(repo, goal, kind="light_week", start_date=date(2026, 11, 2))


def test_light_week_days_must_be_available(repo):
    goal = repo.add(make_goal(available_days_json='["mardi", "jeudi", "samedi"]'))
    with pytest.raises(EventError, match="Les jours de la semaine allégée doivent faire partie de tes jours possibles"):
        build(repo, goal, kind="light_week", start_date=date(2026, 11, 2), max_sessions=2, days=["mardi", "lundi"])
    assert build(repo, goal, kind="light_week", start_date=date(2026, 11, 2), max_sessions=2, days=["samedi", "mardi"])


def test_fatigue_imposes_today(repo, goal):
    e = build(repo, goal, kind="fatigue", start_date=date(2026, 11, 20), end_date=date(2026, 11, 25))
    assert e.start_date == e.end_date == TODAY


def test_fatigue_with_session_of_the_goal(repo, goal):
    s = repo.add(make_db_session(goal.id))
    assert build(repo, goal, kind="fatigue", session_id=s.id).session_id == s.id


def test_fatigue_session_not_found_or_other_goal(repo, goal):
    other = repo.add(make_db_session(goal.id + 1))
    for sid in (9999, other.id):
        with pytest.raises(EventError, match="Séance introuvable"):
            build(repo, goal, kind="fatigue", session_id=sid)


def test_fields_foreign_to_the_kind_are_dropped(repo, goal):
    e = build(
        repo,
        goal,
        kind="unavailable",
        start_date=date(2026, 11, 5),
        end_date=date(2026, 11, 6),
        max_sessions=1,
        days=["lundi"],
        session_id=3,
    )
    assert (e.max_sessions, e.days_json, e.session_id) == (None, None, None)


def test_input_validation():
    with pytest.raises(ValidationError):
        EventInput(kind="light_week", max_sessions=-1)
    with pytest.raises(ValidationError):
        EventInput(kind="nope")
    with pytest.raises(ValidationError):
        EventInput(kind="fatigue", days=["funday"])
