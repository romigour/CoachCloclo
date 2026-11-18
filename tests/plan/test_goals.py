"""Tests des règles pures des objectifs."""

from datetime import date

import pytest

from coach.plan.goals import (
    block_label,
    classify_change,
    cycle_end,
    goal_label,
    proximity,
    proximity_label,
    proximity_notice,
    race_blocks,
)
from tests.plan.factories import make_goal


def test_goal_label():
    assert goal_label(make_goal(type="trail", distance_km=20)) == "Trail de 20 km"
    assert goal_label(make_goal(type="route", distance_km=21.1)) == "Course sur route de 21,1 km"


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


def test_cycle_end_extends_over_block():
    goals = [
        make_goal(race_date=date(2027, 5, 20), priority="principal"),
        make_goal(race_date=date(2027, 5, 21), priority="plaisir"),
        make_goal(race_date=date(2027, 5, 23), priority="plaisir"),
        make_goal(race_date=date(2027, 5, 26), priority="plaisir"),
    ]
    assert cycle_end(goals) == date(2027, 5, 23)


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


# --- courses rapprochées ------------------------------------------------------------------------

def g(id, d, prio="secondaire", km=20, dplus=450, status="active"):
    return make_goal(id=id, race_date=d, priority=prio, distance_km=km, d_plus_m=dplus, status=status)


def test_blocks_up_to_two_days():
    a, b, c = g(1, date(2027, 3, 27)), g(2, date(2027, 3, 29)), g(3, date(2027, 4, 1))
    blocks = race_blocks([c, a, b])
    assert [[x.id for x in bl.goals] for bl in blocks] == [[1, 2], [3]]


def test_block_includes_plaisir_and_takes_highest_priority():
    a, b = g(1, date(2027, 3, 27), "plaisir"), g(2, date(2027, 3, 28), "secondaire", km=30, dplus=600)
    (bl,) = race_blocks([a, b])
    assert bl.priority == "secondaire" and bl.distance_km == 50 and bl.d_plus_m == 1050
    assert block_label(bl) == "Trail de 20 km (27/03) + Trail de 30 km (28/03)"


def test_user_case_semi_plaisir_outside_group():
    semi = g(1, date(2027, 3, 21), "plaisir", km=21.1, dplus=0)
    sat, sun = g(2, date(2027, 3, 27)), g(3, date(2027, 3, 28), km=30, dplus=600)
    ultra = g(4, date(2027, 5, 22), "principal", km=80, dplus=4000)
    p = proximity([semi, sat, sun, ultra])
    assert p[1].role is None and p[2].role is None and p[4].role is None
    assert p[2].block is p[3].block


def test_tie_tapers_latest_and_earlier_is_integrated():
    a, b = g(1, date(2027, 3, 13)), g(2, date(2027, 3, 20))
    p = proximity([a, b])
    assert p[1].role == "integre" and p[2].role == "affute"
    assert p[1].tapered is p[2].block


def test_higher_priority_first_makes_later_a_rebound():
    a, b = g(1, date(2027, 3, 13), "principal"), g(2, date(2027, 3, 20), "secondaire")
    p = proximity([a, b])
    assert p[1].role == "affute" and p[2].role == "rebond"


def test_group_is_transitive():
    a, b, c = g(1, date(2027, 3, 1)), g(2, date(2027, 3, 12)), g(3, date(2027, 3, 23))
    p = proximity([a, b, c])
    assert [p[i].role for i in (1, 2, 3)] == ["integre", "integre", "affute"]


def test_thirteen_days_grouped_fourteen_not():
    assert proximity([g(1, date(2027, 3, 1)), g(2, date(2027, 3, 14))])[1].role == "integre"
    assert proximity([g(1, date(2027, 3, 1)), g(2, date(2027, 3, 15))])[1].role is None


def test_archived_ignored_recent_done_counted():
    done = g(1, date(2027, 3, 27), status="done")
    arch = g(2, date(2027, 3, 26), status="archived")
    sun = g(3, date(2027, 3, 28))
    p = proximity([done, arch, sun])
    assert 2 not in p and [x.id for x in p[3].block.goals] == [1, 3]


def test_unsaved_goal_keyed_zero():
    new = make_goal(id=None, race_date=date(2027, 3, 28), priority="secondaire")
    p = proximity([g(1, date(2027, 3, 27)), new])
    assert p[0].block is p[1].block


def test_labels_and_notice():
    sat, sun = g(2, date(2027, 3, 27)), g(3, date(2027, 3, 28), km=30, dplus=600)
    p = proximity([sat, sun])
    assert proximity_label(sat, p) == "Bloc avec Trail de 30 km (28/03)"
    assert proximity_notice(sun, p) == (
        "Trail de 20 km (27/03) + Trail de 30 km (28/03) seront préparés comme un seul bloc."
    )
    a, b = g(1, date(2027, 3, 13)), g(4, date(2027, 3, 20))
    p = proximity([a, b])
    assert proximity_label(a, p) == "Intégré à l'affûtage de Trail de 20 km (20/03)"
    assert proximity_notice(a, p) == (
        "Trail de 20 km (13/03) et Trail de 20 km (20/03) sont à moins de 14 jours : "
        "Trail de 20 km (20/03) sera affûté ; Trail de 20 km (13/03) sera intégré à son affûtage."
    )
    alone = g(5, date(2027, 6, 1))
    assert proximity_label(alone, proximity([alone])) is None
    assert proximity_notice(alone, proximity([alone])) is None


def test_cycle_end_extends_over_two_day_block():
    p, s = g(1, date(2027, 3, 27), "principal"), g(2, date(2027, 3, 29), "plaisir")
    assert cycle_end([p, s]) == date(2027, 3, 29)


def test_cycle_end_reaches_tapered_block_of_principal_group():
    a, b = g(1, date(2027, 3, 10), "principal"), g(2, date(2027, 3, 18), "principal")
    assert cycle_end([a, b]) == date(2027, 3, 18)


def test_cycle_end_stops_before_rebound():
    a, b = g(1, date(2027, 3, 10), "principal"), g(2, date(2027, 3, 18), "secondaire")
    assert cycle_end([a, b]) == date(2027, 3, 10)


def test_cycle_end_without_principal_is_last_block_end():
    a, b = g(1, date(2027, 3, 27)), g(2, date(2027, 3, 28))
    assert cycle_end([a, b]) == date(2027, 3, 28)
