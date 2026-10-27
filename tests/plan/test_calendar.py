from datetime import date

from coach.plan.calendar import n_weeks, plan_start, week_monday, week_of
from tests.plan.factories import make_goal


def test_plan_start_is_monday():
    assert plan_start(date(2026, 10, 28)) == date(2026, 10, 26)
    assert plan_start(date(2026, 10, 26)) == date(2026, 10, 26)
    assert plan_start(date(2026, 11, 1)) == date(2026, 10, 26)


def test_n_weeks_race_on_sunday():
    assert n_weeks(date(2026, 10, 26), date(2027, 1, 31)) == 14


def test_n_weeks_race_on_monday_adds_a_week():
    assert n_weeks(date(2026, 10, 26), date(2027, 2, 1)) == 15


def test_week_monday_and_week_of():
    g = make_goal()
    assert week_monday(g, 1) == date(2026, 10, 26)
    assert week_monday(g, 3) == date(2026, 11, 9)
    assert week_of(g, date(2026, 11, 12)) == 3


def test_week_of_outside_plan_is_not_clamped():
    g = make_goal()
    assert week_of(g, date(2026, 10, 25)) == 0
    assert week_of(g, date(2027, 2, 1)) == 15
