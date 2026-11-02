import json
from datetime import date

from coach.llm.schemas import AdjustmentResponse, Change
from coach.plan.constraints import (
    Planned,
    PlanConstraints,
    constraint_errors,
    planned_after_adjustment,
    planned_from_plan,
)
from coach.plan.models import ALL_DAYS
from tests.llm.factories import make_plan, make_session
from tests.plan.factories import make_db_session, make_goal

TODAY = date(2026, 11, 2)


def _constraints(available=ALL_DAYS, long_run_day=None):
    return PlanConstraints(available_days=tuple(available), long_run_day=long_run_day, today=TODAY)


def test_session_on_unavailable_day_is_rejected():
    c = _constraints(("mardi", "jeudi", "dimanche"))
    p = [Planned("séance 1", make_session(suggested_day="lundi"), date(2026, 11, 2), exported=False)]
    assert constraint_errors(p, c) == ["séance 1 : lundi n'est pas un jour possible"]


def test_session_on_available_day_is_accepted():
    c = _constraints(("mardi",))
    p = [Planned("séance 1", make_session(suggested_day="mardi"), date(2026, 11, 3), exported=False)]
    assert constraint_errors(p, c) == []


def test_exported_session_ignores_available_days():
    c = _constraints(("mardi",))
    p = [Planned("séance 1", make_session(suggested_day="lundi"), date(2026, 11, 2), exported=True)]
    assert constraint_errors(p, c) == []


def test_long_run_must_be_on_long_run_day():
    c = _constraints(long_run_day="dimanche")
    p = [
        Planned(
            "séance 1",
            make_session(type="sortie_longue", suggested_day="samedi"),
            date(2026, 11, 7),
            exported=False,
        )
    ]
    assert constraint_errors(p, c) == ["séance 1 : la sortie longue doit tomber le dimanche"]


def test_long_run_on_long_run_day_and_no_long_run_day_are_accepted():
    sl = make_session(type="sortie_longue", suggested_day="dimanche")
    p = [Planned("séance 1", sl, date(2026, 11, 8), exported=False)]
    assert constraint_errors(p, _constraints(long_run_day="dimanche")) == []
    sl_sat = make_session(type="sortie_longue", suggested_day="samedi")
    p = [Planned("séance 1", sl_sat, date(2026, 11, 7), exported=False)]
    assert constraint_errors(p, _constraints(long_run_day=None)) == []


def test_unchanged_todo_on_removed_day_is_rejected():
    goal = make_goal(available_days_json=json.dumps(["mardi", "jeudi", "dimanche"]))
    s = make_db_session(1, suggested_day="lundi")
    s.id = 7
    planned = planned_after_adjustment(goal, [s], AdjustmentResponse(analysis="", changes=[]))
    assert constraint_errors(planned, PlanConstraints.of(goal, TODAY)) == [
        "séance 7 : lundi n'est pas un jour possible"
    ]


def test_planned_from_plan_labels_and_dates():
    goal = make_goal()
    plan = make_plan(2, [1, 2])
    planned = planned_from_plan(goal, plan)
    assert [p.label for p in planned] == ["semaine 1, séance 1", "semaine 2, séance 1", "semaine 2, séance 2"]
    assert planned[0].date == date(2026, 10, 27)  # mardi de la semaine 1
    assert planned[1].date == date(2026, 11, 3)
    assert not any(p.exported for p in planned)


def test_planned_after_adjustment_applies_remove_modify_add():
    goal = make_goal()
    kept, removed, modified, exported = (
        make_db_session(1, order=o, suggested_day="mardi") for o in (1, 2, 3, 4)
    )
    for i, s in enumerate((kept, removed, modified, exported), start=10):
        s.id = i
    exported.status = "exported"
    exported.scheduled_date = date(2026, 10, 29)
    exported.week_index = 1

    adj = AdjustmentResponse(
        analysis="",
        changes=[
            Change(op="remove", session_id=11, reason="r"),
            Change(op="modify", session_id=12, session=make_session(week_index=2, suggested_day="jeudi"), reason="r"),
            Change(op="modify", session_id=13, session=make_session(suggested_day="vendredi"), reason="r"),
            Change(op="add", session=make_session(week_index=2, suggested_day="samedi", order=5), reason="r"),
        ],
    )
    planned = planned_after_adjustment(goal, [kept, removed, modified, exported], adj)

    assert [p.label for p in planned] == ["séance 10", "séance 12", "séance 13", "ajout 4"]
    by_label = {p.label: p for p in planned}
    assert by_label["séance 10"].date == date(2026, 10, 27) and not by_label["séance 10"].exported
    assert by_label["séance 12"].date == date(2026, 11, 5) and not by_label["séance 12"].exported
    # exportée modifiée : garde sa date et son statut, mais prend la nouvelle spec
    assert by_label["séance 13"].date == date(2026, 10, 29)
    assert by_label["séance 13"].exported
    assert by_label["séance 13"].spec.suggested_day == "vendredi"
    assert by_label["ajout 4"].date == date(2026, 11, 7) and not by_label["ajout 4"].exported


def test_constraints_of_goal():
    goal = make_goal(available_days_json=json.dumps(["mardi", "dimanche"]), long_run_day="dimanche")
    c = PlanConstraints.of(goal, TODAY)
    assert c.available_days == ("mardi", "dimanche")
    assert c.long_run_day == "dimanche"
    assert c.today == TODAY
    assert c.include_bike is False
    assert c.events == ()


def test_exported_long_run_ignores_long_run_day():
    c = _constraints(long_run_day="dimanche")
    sl = make_session(type="sortie_longue", suggested_day="samedi")
    p = [Planned("séance 1", sl, date(2026, 11, 7), exported=True)]
    assert constraint_errors(p, c) == []
