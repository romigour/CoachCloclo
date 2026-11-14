from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlmodel import select

from coach.analysis.gpx import GpxError
from coach.garmin.port import FakeGarminClient, GarminUnavailable, Metrics
from coach.llm.prompts import NEW_GOAL_ID
from coach.llm.provider import FakeLLMProvider, LLMInvalidResponse
from coach.llm.schemas import AdjustmentResponse, Change, GoalEstimate
from coach.plan.models import Cycle, Goal, Proposal, Session
from coach.services.goals import (
    ChangeResult,
    GoalError,
    GoalInput,
    GoalUpdate,
    add_goal,
    parse_target_time,
    remove_goal,
    update_goal,
)
from coach.services.plans import accept_plan
from coach.services.race_strategy import export_race
from tests.plan.factories import make_db_session
from tests.services.test_sync import adjustment_json

FIXTURES = Path(__file__).parent.parent / "fixtures" / "gpx"
METRICS = Metrics(hr_max=190, hr_rest=50, threshold_pace_s_km=300)
NOTE_END = "Adapte les séances à venir en conséquence."


@pytest.fixture
def fake_garmin():
    return FakeGarminClient(metrics=METRICS)


@pytest.fixture
def monday_garmin():
    return FakeGarminClient(metrics=METRICS, today=date(2026, 11, 2))


def goal_input(**overrides) -> GoalInput:
    gpx = overrides.pop("gpx", None)
    data = {
        "type": "trail",
        "distance_km": 42,
        "d_plus_m": 2000,
        "race_date": date(2027, 2, 7),  # 14 semaines depuis le 2026-11-02
        "sessions_per_week": 3,
        "gpx": gpx.read_bytes() if gpx else None,
    }
    data.update(overrides)
    return GoalInput(**data)


def other_input(**overrides) -> GoalInput:
    """Objectif ajouté à un cycle existant : course sur route de 10 km, sans réglages du plan."""
    data = {"type": "route", "distance_km": 10, "d_plus_m": 0, "race_date": date(2026, 12, 20),
            "priority": "secondaire"}
    data.update(overrides)
    return GoalInput(**data)


def first_goal(repo, garmin, **overrides) -> Goal:
    """Premier objectif (crée le cycle) ; aucun appel à Claude."""
    return add_goal(repo, garmin, FakeLLMProvider([]), goal_input(**overrides))[0]


def _cid(repo) -> int:
    return repo.active_cycle().id


def _goals(repo) -> list[Goal]:
    return repo.upcoming_goals()


def _get(repo, model, id_):
    with repo.transaction() as db:
        return db.get(model, id_)


def accepted_goal(repo, garmin, **overrides) -> Goal:
    """Objectif validé (14 semaines, 3 séances par semaine, 2 la semaine de la course) ; séance 1 des
    semaines 13-14 exportée (planifiée sur le faux Garmin). Sans temps visé, l'objectif porte
    l'estimation de Claude (5 h 40), comme après une génération."""
    goal = first_goal(repo, garmin, **overrides)
    if goal.target_time_s is None:
        with repo.transaction() as db:
            g = db.get(Goal, goal.id)
            g.target_time_s = 20400
            db.add(g)
    for w in range(1, 15):
        for o in (1, 2) if w == 14 else (1, 2, 3):
            s = make_db_session(_cid(repo), week_index=w, order=o)
            if w >= 13 and o == 1:
                s.status = "exported"
                s.scheduled_date = date(2026, 11, 3) + timedelta(weeks=w - 1)  # mardi
                s.garmin_workout_id, s.garmin_schedule_id = 100 + w, 200 + w
                garmin.workouts[100 + w] = {}
                garmin.schedules[200 + w] = (100 + w, s.scheduled_date)
                garmin.calendar.setdefault(s.scheduled_date, []).append(200 + w)
            repo.add(s)
    with repo.transaction() as db:  # comme après une génération
        c = db.get(Cycle, _cid(repo))
        c.needs_generation = False
        db.add(c)
    accept_plan(repo)
    return _goals(repo)[0]


def race_adjustment_json(repo, week: int, goal_id: int | None = NEW_GOAL_ID, seconds: int = 3000) -> str:
    """Ajustement d'une course placée en semaine `week` : retire la séance 3 de cette semaine (la course y
    prend une place) et estime l'objectif `goal_id` (aucune estimation si None)."""
    s = next(x for x in repo.sessions(_cid(repo), week_index=week) if x.order == 3)
    return AdjustmentResponse(
        analysis="Course intégrée.",
        changes=[Change(op="remove", session_id=s.id, reason="la course compte comme une séance")],
        estimated_times=[] if goal_id is None else [GoalEstimate(goal_id=goal_id, seconds=seconds)],
    ).model_dump_json()


def _proposals(repo) -> list[tuple[int, str]]:
    with repo.transaction() as db:
        return sorted((p.id, p.status) for p in db.exec(select(Proposal)).all())


# --- premier objectif --------------------------------------------------------------------


def test_first_goal_creates_cycle_and_needs_generation(repo, fake_garmin):
    llm = FakeLLMProvider([])
    goal, result = add_goal(
        repo, fake_garmin, llm,
        goal_input(available_days=["mardi", "jeudi", "samedi"], long_run_day="samedi", include_bike=True,
                   priority="secondaire"),
    )
    assert result == ChangeResult(proposal_id=None, needs_generation=True)
    cycle = repo.active_cycle()
    assert (cycle.plan_start, cycle.end_date, cycle.sessions_per_week) == (date(2026, 11, 2), date(2027, 2, 7), 3)
    assert cycle.available_days() == ["mardi", "jeudi", "samedi"] and cycle.long_run_day == "samedi"
    assert cycle.include_bike is True and cycle.plan_accepted is False and cycle.needs_generation is True
    assert goal.priority == "secondaire" and [g.id for g in repo.goals_in(cycle)] == [goal.id]
    assert llm.calls == []


def test_first_goal_requires_sessions_per_week(repo, fake_garmin):
    with pytest.raises(GoalError, match="Indique le nombre de séances par semaine"):
        add_goal(repo, fake_garmin, FakeLLMProvider([]), goal_input(sessions_per_week=None))
    assert repo.active_cycle() is None and _goals(repo) == []


def test_race_too_close_rejected(repo, fake_garmin):
    with pytest.raises(GoalError, match="au moins 14 jours"):
        first_goal(repo, fake_garmin, race_date=fake_garmin.today() + timedelta(days=10))


def test_race_in_past_rejected(repo, fake_garmin):
    with pytest.raises(GoalError):
        first_goal(repo, fake_garmin, race_date=fake_garmin.today() - timedelta(days=3))
    assert _goals(repo) == []


def test_gpx_dplus_used_when_not_given(repo, coach_home, fake_garmin):
    g = first_goal(repo, fake_garmin, d_plus_m=0, gpx=FIXTURES / "climb.gpx")
    assert g.d_plus_m == pytest.approx(600, abs=30)
    assert g.gpx_summary_json
    assert repo.gpx(g.id) == (FIXTURES / "climb.gpx").read_bytes()


def test_given_dplus_kept_with_gpx(repo, coach_home, fake_garmin):
    assert first_goal(repo, fake_garmin, d_plus_m=1500, gpx=FIXTURES / "climb.gpx").d_plus_m == 1500


def test_plan_start_is_monday(repo, fake_garmin):
    first_goal(repo, fake_garmin)
    assert repo.active_cycle().plan_start == date(2026, 11, 2)


def test_gpx_error_creates_no_goal(repo, fake_garmin):
    with pytest.raises(GpxError):
        first_goal(repo, fake_garmin, gpx=FIXTURES / "broken.gpx")
    assert _goals(repo) == [] and repo.active_cycle() is None


def test_goal_gpx_stored_in_db(repo, coach_home, fake_garmin):
    g = first_goal(repo, fake_garmin, gpx=FIXTURES / "climb.gpx")
    assert repo.gpx(g.id) == (FIXTURES / "climb.gpx").read_bytes()
    assert not (coach_home / "gpx").exists()


def test_gpx_write_failure_saves_nothing(repo, coach_home, fake_garmin, monkeypatch):
    old = first_goal(repo, fake_garmin)
    cycle = repo.active_cycle()

    def boom(self, db, goal_id, data):
        raise OSError("base pleine")

    monkeypatch.setattr(type(repo), "save_gpx", boom)
    with pytest.raises(OSError):
        add_goal(
            repo, fake_garmin, FakeLLMProvider([]),
            other_input(race_date=date(2027, 4, 11), gpx=(FIXTURES / "climb.gpx").read_bytes()),
        )
    assert [g.id for g in _goals(repo)] == [old.id]
    assert repo.active_cycle().model_dump() == cycle.model_dump()


def test_parse_target_time():
    assert parse_target_time("3:45") == 13500 and parse_target_time("1:05:30") == 3930
    for bad in ("", "3h45", "3:75", "0:00"):
        with pytest.raises(GoalError):
            parse_target_time(bad)


def test_create_goal_with_user_time(repo, fake_garmin):
    g = first_goal(repo, fake_garmin, target_time_s=18000)
    assert (g.target_time_s, g.target_source) == (18000, "user")


def test_create_goal_without_time_is_claude_mode(repo, fake_garmin):
    g = first_goal(repo, fake_garmin)
    assert (g.target_time_s, g.target_source) == (None, "claude")


def test_create_goal_rejects_implausible_time(repo, fake_garmin):
    with pytest.raises(GoalError, match="invraisemblable"):
        first_goal(repo, fake_garmin, target_time_s=3600)  # 42 km en 1 h
    assert _goals(repo) == []


def test_create_goal_rejects_fewer_days_than_sessions(repo, fake_garmin):
    with pytest.raises(GoalError, match="au moins 3 jours possibles"):
        first_goal(repo, fake_garmin, sessions_per_week=3, available_days=["mardi", "jeudi"])


def test_create_goal_rejects_long_run_day_not_available(repo, fake_garmin):
    with pytest.raises(GoalError, match="Le jour de la sortie longue doit faire partie des jours possibles"):
        first_goal(repo, fake_garmin, available_days=["mardi", "jeudi", "samedi"], long_run_day="dimanche")


def test_create_goal_stores_availability_in_week_order(repo, fake_garmin):
    first_goal(repo, fake_garmin, available_days=["samedi", "mardi", "jeudi", "mardi"], long_run_day="samedi")
    cycle = repo.active_cycle()
    assert cycle.available_days() == ["mardi", "jeudi", "samedi"] and cycle.long_run_day == "samedi"


# --- ajout dans un cycle actif ---------------------------------------------------------------


def test_add_secondary_in_accepted_cycle_asks_adjustment(repo, monday_garmin):
    principal = accepted_goal(repo, monday_garmin)
    llm = FakeLLMProvider([race_adjustment_json(repo, 7)])
    goal, result = add_goal(repo, monday_garmin, llm, other_input())
    assert result.proposal_id is not None and result.needs_generation is False
    assert _proposals(repo) == [(result.proposal_id, "pending")]
    cycle = repo.active_cycle()
    assert cycle.end_date == date(2027, 2, 7) and cycle.plan_accepted is True
    assert [g.id for g in repo.goals_in(cycle)] == [goal.id, principal.id]
    assert (goal.priority, goal.target_source) == ("secondaire", "claude")
    assert (
        "L'athlète a ajouté l'objectif Course sur route de 10 km du 20/12/2026 (Secondaire). " + NOTE_END
    ) in llm.calls[0]
    assert len(repo.sessions(_cid(repo))) == 41 and monday_garmin.calls == []


def test_add_goal_gap_conflict_saves_nothing(repo, monday_garmin):
    accepted_goal(repo, monday_garmin)
    llm = FakeLLMProvider([])
    with pytest.raises(GoalError) as e:
        add_goal(repo, monday_garmin, llm, other_input(race_date=date(2027, 1, 31)))
    assert str(e.value) == (
        "Trail de 42 km du 07/02/2027 (Principal) est à 7 jours : passe l'un des deux en Plaisir ou déplace-le"
    )
    assert len(_goals(repo)) == 1 and llm.calls == []
    # un Plaisir n'est jamais en conflit
    add_goal(repo, monday_garmin, FakeLLMProvider([race_adjustment_json(repo, 13)]),
             other_input(race_date=date(2027, 1, 31), priority="plaisir"))
    assert len(_goals(repo)) == 2


def test_add_goal_must_be_after_today(repo, monday_garmin):
    accepted_goal(repo, monday_garmin)
    with pytest.raises(GoalError, match="après aujourd'hui"):
        add_goal(repo, monday_garmin, FakeLLMProvider([]), other_input(race_date=date(2026, 11, 2)))
    # dans un cycle actif, la règle des 14 jours ne s'applique pas et les réglages sont facultatifs
    goal, _ = add_goal(
        repo, monday_garmin, FakeLLMProvider([race_adjustment_json(repo, 1)]),
        other_input(race_date=date(2026, 11, 8), priority="plaisir"),
    )
    assert goal.race_date == date(2026, 11, 8)


def test_add_goal_after_principal_is_horizon(repo, monday_garmin):
    accepted_goal(repo, monday_garmin)
    llm = FakeLLMProvider([])
    goal, result = add_goal(repo, monday_garmin, llm, other_input(race_date=date(2027, 4, 11), priority="principal"))
    assert result == ChangeResult(proposal_id=None, needs_generation=False)
    assert llm.calls == [] and _proposals(repo) == []
    cycle = repo.active_cycle()
    assert cycle.end_date == date(2027, 2, 7) and cycle.plan_accepted is True
    assert [g.id for g in repo.horizon_goals(cycle)] == [goal.id]


def test_add_closer_principal_shrinks_cycle(repo, monday_garmin):
    old = accepted_goal(repo, monday_garmin)
    monday_garmin.fail_on = {"delete_workout"}  # garde la trace des séances exportées à retirer
    llm = FakeLLMProvider([race_adjustment_json(repo, 11)])
    goal, result = add_goal(repo, monday_garmin, llm, other_input(race_date=date(2027, 1, 17), priority="principal"))
    assert result.proposal_id is not None and result.needs_generation is False
    cycle = repo.active_cycle()
    assert cycle.end_date == date(2027, 1, 17)  # 11 semaines
    assert [g.id for g in repo.goals_in(cycle)] == [goal.id]
    assert [g.id for g in repo.horizon_goals(cycle)] == [old.id]
    late = [s for s in repo.sessions(cycle.id) if s.week_index > 11]
    assert [(s.week_index, s.pending_removal) for s in late] == [(13, True), (14, True)]
    assert max(s.week_index for s in repo.sessions(cycle.id) if not s.pending_removal) == 11
    assert monday_garmin.schedules == {}
    assert "| semaine 11 |" in llm.calls[0] and "| semaine 12 |" not in llm.calls[0]


def test_add_far_goal_without_principal_regenerates(repo, monday_garmin):
    accepted_goal(repo, monday_garmin, priority="secondaire")
    before = [s.model_dump() for s in repo.sessions(_cid(repo))]
    llm = FakeLLMProvider([])
    goal, result = add_goal(repo, monday_garmin, llm, other_input(race_date=date(2027, 3, 7)))
    assert result == ChangeResult(proposal_id=None, needs_generation=True)
    cycle = repo.active_cycle()
    assert (cycle.end_date, cycle.plan_accepted, cycle.needs_generation) == (date(2027, 3, 7), False, True)
    assert [s.model_dump() for s in repo.sessions(cycle.id)] == before
    assert llm.calls == [] and goal.id in [g.id for g in repo.goals_in(cycle)]


def test_add_goal_in_draft_marks_needs_generation(repo, monday_garmin):
    first_goal(repo, monday_garmin)
    llm = FakeLLMProvider([])
    _, result = add_goal(repo, monday_garmin, llm, other_input())
    assert result == ChangeResult(proposal_id=None, needs_generation=True)
    cycle = repo.active_cycle()
    assert (cycle.end_date, cycle.plan_accepted, cycle.needs_generation) == (date(2027, 2, 7), False, True)
    assert llm.calls == []


def test_adjust_failure_saves_nothing(repo, monday_garmin):
    accepted_goal(repo, monday_garmin)
    old = repo.add(Proposal(analysis="avant", changes_json="[]"))
    before = [s.model_dump() for s in repo.sessions(_cid(repo))]
    for data in (other_input(), other_input(race_date=date(2027, 1, 17), priority="principal")):
        with pytest.raises(LLMInvalidResponse):
            add_goal(repo, monday_garmin, FakeLLMProvider(["{}", "{}"]), data)
    assert len(_goals(repo)) == 1
    assert repo.active_cycle().end_date == date(2027, 2, 7)
    assert [s.model_dump() for s in repo.sessions(_cid(repo))] == before
    assert _proposals(repo) == [(old.id, "pending")] and monday_garmin.calls == []


# --- modification ----------------------------------------------------------------------------


def test_update_goal_target_only(repo, monday_garmin):
    goal = accepted_goal(repo, monday_garmin, target_time_s=18000)
    llm = FakeLLMProvider([adjustment_json()])
    saved, result = update_goal(repo, monday_garmin, llm, goal.id, GoalUpdate(target_time="5:30"))
    g = _goals(repo)[0]
    assert (g.target_time_s, g.target_source, g.race_date) == (19800, "user", date(2027, 2, 7))
    assert (saved.target_time_s, saved.target_source) == (19800, "user")
    assert _proposals(repo) == [(result.proposal_id, "pending")] and result.needs_generation is False
    assert (
        "L'athlète a modifié l'objectif Trail de 42 km du 07/02/2027 (Principal) : "
        "temps visé 5 h 30 au lieu de 5 h 00. " + NOTE_END
    ) in llm.calls[0]
    assert len(repo.sessions(_cid(repo))) == 41 and monday_garmin.calls == []


def test_update_goal_target_without_previous(repo, monday_garmin):
    goal = accepted_goal(repo, monday_garmin)
    with repo.transaction() as db:  # mode Claude, aucun temps encore estimé
        db.get(Goal, goal.id).target_time_s = None
    llm = FakeLLMProvider([adjustment_json()])
    update_goal(repo, monday_garmin, llm, goal.id, GoalUpdate(target_time="5:30"))
    assert "temps visé 5 h 30, aucun auparavant" in llm.calls[0]
    g = _goals(repo)[0]
    assert (g.target_time_s, g.target_source) == (19800, "user")


def test_update_goal_earlier_date_removes_weeks(repo, monday_garmin):
    goal = accepted_goal(repo, monday_garmin)
    llm = FakeLLMProvider([race_adjustment_json(repo, 12, goal_id=None)])
    update_goal(repo, monday_garmin, llm, goal.id, GoalUpdate(race_date=date(2027, 1, 24)))
    assert _goals(repo)[0].race_date == date(2027, 1, 24)
    assert repo.active_cycle().end_date == date(2027, 1, 24)
    # todo des semaines 13-14 supprimées ; exportées retirées de la montre puis supprimées
    assert max(s.week_index for s in repo.sessions(_cid(repo))) == 12
    assert len(repo.sessions(_cid(repo))) == 36
    assert monday_garmin.calls == ["unschedule", "delete_workout"] * 2
    assert monday_garmin.workouts == {} and monday_garmin.schedules == {} and monday_garmin.calendar == {}
    assert "course déplacée du 07/02/2027 au 24/01/2027" in llm.calls[0]
    assert "| semaine 12 |" in llm.calls[0] and "| semaine 13 |" not in llm.calls[0]


def test_update_goal_date_in_current_week(repo, monday_garmin):
    goal = accepted_goal(repo, monday_garmin)
    update_goal(
        repo, monday_garmin, FakeLLMProvider([race_adjustment_json(repo, 1, goal_id=None)]), goal.id,
        GoalUpdate(race_date=date(2026, 11, 8)),
    )
    sessions = repo.sessions(_cid(repo))
    assert [s.week_index for s in sessions] == [1, 1, 1]
    assert monday_garmin.workouts == {} and monday_garmin.schedules == {}


def test_update_goal_removes_exported_after_race_day(repo, monday_garmin):
    goal = accepted_goal(repo, monday_garmin)
    # course le lundi 2027-01-25 (semaine 13) : la séance exportée du mardi 26 tombe après
    update_goal(
        repo, monday_garmin, FakeLLMProvider([adjustment_json()]), goal.id,
        GoalUpdate(race_date=date(2027, 1, 25)),
    )
    assert repo.sessions(_cid(repo), week_index=13) == []  # les todo (mardi) tombent aussi après la course
    assert repo.sessions(_cid(repo), week_index=14) == []
    assert monday_garmin.workouts == {} and monday_garmin.schedules == {}


def test_update_goal_mid_week_removes_todo_after_race_day(repo, monday_garmin):
    goal = accepted_goal(repo, monday_garmin)
    # course le samedi 2027-01-30 (semaine 13) : les todo planifiés dimanche sont retirés, les autres restent
    with repo.transaction() as db:
        for s in db.exec(select(Session).where(Session.cycle_id == _cid(repo), Session.week_index == 13)).all():
            s.suggested_day = "dimanche" if s.order == 3 else "jeudi"
            db.add(s)
    update_goal(
        repo, monday_garmin, FakeLLMProvider([adjustment_json()]), goal.id,
        GoalUpdate(race_date=date(2027, 1, 30)),
    )
    todo13 = [s.order for s in repo.sessions(_cid(repo), week_index=13) if s.status == "todo"]
    assert todo13 == [2]


def test_update_goal_garmin_failure_keeps_edit(repo, monday_garmin):
    goal = accepted_goal(repo, monday_garmin)
    monday_garmin.fail_on = {"delete_workout"}
    _, result = update_goal(
        repo, monday_garmin, FakeLLMProvider([race_adjustment_json(repo, 12, goal_id=None)]), goal.id,
        GoalUpdate(race_date=date(2027, 1, 24)),
    )
    assert _goals(repo)[0].race_date == date(2027, 1, 24)
    assert _proposals(repo) == [(result.proposal_id, "pending")]
    late = [s for s in repo.sessions(_cid(repo)) if s.week_index > 12]
    assert len(late) == 2
    for s in late:
        assert (s.status, s.pending_removal) == ("sync_error", True)
        assert s.sync_error.startswith("Synchronisation Garmin échouée")
        assert s.pending_old_schedule_id is None and s.pending_old_workout_id is not None
    assert monday_garmin.schedules == {} and set(monday_garmin.workouts) == {113, 114}


def test_update_goal_later_date_regenerates(repo, monday_garmin):
    goal = accepted_goal(repo, monday_garmin)
    llm = FakeLLMProvider([])
    saved, result = update_goal(repo, monday_garmin, llm, goal.id, GoalUpdate(race_date=date(2027, 2, 21)))
    assert result == ChangeResult(proposal_id=None, needs_generation=True)
    cycle = repo.active_cycle()
    assert (cycle.end_date, cycle.plan_accepted, cycle.needs_generation) == (date(2027, 2, 21), False, True)
    assert saved.race_date == date(2027, 2, 21)
    assert llm.calls == [] and len(repo.sessions(cycle.id)) == 41 and monday_garmin.calls == []


def test_update_goal_makes_pending_stale(repo, monday_garmin):
    goal = accepted_goal(repo, monday_garmin)
    old = repo.add(Proposal(analysis="avant", changes_json="[]"))
    _, result = update_goal(
        repo, monday_garmin, FakeLLMProvider([adjustment_json()]), goal.id, GoalUpdate(target_time="5:30")
    )
    assert _proposals(repo) == [(old.id, "stale"), (result.proposal_id, "pending")]


def test_update_goal_llm_failure_changes_nothing(repo, monday_garmin):
    goal = accepted_goal(repo, monday_garmin, target_time_s=18000)
    old = repo.add(Proposal(analysis="avant", changes_json="[]"))
    before = [s.model_dump() for s in repo.sessions(_cid(repo))]
    with pytest.raises(LLMInvalidResponse):
        update_goal(
            repo, monday_garmin, FakeLLMProvider(["{}", "{}"]), goal.id,
            GoalUpdate(race_date=date(2027, 1, 24), target_time="5:30"),
        )
    g = _goals(repo)[0]
    assert (g.race_date, g.target_time_s, g.target_source) == (date(2027, 2, 7), 18000, "user")
    assert repo.active_cycle().end_date == date(2027, 2, 7)
    assert [s.model_dump() for s in repo.sessions(_cid(repo))] == before
    assert _proposals(repo) == [(old.id, "pending")]


@pytest.mark.parametrize(
    ("update", "match"),
    [
        (GoalUpdate(race_date=date(2026, 11, 2)), "après aujourd'hui"),
        (GoalUpdate(race_date=date(2026, 10, 30)), "après aujourd'hui"),
        (GoalUpdate(target_time="abc"), "format attendu"),
        (GoalUpdate(target_time="1:00"), "invraisemblable"),
        (GoalUpdate(), "Aucune modification"),
        (GoalUpdate(race_date=date(2027, 2, 7), target_time="5:00"), "Aucune modification"),
        (GoalUpdate(target_time="5:00:00"), "Aucune modification"),
        (GoalUpdate(priority="principal"), "Aucune modification"),
    ],
)
def test_update_goal_rejections(repo, monday_garmin, update, match):
    goal = accepted_goal(repo, monday_garmin, target_time_s=18000)
    llm = FakeLLMProvider([])
    with pytest.raises(GoalError, match=match):
        update_goal(repo, monday_garmin, llm, goal.id, update)
    assert llm.calls == []


def test_update_goal_in_draft_and_unknown_goals(repo, monday_garmin):
    draft = first_goal(repo, monday_garmin)
    llm = FakeLLMProvider([])
    _, result = update_goal(repo, monday_garmin, llm, draft.id, GoalUpdate(target_time="5:30"))
    assert result == ChangeResult(proposal_id=None, needs_generation=True)
    assert repo.active_cycle().needs_generation is True
    remove_goal(repo, monday_garmin, llm, draft.id)
    for bad in (draft.id, 999):
        with pytest.raises(GoalError, match="introuvable ou archivé"):
            update_goal(repo, monday_garmin, llm, bad, GoalUpdate(target_time="5:30"))
    assert llm.calls == []


def test_update_goal_date_respects_gap(repo, monday_garmin):
    accepted_goal(repo, monday_garmin)
    later, _ = add_goal(repo, monday_garmin, FakeLLMProvider([]), other_input(race_date=date(2027, 4, 11)))
    llm = FakeLLMProvider([])
    with pytest.raises(GoalError, match="Trail de 42 km du 07/02/2027 \\(Principal\\) est à 7 jours"):
        update_goal(repo, monday_garmin, llm, later.id, GoalUpdate(race_date=date(2027, 2, 14)))
    assert _get(repo, Goal, later.id).race_date == date(2027, 4, 11) and llm.calls == []
    # même règle au changement de priorité : un Plaisir proche devient Principal
    fun, _ = add_goal(repo, monday_garmin, FakeLLMProvider([]),
                      other_input(race_date=date(2027, 4, 18), priority="plaisir"))
    with pytest.raises(GoalError, match="est à 7 jours"):
        update_goal(repo, monday_garmin, llm, fun.id, GoalUpdate(priority="principal"))


def test_update_priority_to_principal_moves_end(repo, monday_garmin):
    accepted_goal(repo, monday_garmin)
    second, _ = add_goal(
        repo, monday_garmin, FakeLLMProvider([race_adjustment_json(repo, 11)]), other_input(race_date=date(2027, 1, 17))
    )
    # proposition non acceptée : semaine 11 encore pleine, objectif encore sans temps
    llm = FakeLLMProvider([race_adjustment_json(repo, 11, goal_id=second.id)])
    saved, result = update_goal(repo, monday_garmin, llm, second.id, GoalUpdate(priority="principal"))
    assert saved.priority == "principal" and result.proposal_id is not None
    assert repo.active_cycle().end_date == date(2027, 1, 17)
    assert "priorité Principal au lieu de Secondaire" in llm.calls[0]
    assert max(s.week_index for s in repo.sessions(_cid(repo))) == 11


# --- retrait -------------------------------------------------------------------------------


def test_remove_last_goal_closes_cycle(repo, monday_garmin):
    goal = accepted_goal(repo, monday_garmin)
    cycle_id = _cid(repo)
    with repo.transaction() as db:
        done = db.exec(select(Session).where(Session.cycle_id == cycle_id, Session.week_index == 1)).first()
        done.status = "done"
        db.add(done)
    old = repo.add(Proposal(analysis="avant", changes_json="[]"))
    llm = FakeLLMProvider([])
    result = remove_goal(repo, monday_garmin, llm, goal.id)
    assert result == ChangeResult(proposal_id=None, needs_generation=False)
    assert repo.active_cycle() is None and _get(repo, Cycle, cycle_id).status == "done"
    assert _get(repo, Goal, goal.id).status == "archived"
    assert [s.id for s in repo.sessions(cycle_id)] == [done.id]  # todo supprimées, exportées retirées
    assert monday_garmin.workouts == {} and monday_garmin.schedules == {}
    assert _proposals(repo) == [(old.id, "stale")] and llm.calls == []


def test_remove_principal_with_later_goal_regenerates(repo, monday_garmin):
    goal = accepted_goal(repo, monday_garmin)
    later, _ = add_goal(repo, monday_garmin, FakeLLMProvider([]), other_input(race_date=date(2027, 4, 11)))
    result = remove_goal(repo, monday_garmin, FakeLLMProvider([]), goal.id)
    assert result == ChangeResult(proposal_id=None, needs_generation=True)
    cycle = repo.active_cycle()
    assert (cycle.end_date, cycle.plan_accepted, cycle.needs_generation) == (date(2027, 4, 11), False, True)
    assert [g.id for g in repo.goals_in(cycle)] == [later.id]


def test_remove_goal_in_cycle_asks_adjustment(repo, monday_garmin):
    accepted_goal(repo, monday_garmin)
    second, _ = add_goal(repo, monday_garmin, FakeLLMProvider([race_adjustment_json(repo, 7)]), other_input())
    llm = FakeLLMProvider([adjustment_json()])
    result = remove_goal(repo, monday_garmin, llm, second.id)
    assert result.proposal_id is not None and result.needs_generation is False
    assert (
        "L'athlète a retiré l'objectif Course sur route de 10 km du 20/12/2026 (Secondaire). " + NOTE_END
    ) in llm.calls[0]
    # l'objectif retiré n'est plus transmis à Claude comme objectif du cycle
    assert _get(repo, Goal, second.id).status == "archived"


def _exported_horizon_race(repo, garmin) -> Goal:
    accepted_goal(repo, garmin)
    later, _ = add_goal(
        repo, garmin, FakeLLMProvider([]), other_input(race_date=date(2027, 4, 11), target_time_s=2700)
    )
    export_race(repo, garmin, later.id)
    return later


def test_remove_goal_withdraws_race_workout(repo, coach_home, monday_garmin):
    later = _exported_horizon_race(repo, monday_garmin)
    workout_id = repo.race_strategy(later.id).garmin_workout_id
    assert workout_id in monday_garmin.workouts
    llm = FakeLLMProvider([])
    assert remove_goal(repo, monday_garmin, llm, later.id) == ChangeResult(proposal_id=None, needs_generation=False)
    strategy = repo.race_strategy(later.id)
    assert (strategy.garmin_workout_id, strategy.garmin_schedule_id) == (None, None)
    assert workout_id not in monday_garmin.workouts
    assert _get(repo, Goal, later.id).status == "archived" and llm.calls == []


def test_remove_goal_garmin_error_keeps_goal(repo, coach_home, monday_garmin):
    later = _exported_horizon_race(repo, monday_garmin)
    monday_garmin.fail_on = {"unschedule"}
    with pytest.raises(GarminUnavailable):
        remove_goal(repo, monday_garmin, FakeLLMProvider([]), later.id)
    assert _get(repo, Goal, later.id).status == "active"
    assert repo.race_strategy(later.id).garmin_workout_id is not None


def test_remove_unknown_goal(repo, monday_garmin):
    with pytest.raises(GoalError, match="introuvable ou archivé"):
        remove_goal(repo, monday_garmin, FakeLLMProvider([]), 999)


def test_draft_shorter_end_removes_late_sessions(repo, monday_garmin):
    goal = accepted_goal(repo, monday_garmin)
    update_goal(repo, monday_garmin, FakeLLMProvider([]), goal.id, GoalUpdate(race_date=date(2027, 2, 21)))
    assert repo.active_cycle().plan_accepted is False  # régénération en attente : brouillon
    monday_garmin.fail_on = {"delete_workout"}  # garde la trace des séances exportées à retirer
    llm = FakeLLMProvider([])
    _, result = add_goal(repo, monday_garmin, llm, other_input(race_date=date(2027, 1, 17), priority="principal"))
    assert result == ChangeResult(proposal_id=None, needs_generation=True) and llm.calls == []
    cycle = repo.active_cycle()
    assert cycle.end_date == date(2027, 1, 17)  # 11 semaines
    late = [s for s in repo.sessions(cycle.id) if s.week_index > 11]
    assert [(s.week_index, s.pending_removal) for s in late] == [(13, True), (14, True)]
    assert monday_garmin.schedules == {}
    # la génération suivante ne transmet pas ces séances comme fixes
    from tests.services.test_plans import _plan_from

    gen = FakeLLMProvider([_plan_from(1, {**{w: 3 for w in range(1, 11)}, 11: 2}, {2: 3000})])
    from coach.services.plans import generate_plan

    generate_plan(repo, monday_garmin, gen)
    assert "fixées" not in gen.calls[0] and "| semaine 13 |" not in gen.calls[0]


def test_regenerate_change_makes_pending_stale(repo, monday_garmin):
    goal = accepted_goal(repo, monday_garmin)
    old = repo.add(Proposal(analysis="avant", changes_json="[]"))
    _, result = update_goal(repo, monday_garmin, FakeLLMProvider([]), goal.id, GoalUpdate(race_date=date(2027, 2, 21)))
    assert result.needs_generation is True
    assert _proposals(repo) == [(old.id, "stale")]


def test_remove_last_goal_cleans_sync_error_sessions(repo, monday_garmin):
    """Clôture : une séance en `sync_error` qui tient encore des ids Garmin quitte aussi la montre."""
    goal = accepted_goal(repo, monday_garmin)
    cycle_id = _cid(repo)
    w13, w14 = (next(s for s in repo.sessions(cycle_id) if s.week_index == w and s.order == 1) for w in (13, 14))
    monday_garmin.workouts[900] = {}
    monday_garmin.schedules[901] = (900, date(2027, 2, 2))
    monday_garmin.calendar.setdefault(date(2027, 2, 2), []).append(901)
    with repo.transaction() as db:
        s = db.get(Session, w13.id)  # remplacement inachevé : la nouvelle version est sur la montre
        s.status, s.sync_error = "sync_error", "Synchronisation Garmin échouée : x"
        s.pending_old_workout_id = None
        db.add(s)
        s = db.get(Session, w14.id)  # ids actuels et anciens à la fois
        s.status, s.sync_error = "sync_error", "Synchronisation Garmin échouée : x"
        s.pending_old_workout_id, s.pending_old_schedule_id = 900, 901
        db.add(s)
    remove_goal(repo, monday_garmin, FakeLLMProvider([]), goal.id)
    assert repo.sessions(cycle_id) == []
    assert monday_garmin.workouts == {} and monday_garmin.schedules == {}


def test_close_cycle_garmin_failure_leaves_sessions_to_retry(repo, monday_garmin):
    """Retrait Garmin en échec à la clôture : les séances restent marquées pour retrait (relancé par la synchro)."""
    goal = accepted_goal(repo, monday_garmin)
    cycle_id = _cid(repo)
    monday_garmin.fail_on = {"unschedule"}
    remove_goal(repo, monday_garmin, FakeLLMProvider([]), goal.id)
    left = repo.sessions(cycle_id)
    assert len(left) == 2 and all((s.status, s.pending_removal) == ("sync_error", True) for s in left)
