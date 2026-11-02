import json
from datetime import date, timedelta

from coach.llm.schemas import AdjustmentResponse, Change
from coach.plan.constraints import (
    blocked_periods,
    Planned,
    PlanConstraints,
    constraint_errors,
    planned_after_adjustment,
    planned_from_plan,
)
from coach.plan.models import ALL_DAYS, Event
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


# --- périodes bloquées, arrêt ouvert, semaine allégée ---


def _ev(kind, start, end=None, **kw):
    return Event(goal_id=1, kind=kind, start_date=start, end_date=end, **kw)


def _ec(*events, today=TODAY, available=ALL_DAYS, long_run_day=None):
    return PlanConstraints(
        available_days=tuple(available),
        long_run_day=long_run_day,
        today=today,
        events=tuple(events),
        plan_start=date(2026, 10, 26),
    )


def _p(label, day, d, *, week=1, exported=False, **kw):
    return Planned(label, make_session(suggested_day=day, week_index=week, **kw), d, exported)


def _light(max_sessions, start=date(2026, 11, 2), days=None):
    return _ev(
        "light_week",
        start,
        start + timedelta(days=6),
        max_sessions=max_sessions,
        days_json=None if days is None else json.dumps(days),
    )


def test_session_during_unavailability_is_rejected():
    c = _ec(_ev("unavailable", date(2026, 11, 5), date(2026, 11, 12)))
    p = [_p("séance 1", "jeudi", date(2026, 11, 5), week=2), _p("séance 2", "vendredi", date(2026, 11, 13), week=2)]
    assert constraint_errors(p, c) == ["séance 1 : tombe pendant indisponibilité du 05/11 au 12/11"]


def test_exported_session_during_unavailability_must_be_removed():
    c = _ec(_ev("unavailable", date(2026, 11, 5), date(2026, 11, 12)))
    p = [_p("séance 1", "lundi", date(2026, 11, 9), week=2, exported=True)]
    assert constraint_errors(p, c) == [
        "séance 1 : séance exportée pendant indisponibilité du 05/11 au 12/11, à retirer (op remove)"
    ]


def test_closed_injury_label():
    c = _ec(_ev("injury", date(2026, 11, 3), date(2026, 11, 6)))
    p = [_p("séance 1", "mercredi", date(2026, 11, 4), week=2)]
    assert constraint_errors(p, c) == ["séance 1 : tombe pendant arrêt du 03/11 au 06/11"]


def test_open_injury_blocks_until_end_of_current_week():
    c = _ec(_ev("injury", date(2026, 11, 4)), today=date(2026, 11, 5))
    assert blocked_periods(c) == [(date(2026, 11, 4), date(2026, 11, 8), "arrêt depuis le 04/11")]
    p = [_p("dimanche", "dimanche", date(2026, 11, 8), week=2), _p("lundi", "lundi", date(2026, 11, 9), week=3)]
    assert constraint_errors(p, c) == ["dimanche : tombe pendant arrêt depuis le 04/11"]


def test_open_injury_declared_on_sunday_blocks_only_that_day():
    c = _ec(_ev("injury", date(2026, 11, 8)), today=date(2026, 11, 8))
    assert blocked_periods(c) == [(date(2026, 11, 8), date(2026, 11, 8), "arrêt depuis le 08/11")]
    p = [_p("lundi", "lundi", date(2026, 11, 9), week=3)]
    assert constraint_errors(p, c) == []


def test_open_injury_starting_after_current_week_blocks_its_first_day():
    c = _ec(_ev("injury", date(2026, 11, 12)), today=TODAY)
    assert blocked_periods(c) == [(date(2026, 11, 12), date(2026, 11, 12), "arrêt depuis le 12/11")]


def test_light_week_limits_sessions_with_fixed_counts():
    c = _ec(_light(1))
    p = [_p("séance 1", "jeudi", date(2026, 11, 5), week=2)]
    assert constraint_errors(p, c, fixed_counts={2: 1}) == [
        "semaine 2 : 2 séances pour 1 au plus (semaine allégée)"
    ]
    assert constraint_errors(p, c, fixed_counts={}) == []
    assert constraint_errors(p, c) == []


def test_light_week_only_counts_its_own_week():
    c = _ec(_light(1))
    p = [_p("a", "jeudi", date(2026, 11, 5), week=2), _p("b", "mardi", date(2026, 11, 10), week=3, order=2)]
    assert constraint_errors(p, c) == []


def test_light_week_with_no_planned_session_has_nothing_to_fix():
    c = _ec(_light(0))
    assert constraint_errors([], c, fixed_counts={2: 1}) == []
    p = [_p("a", "jeudi", date(2026, 11, 5), week=2)]
    assert constraint_errors(p, c) == ["semaine 2 : 1 séances pour 0 au plus (semaine allégée)"]


def test_several_light_weeks_on_same_week_all_apply():
    c = _ec(_light(3), _light(1))
    p = [_p("a", "jeudi", date(2026, 11, 5), week=2), _p("b", "vendredi", date(2026, 11, 6), week=2, order=2)]
    assert constraint_errors(p, c) == ["semaine 2 : 2 séances pour 1 au plus (semaine allégée)"]
    c = _ec(_light(2, days=["jeudi", "vendredi"]), _light(2, days=["jeudi"]))
    assert constraint_errors(p, c) == ["b : vendredi n'est pas un jour possible"]


def test_light_week_days_override_available_days():
    c = _ec(_light(3, days=["jeudi"]), available=("mardi", "jeudi"))
    p = [
        _p("a", "mardi", date(2026, 11, 3), week=2),  # jour possible de l'objectif, mais pas de la semaine allégée
        _p("b", "jeudi", date(2026, 11, 5), week=2, order=2),
        _p("c", "mardi", date(2026, 11, 10), week=3),  # autre semaine : jours de l'objectif
    ]
    assert constraint_errors(p, c) == ["a : mardi n'est pas un jour possible"]


def test_light_week_days_ignored_for_exported_session():
    c = _ec(_light(3, days=["jeudi"]))
    p = [_p("a", "mardi", date(2026, 11, 3), week=2, exported=True)]
    assert constraint_errors(p, c) == []


def test_long_run_free_when_long_run_day_blocked():
    c = _ec(_ev("unavailable", date(2026, 11, 8), date(2026, 11, 8)), long_run_day="dimanche")
    p = [_p("a", "samedi", date(2026, 11, 7), week=2, type="sortie_longue")]
    assert constraint_errors(p, c) == []
    other_week = [_p("b", "samedi", date(2026, 11, 14), week=3, type="sortie_longue")]
    assert constraint_errors(other_week, c) == ["b : la sortie longue doit tomber le dimanche"]


def test_long_run_free_when_light_week_excludes_long_run_day():
    c = _ec(_light(3, days=["mardi", "samedi"]), long_run_day="dimanche")
    p = [_p("a", "samedi", date(2026, 11, 7), week=2, type="sortie_longue")]
    assert constraint_errors(p, c) == []


def test_long_run_still_required_when_light_week_keeps_long_run_day():
    c = _ec(_light(3, days=["samedi", "dimanche"]), long_run_day="dimanche")
    p = [_p("a", "samedi", date(2026, 11, 7), week=2, type="sortie_longue")]
    assert constraint_errors(p, c) == ["a : la sortie longue doit tomber le dimanche"]


def test_fully_blocked_week_may_be_empty():
    c = _ec(_ev("unavailable", date(2026, 11, 2), date(2026, 11, 8)))
    assert constraint_errors([], c) == []


def test_period_spanning_weeks_and_outside_plan():
    c = _ec(
        _ev("unavailable", date(2026, 12, 28), date(2027, 1, 10)),  # chevauche 3 semaines
        _ev("unavailable", date(2026, 10, 12), date(2026, 10, 28)),  # commence avant plan_start
    )
    p = [
        _p("a", "lundi", date(2026, 12, 28), week=10),
        _p("b", "mardi", date(2027, 1, 5), week=11),
        _p("c", "dimanche", date(2027, 1, 10), week=11),
        _p("d", "lundi", date(2027, 1, 11), week=12),
        _p("e", "mardi", date(2026, 10, 27), week=1),
        _p("f", "jeudi", date(2026, 10, 29), week=1),
    ]
    assert constraint_errors(p, c) == [
        "a : tombe pendant indisponibilité du 28/12 au 10/01",
        "b : tombe pendant indisponibilité du 28/12 au 10/01",
        "c : tombe pendant indisponibilité du 28/12 au 10/01",
        "e : tombe pendant indisponibilité du 12/10 au 28/10",
    ]


def test_fatigue_does_not_block():
    c = _ec(_ev("fatigue", TODAY, TODAY, note="jambes lourdes"))
    assert blocked_periods(c) == []
    p = [_p("a", "mardi", date(2026, 11, 3), week=2)]
    assert constraint_errors(p, c) == []


def test_constraints_of_goal_carries_plan_start():
    assert PlanConstraints.of(make_goal(), TODAY).plan_start == date(2026, 10, 26)
