from datetime import date

import pytest
from pydantic import ValidationError

from sqlmodel import select

from coach.config import load_settings, save_settings
from coach.llm.provider import FakeLLMProvider
from coach.garmin.port import GarminAuthRequired, GarminRateLimited, GarminUnavailable
from coach.plan.models import Event, Proposal, Session
from coach.services import CoachError
from coach.services.adjust import request_adjustment
from coach.services.events import (
    EventError,
    EventInput,
    build_event,
    create_event,
    delete_event,
    event_note,
    resume_injury,
)
from tests.plan.factories import make_db_session, make_goal
from tests.services.test_sync import accepted_plan, adjustment_json, draft_plan, fake_garmin  # noqa: F401

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


def test_open_injury_in_the_future_refused(repo, goal):
    with pytest.raises(EventError, match="Un arrêt sans date de reprise doit avoir déjà commencé"):
        build(repo, goal, kind="injury", start_date=date(2026, 11, 4))
    assert build(repo, goal, kind="injury", start_date=TODAY).end_date is None
    # un arrêt futur de durée connue reste possible
    assert build(repo, goal, kind="injury", start_date=date(2026, 11, 4), end_date=date(2026, 11, 6))


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


def test_light_week_empty_days_means_no_restriction(repo, goal):
    e = build(repo, goal, kind="light_week", start_date=date(2026, 11, 2), max_sessions=1, days=[])
    assert e.days() is None and e.days_json is None


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


# --- déclarer, supprimer, reprendre ------------------------------------------------------------


def _statuses(repo):
    with repo.transaction() as db:
        return {p.id: p.status for p in db.exec(select(Proposal)).all()}


def test_create_event_produces_pending_proposal(repo, coach_home, fake_garmin, accepted_plan):
    llm = FakeLLMProvider([adjustment_json(analysis="Un"), adjustment_json(analysis="Deux")])
    data = EventInput(kind="unavailable", start_date=date(2026, 11, 16), end_date=date(2026, 11, 18))
    first = create_event(repo, fake_garmin, llm, accepted_plan.id, data)
    second = create_event(repo, fake_garmin, llm, accepted_plan.id, data)
    assert first.error is None and second.error is None
    assert _statuses(repo) == {first.proposal_id: "stale", second.proposal_id: "pending"}
    assert "indisponible du 16/11/2026 au 18/11/2026" in llm.calls[0]
    assert len(repo.events(accepted_plan.id)) == 2


def test_create_event_requires_accepted_plan(repo, coach_home, fake_garmin, draft_plan):
    data = EventInput(kind="unavailable", start_date=date(2026, 11, 16), end_date=date(2026, 11, 18))
    with pytest.raises(EventError, match="Le plan de l'objectif doit être validé"):
        create_event(repo, fake_garmin, FakeLLMProvider([]), draft_plan.id, data)
    assert repo.events(draft_plan.id) == []


def test_create_event_keeps_event_when_claude_fails(repo, coach_home, fake_garmin, accepted_plan):
    data = EventInput(kind="unavailable", start_date=date(2026, 11, 16), end_date=date(2026, 11, 18))
    result = create_event(repo, fake_garmin, FakeLLMProvider([]), accepted_plan.id, data)
    assert result.proposal_id is None and result.error
    assert [e.id for e in repo.events(accepted_plan.id)] == [result.event_id]


def test_request_adjustment_after_failure_succeeds(repo, coach_home, fake_garmin, accepted_plan):
    data = EventInput(kind="unavailable", start_date=date(2026, 11, 16), end_date=date(2026, 11, 18))
    create_event(repo, fake_garmin, FakeLLMProvider([]), accepted_plan.id, data)
    settings = load_settings()
    settings.proposal_due = True
    save_settings(settings)
    proposal_id = request_adjustment(repo, fake_garmin, FakeLLMProvider([adjustment_json()]), accepted_plan.id)
    assert repo.pending_proposal().id == proposal_id
    assert load_settings().proposal_due is False


def test_fatigue_marks_session_missed(repo, coach_home, fake_garmin, accepted_plan):
    sessions = repo.sessions(accepted_plan.id)
    exported = next(s for s in sessions if s.status == "exported")
    todo = next(s for s in sessions if s.status == "todo")
    llm = FakeLLMProvider([adjustment_json(), adjustment_json()])
    for s in (exported, todo):
        create_event(repo, fake_garmin, llm, accepted_plan.id, EventInput(kind="fatigue", session_id=s.id))
        assert repo.session(s.id).status == "missed"
    assert "fatigue" in llm.calls[0]


def test_fatigue_with_invalid_session_changes_nothing(repo, coach_home, fake_garmin, accepted_plan):
    data = EventInput(kind="fatigue", session_id=999)
    with pytest.raises(EventError):
        create_event(repo, fake_garmin, FakeLLMProvider([]), accepted_plan.id, data)
    assert repo.events(accepted_plan.id) == []


def test_resume_injury_sets_end_and_asks_progressive_return(repo, coach_home, fake_garmin, accepted_plan):
    injury = repo.add(Event(goal_id=accepted_plan.id, kind="injury", start_date=date(2026, 10, 30), note="genou"))
    llm = FakeLLMProvider([adjustment_json()])
    result = resume_injury(repo, fake_garmin, llm, injury.id, date(2026, 11, 2))
    assert result.proposal_id is not None and result.error is None
    assert repo.open_injury(accepted_plan.id) is None
    assert repo.events(accepted_plan.id)[0].end_date == date(2026, 11, 1)
    assert "Reprise après 3 jours d'arrêt (genou)" in llm.calls[-1]
    assert "reprise progressive" in llm.calls[-1]


def test_resume_injury_same_day_keeps_end_at_start(repo, coach_home, fake_garmin, accepted_plan):
    injury = repo.add(Event(goal_id=accepted_plan.id, kind="injury", start_date=date(2026, 11, 4)))
    resume_injury(repo, fake_garmin, FakeLLMProvider([adjustment_json()]), injury.id, date(2026, 11, 4))
    assert repo.events(accepted_plan.id)[0].end_date == date(2026, 11, 4)


def test_resume_injury_rejects_invalid(repo, coach_home, fake_garmin, accepted_plan):
    injury = repo.add(Event(goal_id=accepted_plan.id, kind="injury", start_date=date(2026, 11, 4)))
    closed = repo.add(
        Event(goal_id=accepted_plan.id, kind="injury", start_date=date(2026, 10, 1), end_date=date(2026, 10, 5))
    )
    with pytest.raises(EventError, match="La reprise doit être après le début de l'arrêt"):
        resume_injury(repo, fake_garmin, FakeLLMProvider([]), injury.id, date(2026, 11, 3))
    with pytest.raises(EventError):
        resume_injury(repo, fake_garmin, FakeLLMProvider([]), closed.id, date(2026, 11, 3))
    with pytest.raises(EventError, match="Imprévu introuvable"):
        resume_injury(repo, fake_garmin, FakeLLMProvider([]), 999, date(2026, 11, 3))
    assert repo.open_injury(accepted_plan.id).id == injury.id


def test_resume_injury_keeps_end_when_claude_fails(repo, coach_home, fake_garmin, accepted_plan):
    injury = repo.add(Event(goal_id=accepted_plan.id, kind="injury", start_date=date(2026, 11, 1)))
    result = resume_injury(repo, fake_garmin, FakeLLMProvider([]), injury.id, date(2026, 11, 4))
    assert result.proposal_id is None and result.error
    assert repo.open_injury(accepted_plan.id) is None


def test_delete_event(repo, accepted_plan):
    e = repo.add(
        Event(goal_id=accepted_plan.id, kind="unavailable", start_date=date(2026, 11, 9), end_date=date(2026, 11, 9))
    )
    delete_event(repo, e.id)
    assert repo.events(accepted_plan.id) == []
    with pytest.raises(EventError, match="Imprévu introuvable"):
        delete_event(repo, e.id)


def test_event_note_describes_each_kind():
    base = {"goal_id": 1, "start_date": date(2026, 11, 9)}
    assert "indisponible du 09/11/2026 au 11/11/2026 (voyage)" in event_note(
        Event(kind="unavailable", end_date=date(2026, 11, 11), note="voyage", **base)
    )
    assert "arrêt depuis le 09/11/2026" in event_note(Event(kind="injury", **base))
    assert "2 séance(s) au maximum, jours possibles : mardi, samedi" in event_note(
        Event(kind="light_week", max_sessions=2, days_json='["mardi", "samedi"]', **base)
    )
    assert "fatigue" in event_note(Event(kind="fatigue", **base))


def _fail_metrics(fake_garmin, exc):
    def boom():
        raise exc

    fake_garmin.metrics = boom


@pytest.mark.parametrize(
    "exc, message",
    [
        (GarminUnavailable("Garmin indisponible (simulé)"), "Garmin indisponible (simulé)"),
        (GarminAuthRequired(), "Connexion Garmin requise"),
        (GarminRateLimited(), "Garmin limite les requêtes, réessaie plus tard"),
        (CoachError("Le plan n'est plus validé"), "Le plan n'est plus validé"),
    ],
)
def test_create_event_keeps_event_on_garmin_or_coach_error(repo, coach_home, fake_garmin, accepted_plan, exc, message):
    _fail_metrics(fake_garmin, exc)
    data = EventInput(kind="unavailable", start_date=date(2026, 11, 16), end_date=date(2026, 11, 18))
    result = create_event(repo, fake_garmin, FakeLLMProvider([]), accepted_plan.id, data)
    assert result.proposal_id is None and result.error == message
    assert [e.id for e in repo.events(accepted_plan.id)] == [result.event_id]


@pytest.mark.parametrize(
    "exc, message",
    [
        (GarminUnavailable("Garmin indisponible (simulé)"), "Garmin indisponible (simulé)"),
        (GarminAuthRequired(), "Connexion Garmin requise"),
        (GarminRateLimited(), "Garmin limite les requêtes, réessaie plus tard"),
        (CoachError("Le plan n'est plus validé"), "Le plan n'est plus validé"),
    ],
)
def test_resume_injury_closes_stop_on_garmin_or_coach_error(repo, coach_home, fake_garmin, accepted_plan, exc, message):
    injury = repo.add(Event(goal_id=accepted_plan.id, kind="injury", start_date=date(2026, 11, 1)))
    _fail_metrics(fake_garmin, exc)
    result = resume_injury(repo, fake_garmin, FakeLLMProvider([]), injury.id, date(2026, 11, 4))
    assert result.proposal_id is None and result.error == message
    assert repo.open_injury(accepted_plan.id) is None


def test_fatigue_names_the_missed_session_to_claude(repo, coach_home, fake_garmin, accepted_plan):
    todo = next(s for s in repo.sessions(accepted_plan.id) if s.status == "todo")
    llm = FakeLLMProvider([adjustment_json()])
    result = create_event(repo, fake_garmin, llm, accepted_plan.id, EventInput(kind="fatigue", session_id=todo.id))
    assert result.error is None
    manquees = llm.calls[0].split("Séances manquées :")[1]
    assert todo.title in manquees.split("Séances")[0]
    assert f"séance ratée : {todo.title} ({todo.type}, semaine {todo.week_index})" in llm.calls[0]


def test_event_note_names_the_missed_session():
    s = Session(goal_id=1, title="Sortie vélo", type="endurance", sport="bike", week_index=3, order=1)
    note = event_note(Event(goal_id=1, kind="fatigue", start_date=TODAY), s)
    assert "séance ratée : Sortie vélo (endurance, vélo, semaine 3)" in note


def test_resume_note_singular_day(repo, coach_home, fake_garmin, accepted_plan):
    injury = repo.add(Event(goal_id=accepted_plan.id, kind="injury", start_date=date(2026, 11, 3)))
    llm = FakeLLMProvider([adjustment_json()])
    resume_injury(repo, fake_garmin, llm, injury.id, date(2026, 11, 4))
    assert "Reprise après un jour d'arrêt" in llm.calls[-1]
