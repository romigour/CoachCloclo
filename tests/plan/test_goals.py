"""Tests des règles pures des objectifs."""

from datetime import date

import pytest

from coach.plan.goals import classify_change, cycle_end, gap_conflict, goal_label
from tests.plan.factories import make_goal


def test_goal_label():
    assert goal_label(make_goal(type="trail", distance_km=20)) == "Trail de 20 km"
    assert goal_label(make_goal(type="route", distance_km=21.1)) == "Course sur route de 21,1 km"


def test_gap_conflict_message():
    semi = make_goal(id=1, type="route", distance_km=21.1, race_date=date(2027, 3, 22), priority="secondaire")
    trail = make_goal(id=2, type="trail", distance_km=20, race_date=date(2027, 3, 28), priority="secondaire")
    assert gap_conflict(trail, [semi]) == (
        "Course sur route de 21,1 km du 22/03/2027 (Secondaire) est à 6 jours : "
        "passe l'un des deux en Plaisir ou déplace-le"
    )


def test_gap_ignores_plaisir_and_self_and_archived():
    goal = make_goal(id=1, race_date=date(2027, 3, 28), priority="secondaire")
    close = date(2027, 3, 30)
    assert gap_conflict(goal, [make_goal(id=2, race_date=close, priority="plaisir")]) is None
    assert gap_conflict(goal, [make_goal(id=1, race_date=close, priority="principal")]) is None
    assert gap_conflict(goal, [make_goal(id=2, race_date=close, status="archived")]) is None
    plaisir = make_goal(id=3, race_date=date(2027, 3, 28), priority="plaisir")
    assert gap_conflict(plaisir, [make_goal(id=2, race_date=close, priority="principal")]) is None


def test_gap_exactly_14_days_ok():
    goal = make_goal(id=1, race_date=date(2027, 3, 28))
    ok = make_goal(id=2, race_date=date(2027, 4, 11))
    assert gap_conflict(goal, [ok]) is None
    too_close = make_goal(id=2, race_date=date(2027, 4, 10))
    assert gap_conflict(goal, [too_close]) is not None


def test_cycle_end_first_principal():
    goals = [
        make_goal(race_date=date(2027, 10, 10), priority="principal"),
        make_goal(race_date=date(2027, 3, 28), priority="secondaire"),
        make_goal(race_date=date(2027, 5, 20), priority="principal"),
    ]
    assert cycle_end(goals) == date(2027, 5, 20)


def test_cycle_end_without_principal_is_last():
    goals = [
        make_goal(race_date=date(2027, 8, 1), priority="plaisir"),
        make_goal(race_date=date(2027, 3, 28), priority="secondaire"),
    ]
    assert cycle_end(goals) == date(2027, 8, 1)


def test_cycle_end_extends_over_consecutive_days():
    goals = [
        make_goal(race_date=date(2027, 5, 20), priority="principal"),
        make_goal(race_date=date(2027, 5, 21), priority="plaisir"),
        make_goal(race_date=date(2027, 5, 23), priority="plaisir"),
    ]
    assert cycle_end(goals) == date(2027, 5, 21)


def test_cycle_end_empty_is_none():
    assert cycle_end([]) is None


OLD, NEW = date(2027, 5, 20), date(2027, 6, 1)


@pytest.mark.parametrize(
    ("accepted", "new_end", "touched", "expected"),
    [
        (True, None, False, "close"),
        (False, NEW, False, "draft"),
        (True, NEW, False, "regenerate"),
        (True, date(2027, 5, 1), False, "shrink"),
        (False, OLD, True, "draft"),
        (True, OLD, True, "adjust"),
        (True, OLD, False, "horizon"),
    ],
)
def test_classify_change(accepted, new_end, touched, expected):
    assert (
        classify_change(plan_accepted=accepted, old_end=OLD, new_end=new_end, touched_in_cycle=touched)
        == expected
    )
