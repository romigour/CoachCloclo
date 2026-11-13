import json
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlmodel import select

from coach.analysis.gpx import GpxError
from coach.garmin.port import FakeGarminClient, Metrics
from coach.llm.provider import FakeLLMProvider, LLMInvalidResponse
from coach.llm.schemas import Change
from coach.plan.models import ALL_DAYS, Cycle, Goal, Proposal, Session
from coach.services import CoachError
from coach.services.context import refresh_snapshot
from coach.services.plans import (
    GoalError,
    GoalInput,
    GoalUpdate,
    PlanSettingsUpdate,
    accept_plan,
    create_goal,
    generate_plan,
    parse_target_time,
    update_goal,
    update_plan_settings,
)
from tests.llm.factories import make_session, valid_plan_json
from tests.plan.factories import make_db_session
from tests.services.test_sync import adjustment_json

FIXTURES = Path(__file__).parent.parent / "fixtures" / "gpx"
METRICS = Metrics(hr_max=190, hr_rest=50, threshold_pace_s_km=300)


@pytest.fixture
def fake_garmin():
    return FakeGarminClient(metrics=METRICS)


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


def _cid(repo) -> int:
    """Id du cycle actif."""
    return repo.active_cycle().id


def _active_goal(repo) -> Goal | None:
    """Objectif à venir (un seul à ce stade)."""
    goals = repo.upcoming_goals()
    return goals[0] if goals else None


def _goal(repo, fake_garmin) -> Goal:
    return create_goal(repo, fake_garmin, goal_input())


def test_race_too_close_rejected(repo, fake_garmin):
    with pytest.raises(GoalError, match="au moins 14 jours"):
        create_goal(repo, fake_garmin, goal_input(race_date=fake_garmin.today() + timedelta(days=10)))


def test_race_in_past_rejected(repo, fake_garmin):
    with pytest.raises(GoalError):
        create_goal(repo, fake_garmin, goal_input(race_date=fake_garmin.today() - timedelta(days=3)))
    assert _active_goal(repo) is None


def test_gpx_dplus_used_when_not_given(repo, coach_home, fake_garmin):
    g = create_goal(repo, fake_garmin, goal_input(d_plus_m=0, gpx=FIXTURES / "climb.gpx"))
    assert g.d_plus_m == pytest.approx(600, abs=30)
    assert (coach_home / "gpx" / f"{g.id}.gpx").exists()
    assert g.gpx_summary_json and g.gpx_path


def test_given_dplus_kept_with_gpx(repo, coach_home, fake_garmin):
    g = create_goal(repo, fake_garmin, goal_input(d_plus_m=1500, gpx=FIXTURES / "climb.gpx"))
    assert g.d_plus_m == 1500


def test_plan_start_is_monday(repo, fake_garmin):
    assert _goal(repo, fake_garmin).plan_start == date(2026, 11, 2)


def test_generate_plan_persists_sessions(repo, fake_garmin):
    goal = _goal(repo, fake_garmin)
    llm = FakeLLMProvider([valid_plan_json(n_weeks=14, per_week=3)])
    plan = generate_plan(repo, fake_garmin, llm)
    sessions = repo.sessions(_cid(repo))
    assert len(plan.weeks) == 14
    assert len(sessions) == 42 and all(s.status == "todo" for s in sessions)
    assert repo.latest_snapshot().hr_max == 190


def test_generate_plan_invalid_twice_raises_and_persists_nothing(repo, fake_garmin):
    goal = _goal(repo, fake_garmin)
    with pytest.raises(LLMInvalidResponse):
        generate_plan(repo, fake_garmin, FakeLLMProvider(["{}", "{}"]))
    assert repo.sessions(_cid(repo)) == []


def test_regenerate_replaces_todo_and_resets_accepted(repo, fake_garmin):
    goal = _goal(repo, fake_garmin)
    generate_plan(repo, fake_garmin, FakeLLMProvider([valid_plan_json(14, 3)]))
    accept_plan(repo)
    assert repo.active_cycle().plan_accepted is True
    generate_plan(repo, fake_garmin, FakeLLMProvider([valid_plan_json(14, 2)]))
    assert len(repo.sessions(_cid(repo))) == 28
    assert repo.active_cycle().plan_accepted is False


def test_new_goal_archives_previous(repo, fake_garmin):
    old = _goal(repo, fake_garmin)
    old_cycle = repo.active_cycle()
    todo = repo.add(make_db_session(old_cycle.id, week_index=1, order=1))
    exported = make_db_session(old_cycle.id, week_index=1, order=2)
    exported.status = "exported"
    exported = repo.add(exported)
    new = _goal(repo, fake_garmin)
    assert _active_goal(repo).id == new.id
    assert repo.active_cycle().id != old_cycle.id
    with repo.transaction() as db:
        assert db.get(Goal, old.id).status == "archived"
        assert db.get(Cycle, old_cycle.id).status == "done"
    remaining = [s.id for s in repo.sessions(old_cycle.id)]
    assert remaining == [exported.id] and todo.id not in remaining


def test_refresh_snapshot_without_hr_max(repo):
    with pytest.raises(CoachError, match="FC max inconnue"):
        refresh_snapshot(repo, FakeGarminClient(metrics=Metrics()))


def test_refresh_snapshot_relays_real_zone_error(repo):
    with pytest.raises(CoachError, match="FC repos inconnue") as e:
        refresh_snapshot(repo, FakeGarminClient(metrics=Metrics(hr_max=190)))
    assert "FC max" not in str(e.value)


def test_generation_prompt_gives_today(repo, fake_garmin):
    goal = _goal(repo, fake_garmin)  # aujourd'hui : mercredi 4 novembre 2026
    llm = FakeLLMProvider([valid_plan_json(n_weeks=14, per_week=3)])
    generate_plan(repo, fake_garmin, llm)
    assert "Aujourd'hui : mercredi 4 novembre 2026 (semaine 1)" in llm.calls[0]


def test_gpx_write_failure_keeps_previous_goal(repo, coach_home, fake_garmin, monkeypatch):
    old = _goal(repo, fake_garmin)
    old_cycle = repo.active_cycle()
    todo = repo.add(make_db_session(old_cycle.id, week_index=1, order=1))

    def boom(self, data):
        raise OSError("disque plein")

    monkeypatch.setattr(Path, "write_bytes", boom)
    with pytest.raises(OSError):
        create_goal(repo, fake_garmin, goal_input(gpx=FIXTURES / "climb.gpx"))
    assert _active_goal(repo).id == old.id
    assert repo.active_cycle().id == old_cycle.id
    assert [s.id for s in repo.sessions(old_cycle.id)] == [todo.id]
    with repo.transaction() as db:
        assert len(db.exec(select(Goal)).all()) == 1
        assert len(db.exec(select(Cycle)).all()) == 1
    assert not list((coach_home / "gpx").glob("*.gpx"))


def test_gpx_error_creates_no_goal(repo, fake_garmin):
    with pytest.raises(GpxError):
        create_goal(repo, fake_garmin, goal_input(gpx=FIXTURES / "broken.gpx"))
    assert _active_goal(repo) is None
    assert repo.active_cycle() is None


def test_generate_or_accept_without_cycle_rejected(repo, fake_garmin):
    llm = FakeLLMProvider([valid_plan_json(14, 3)])
    with pytest.raises(GoalError, match="Aucun plan en cours"):
        generate_plan(repo, fake_garmin, llm)
    with pytest.raises(GoalError, match="Aucun plan en cours"):
        accept_plan(repo)
    assert llm.calls == []


def test_create_goal_creates_cycle_from_settings(repo, fake_garmin):
    goal = create_goal(
        repo, fake_garmin,
        goal_input(available_days=["mardi", "jeudi", "samedi"], long_run_day="samedi", include_bike=True,
                   priority="secondaire"),
    )
    cycle = repo.active_cycle()
    assert (cycle.plan_start, cycle.end_date, cycle.sessions_per_week) == (date(2026, 11, 2), date(2027, 2, 7), 3)
    assert cycle.available_days() == ["mardi", "jeudi", "samedi"] and cycle.long_run_day == "samedi"
    assert cycle.include_bike is True and cycle.plan_accepted is False
    assert goal.priority == "secondaire" and [g.id for g in repo.goals_in(cycle)] == [goal.id]


def test_parse_target_time():
    assert parse_target_time("3:45") == 13500 and parse_target_time("1:05:30") == 3930
    for bad in ("", "3h45", "3:75", "0:00"):
        with pytest.raises(GoalError):
            parse_target_time(bad)


def test_create_goal_with_user_time(repo, fake_garmin):
    g = create_goal(repo, fake_garmin, goal_input(target_time_s=18000))
    assert (g.target_time_s, g.target_source) == (18000, "user")


def test_create_goal_without_time_is_claude_mode(repo, fake_garmin):
    g = create_goal(repo, fake_garmin, goal_input())
    assert (g.target_time_s, g.target_source) == (None, "claude")


def test_create_goal_rejects_implausible_time(repo, fake_garmin):
    with pytest.raises(GoalError, match="invraisemblable"):
        create_goal(repo, fake_garmin, goal_input(target_time_s=3600))  # 42 km en 1 h
    assert _active_goal(repo) is None


def test_generate_saves_claude_estimate(repo, fake_garmin):
    goal = _goal(repo, fake_garmin)
    generate_plan(repo, fake_garmin, FakeLLMProvider([valid_plan_json(14, 3, estimated_time_s=19800)]))
    assert _active_goal(repo).target_time_s == 19800


def test_regenerate_reestimates(repo, fake_garmin):
    goal = _goal(repo, fake_garmin)
    generate_plan(repo, fake_garmin, FakeLLMProvider([valid_plan_json(14, 3, estimated_time_s=19800)]))
    generate_plan(repo, fake_garmin, FakeLLMProvider([valid_plan_json(14, 3, estimated_time_s=20400)]))
    g = _active_goal(repo)
    assert (g.target_time_s, g.target_source) == (20400, "claude")


def test_generate_keeps_user_time(repo, fake_garmin):
    goal = create_goal(repo, fake_garmin, goal_input(target_time_s=18000))
    generate_plan(repo, fake_garmin, FakeLLMProvider([valid_plan_json(14, 3, estimated_time_s=1)]))
    g = _active_goal(repo)
    assert (g.target_time_s, g.target_source) == (18000, "user")


def test_generate_claude_mode_requires_estimate(repo, fake_garmin):
    goal = _goal(repo, fake_garmin)
    llm = FakeLLMProvider([valid_plan_json(14, 3, estimated_time_s=None)] * 2)
    with pytest.raises(LLMInvalidResponse):
        generate_plan(repo, fake_garmin, llm)


# --- modification d'un objectif en cours --------------------------------------------------


@pytest.fixture
def monday_garmin():
    return FakeGarminClient(metrics=METRICS, today=date(2026, 11, 2))


def _accepted_goal(repo, garmin, **overrides) -> Goal:
    """Objectif validé (14 semaines, 3 séances par semaine) ; séance 1 des semaines 13-14 exportée
    (planifiée sur le faux Garmin)."""
    goal = create_goal(repo, garmin, goal_input(**overrides))
    for w in range(1, 15):
        for o in (1, 2, 3):
            s = make_db_session(_cid(repo), week_index=w, order=o)
            if w >= 13 and o == 1:
                s.status = "exported"
                s.scheduled_date = date(2026, 11, 3) + timedelta(weeks=w - 1)  # mardi
                s.garmin_workout_id, s.garmin_schedule_id = 100 + w, 200 + w
                garmin.workouts[100 + w] = {}
                garmin.schedules[200 + w] = (100 + w, s.scheduled_date)
                garmin.calendar.setdefault(s.scheduled_date, []).append(200 + w)
            repo.add(s)
    accept_plan(repo)
    return _active_goal(repo)


def _proposals(repo) -> list[tuple[int, str]]:
    with repo.transaction() as db:
        return sorted((p.id, p.status) for p in db.exec(select(Proposal)).all())


def test_update_goal_target_only(repo, monday_garmin):
    goal = _accepted_goal(repo, monday_garmin, target_time_s=18000)
    llm = FakeLLMProvider([adjustment_json()])
    saved, pid = update_goal(repo, monday_garmin, llm, goal.id, GoalUpdate(target_time="5:30"))
    g = _active_goal(repo)
    assert (g.target_time_s, g.target_source, g.race_date) == (19800, "user", date(2027, 2, 7))
    assert (saved.target_time_s, saved.target_source) == (19800, "user")
    assert _proposals(repo) == [(pid, "pending")]
    assert (
        "L'athlète a modifié son objectif : temps visé 5 h 30 au lieu de 5 h 00. "
        "Adapte les séances à venir en conséquence."
    ) in llm.calls[0]
    assert len(repo.sessions(_cid(repo))) == 42 and monday_garmin.calls == []


def test_update_goal_target_without_previous(repo, monday_garmin):
    goal = _accepted_goal(repo, monday_garmin)  # mode Claude, aucun temps encore estimé
    llm = FakeLLMProvider([adjustment_json()])
    update_goal(repo, monday_garmin, llm, goal.id, GoalUpdate(target_time="5:30"))
    assert "temps visé 5 h 30, aucun auparavant" in llm.calls[0]
    g = _active_goal(repo)
    assert (g.target_time_s, g.target_source) == (19800, "user")


def test_update_goal_earlier_date_removes_weeks(repo, monday_garmin):
    goal = _accepted_goal(repo, monday_garmin)
    llm = FakeLLMProvider([adjustment_json()])
    update_goal(repo, monday_garmin, llm, goal.id, GoalUpdate(race_date=date(2027, 1, 24)))
    assert _active_goal(repo).race_date == date(2027, 1, 24)
    assert repo.active_cycle().end_date == date(2027, 1, 24)
    # todo des semaines 13-14 supprimées ; exportées retirées de la montre puis supprimées
    assert max(s.week_index for s in repo.sessions(_cid(repo))) == 12
    assert len(repo.sessions(_cid(repo))) == 36
    assert monday_garmin.calls == ["unschedule", "delete_workout"] * 2
    assert monday_garmin.workouts == {} and monday_garmin.schedules == {} and monday_garmin.calendar == {}
    assert "course déplacée du 07/02/2027 au 24/01/2027" in llm.calls[0]
    assert "| semaine 12 |" in llm.calls[0] and "| semaine 13 |" not in llm.calls[0]


def test_update_goal_date_in_current_week(repo, monday_garmin):
    goal = _accepted_goal(repo, monday_garmin)
    update_goal(
        repo, monday_garmin, FakeLLMProvider([adjustment_json()]), goal.id,
        GoalUpdate(race_date=date(2026, 11, 8)),
    )
    sessions = repo.sessions(_cid(repo))
    assert [s.week_index for s in sessions if s.status == "todo"] == [1, 1, 1]
    assert [s.week_index for s in sessions] == [1, 1, 1]
    assert monday_garmin.workouts == {} and monday_garmin.schedules == {}


def test_update_goal_removes_exported_after_race_day(repo, monday_garmin):
    goal = _accepted_goal(repo, monday_garmin)
    # course le lundi 2027-01-25 (semaine 13) : la séance exportée du mardi 26 tombe après
    update_goal(
        repo, monday_garmin, FakeLLMProvider([adjustment_json()]), goal.id,
        GoalUpdate(race_date=date(2027, 1, 25)),
    )
    week13 = repo.sessions(_cid(repo), week_index=13)
    assert week13 == []  # les todo (jour suggéré mardi) tombent aussi après la course
    assert repo.sessions(_cid(repo), week_index=14) == []
    assert monday_garmin.workouts == {} and monday_garmin.schedules == {}


def test_update_goal_mid_week_removes_todo_after_race_day(repo, monday_garmin):
    goal = _accepted_goal(repo, monday_garmin)
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
    goal = _accepted_goal(repo, monday_garmin)
    monday_garmin.fail_on = {"delete_workout"}
    _, pid = update_goal(
        repo, monday_garmin, FakeLLMProvider([adjustment_json()]), goal.id,
        GoalUpdate(race_date=date(2027, 1, 24)),
    )
    assert _active_goal(repo).race_date == date(2027, 1, 24)
    assert _proposals(repo) == [(pid, "pending")]
    late = [s for s in repo.sessions(_cid(repo)) if s.week_index > 12]
    assert len(late) == 2
    for s in late:
        assert (s.status, s.pending_removal) == ("sync_error", True)
        assert s.sync_error.startswith("Synchronisation Garmin échouée")
        assert s.pending_old_schedule_id is None and s.pending_old_workout_id is not None
    assert monday_garmin.schedules == {} and set(monday_garmin.workouts) == {113, 114}


def test_update_goal_later_date_allows_new_weeks(repo, monday_garmin):
    goal = _accepted_goal(repo, monday_garmin)
    add = Change(op="add", session=make_session(week_index=16, order=1), reason="Nouvelle semaine")
    llm = FakeLLMProvider([adjustment_json([add])])
    _, pid = update_goal(repo, monday_garmin, llm, goal.id, GoalUpdate(race_date=date(2027, 2, 21)))
    assert len(llm.calls) == 1
    with repo.transaction() as db:
        assert json.loads(db.get(Proposal, pid).changes_json)[0]["session"]["week_index"] == 16
    assert len(repo.sessions(_cid(repo))) == 42 and monday_garmin.calls == []


def test_update_goal_makes_pending_stale(repo, monday_garmin):
    goal = _accepted_goal(repo, monday_garmin)
    old = repo.add(Proposal(analysis="avant", changes_json="[]"))
    _, pid = update_goal(
        repo, monday_garmin, FakeLLMProvider([adjustment_json()]), goal.id, GoalUpdate(target_time="5:30")
    )
    assert _proposals(repo) == [(old.id, "stale"), (pid, "pending")]


def test_update_goal_llm_failure_changes_nothing(repo, monday_garmin):
    goal = _accepted_goal(repo, monday_garmin, target_time_s=18000)
    old = repo.add(Proposal(analysis="avant", changes_json="[]"))
    before = [s.model_dump() for s in repo.sessions(_cid(repo))]
    with pytest.raises(LLMInvalidResponse):
        update_goal(
            repo, monday_garmin, FakeLLMProvider(["{}", "{}"]), goal.id,
            GoalUpdate(race_date=date(2027, 1, 24), target_time="5:30"),
        )
    g = _active_goal(repo)
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
    ],
)
def test_update_goal_rejections(repo, monday_garmin, update, match):
    goal = _accepted_goal(repo, monday_garmin, target_time_s=18000)
    llm = FakeLLMProvider([])
    with pytest.raises(GoalError, match=match):
        update_goal(repo, monday_garmin, llm, goal.id, update)
    assert llm.calls == []


def test_update_goal_requires_accepted_active_goal(repo, monday_garmin):
    draft = create_goal(repo, monday_garmin, goal_input())
    llm = FakeLLMProvider([])
    with pytest.raises(GoalError, match="validé"):
        update_goal(repo, monday_garmin, llm, draft.id, GoalUpdate(target_time="5:30"))
    old = _accepted_goal(repo, monday_garmin)
    _accepted_goal(repo, monday_garmin)  # archive `old`
    for bad in (old.id, 999):
        with pytest.raises(GoalError, match="introuvable ou archivé"):
            update_goal(repo, monday_garmin, llm, bad, GoalUpdate(target_time="5:30"))
    assert llm.calls == []


# --- disponibilités ------------------------------------------------------------------------


def test_create_goal_rejects_fewer_days_than_sessions(repo, fake_garmin):
    with pytest.raises(GoalError, match="au moins 3 jours possibles"):
        create_goal(repo, fake_garmin, goal_input(sessions_per_week=3, available_days=["mardi", "jeudi"]))


def test_create_goal_rejects_long_run_day_not_available(repo, fake_garmin):
    with pytest.raises(GoalError, match="Le jour de la sortie longue doit faire partie des jours possibles"):
        create_goal(
            repo, fake_garmin,
            goal_input(available_days=["mardi", "jeudi", "samedi"], long_run_day="dimanche"),
        )


def test_create_goal_stores_availability_in_week_order(repo, fake_garmin):
    create_goal(
        repo, fake_garmin,
        goal_input(available_days=["samedi", "mardi", "jeudi", "mardi"], long_run_day="samedi"),
    )
    cycle = repo.active_cycle()
    assert cycle.available_days() == ["mardi", "jeudi", "samedi"] and cycle.long_run_day == "samedi"


def test_generate_plan_retries_on_unavailable_day(repo, fake_garmin):
    create_goal(repo, fake_garmin, goal_input(available_days=["mardi", "jeudi", "samedi"]))
    bad = valid_plan_json(n_weeks=14, per_week=3).replace('"mardi"', '"lundi"')
    llm = FakeLLMProvider([bad, valid_plan_json(n_weeks=14, per_week=3)])
    generate_plan(repo, fake_garmin, llm)
    assert "lundi n'est pas un jour possible" in llm.calls[1]
    assert "Jours possibles : mardi, jeudi, samedi" in llm.calls[0]


def test_update_plan_settings_creates_proposal_with_note(repo, monday_garmin):
    _accepted_goal(repo, monday_garmin)
    llm = FakeLLMProvider([adjustment_json()])
    days = ["mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    # les séances existantes sont toutes le mardi : aucune n'est sur un jour retiré
    _, pid = update_plan_settings(repo, monday_garmin, llm, PlanSettingsUpdate(available_days=days))
    assert repo.active_cycle().available_days() == days
    assert "jours possibles : mardi, mercredi" in llm.calls[0]
    assert _proposals(repo) == [(pid, "pending")]


def test_update_plan_settings_removed_day_forces_claude_to_move_sessions(repo, monday_garmin):
    _accepted_goal(repo, monday_garmin)
    llm = FakeLLMProvider([adjustment_json(), adjustment_json()])
    with pytest.raises(LLMInvalidResponse):
        update_plan_settings(
            repo, monday_garmin, llm,
            PlanSettingsUpdate(available_days=["lundi", "mercredi", "jeudi"]),  # mardi retiré
        )
    assert "mardi n'est pas un jour possible" in llm.calls[1]
    assert repo.active_cycle().available_days() == list(ALL_DAYS)


def test_update_plan_settings_clears_long_run_day(repo, monday_garmin):
    _accepted_goal(repo, monday_garmin, long_run_day="mardi")
    assert repo.active_cycle().long_run_day == "mardi"
    llm = FakeLLMProvider([adjustment_json()])
    update_plan_settings(repo, monday_garmin, llm, PlanSettingsUpdate(long_run_day=""))
    assert repo.active_cycle().long_run_day is None
    assert "plus de jour imposé pour la sortie longue" in llm.calls[0]


def test_update_plan_settings_rejections(repo, monday_garmin):
    _accepted_goal(repo, monday_garmin)
    llm = FakeLLMProvider([])
    with pytest.raises(GoalError, match="au moins 3 jours possibles"):
        update_plan_settings(repo, monday_garmin, llm, PlanSettingsUpdate(available_days=["mardi", "jeudi"]))
    with pytest.raises(GoalError, match="sortie longue doit faire partie"):
        update_plan_settings(
            repo, monday_garmin, llm,
            PlanSettingsUpdate(available_days=["mardi", "jeudi", "samedi"], long_run_day="dimanche"),
        )
    with pytest.raises(GoalError, match="Aucune modification"):
        update_plan_settings(repo, monday_garmin, llm, PlanSettingsUpdate(available_days=list(ALL_DAYS)))
    assert llm.calls == []


def test_update_plan_settings_requires_accepted_plan(repo, monday_garmin):
    llm = FakeLLMProvider([])
    with pytest.raises(GoalError, match="Aucun plan en cours"):
        update_plan_settings(repo, monday_garmin, llm, PlanSettingsUpdate(include_bike=True))
    create_goal(repo, monday_garmin, goal_input())
    with pytest.raises(GoalError, match="validé"):
        update_plan_settings(repo, monday_garmin, llm, PlanSettingsUpdate(include_bike=True))
    assert llm.calls == []
