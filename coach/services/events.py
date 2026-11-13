"""Imprévus de l'athlète : validation avant enregistrement."""

import json
from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, Field

from coach.garmin.port import GarminAuthRequired, GarminPort, GarminRateLimited, GarminUnavailable
from coach.llm.provider import LLMError, LLMProvider
from coach.llm.schemas import Weekday
from coach.plan import calendar
from coach.plan.models import Cycle, Event, Session
from coach.plan.repo import Repo
from coach.services import CoachError
from coach.services.adjust import request_adjustment
from coach.services.plans import _active_cycle, normalize_days


class EventError(CoachError):
    """Imprévu invalide."""


class EventInput(BaseModel):
    kind: Literal["unavailable", "injury", "light_week", "fatigue"]
    start_date: date | None = None
    end_date: date | None = None
    max_sessions: int | None = Field(None, ge=0)
    days: list[Weekday] | None = None
    session_id: int | None = None
    note: str | None = Field(None, max_length=1000)


def _check_order(start: date, end: date | None) -> None:
    if end is not None and end < start:
        raise EventError("La fin doit être après le début")


def _is_plan_monday(cycle: Cycle, d: date | None) -> bool:
    return (
        d is not None
        and d.weekday() == 0
        and 1 <= calendar.week_of(cycle, d) <= calendar.n_weeks(cycle.plan_start, cycle.end_date)
    )


def build_event(repo: Repo, cycle: Cycle, data: EventInput, today: date) -> Event:
    """Valide `data` et renvoie l'imprévu à enregistrer (n'écrit rien)."""
    start, end = data.start_date, data.end_date
    max_sessions = days = session_id = None
    if data.kind == "unavailable":
        if start is None or end is None:
            raise EventError("Indique les dates de début et de fin")
        _check_order(start, end)
    elif data.kind == "injury":
        if start is None:
            raise EventError("Indique la date de début")
        _check_order(start, end)
        if end is None and start > today:
            raise EventError("Un arrêt sans date de reprise doit avoir déjà commencé")
        # un seul arrêt ouvert : seul un nouvel arrêt ouvert entre en conflit
        if end is None and repo.open_injury(cycle.id) is not None:
            raise EventError("Un arrêt est déjà en cours : signale d'abord la reprise")
    elif data.kind == "light_week":
        if not _is_plan_monday(cycle, start):
            raise EventError("Choisis une semaine du plan")
        if data.max_sessions is None:
            raise EventError("Indique le nombre de séances maximum")
        end = start + timedelta(days=6)
        max_sessions = data.max_sessions
        if data.days:  # liste vide = aucune restriction de jours
            days = normalize_days(data.days)
            if not set(days) <= set(cycle.available_days()):
                raise EventError("Les jours de la semaine allégée doivent faire partie de tes jours possibles")
    else:  # fatigue : toujours datée d'aujourd'hui
        start = end = today
        if data.session_id is not None:
            try:
                owned = repo.session(data.session_id).cycle_id == cycle.id
            except KeyError:
                owned = False
            if not owned:
                raise EventError("Séance introuvable")
            session_id = data.session_id
    return Event(
        cycle_id=cycle.id,
        kind=data.kind,
        start_date=start,
        end_date=end,
        max_sessions=max_sessions,
        days_json=None if days is None else json.dumps(days),
        session_id=session_id,
        note=data.note,
    )


class EventResult(BaseModel):
    event_id: int
    proposal_id: int | None
    error: str | None


_DEFAULT_ERROR = "Claude n'a pas pu proposer d'ajustement, réessaie"


def _fmt(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def event_note(event: Event, session: Session | None = None) -> str:
    """Description française de l'imprévu, transmise à Claude comme `change_note`.

    `session` est la séance ratée d'une fatigue : Claude ne la voit plus parmi les séances à venir."""
    extra = f" ({event.note})" if event.note else ""
    if event.kind == "unavailable":
        text = f"indisponible du {_fmt(event.start_date)} au {_fmt(event.end_date)}"
    elif event.kind == "injury":
        text = (
            f"blessure : arrêt depuis le {_fmt(event.start_date)}"
            if event.end_date is None
            else f"blessure : arrêt du {_fmt(event.start_date)} au {_fmt(event.end_date)}"
        )
    elif event.kind == "light_week":
        days = event.days()
        text = f"semaine allégée du {_fmt(event.start_date)} : {event.max_sessions} séance(s) au maximum"
        if days:
            text += f", jours possibles : {', '.join(days)}"
    else:
        text = "fatigue signalée aujourd'hui"
        if session is not None:
            kind = f"{session.type}, vélo" if session.sport == "bike" else session.type
            text += f", séance ratée : {session.title} ({kind}, semaine {session.week_index})"
        elif event.session_id:
            text += ", une séance a été ratée"
    return f"L'athlète signale un imprévu : {text}{extra}. Adapte les séances à venir en conséquence."


def _ask(
    repo: Repo,
    garmin: GarminPort,
    llm: LLMProvider,
    event_id: int,
    note: str,
    missed: list[Session] = (),
) -> EventResult:
    """Demande l'ajustement ; toute erreur (Claude, Garmin, plan) laisse l'imprévu enregistré."""
    try:
        proposal_id = request_adjustment(repo, garmin, llm, note, missed=missed)
    except GarminAuthRequired:
        return EventResult(event_id=event_id, proposal_id=None, error="Connexion Garmin requise")
    except GarminRateLimited:
        return EventResult(event_id=event_id, proposal_id=None, error="Garmin limite les requêtes, réessaie plus tard")
    except (LLMError, GarminUnavailable, CoachError) as e:
        return EventResult(event_id=event_id, proposal_id=None, error=str(e) or _DEFAULT_ERROR)
    return EventResult(event_id=event_id, proposal_id=proposal_id, error=None)


def create_event(repo: Repo, garmin: GarminPort, llm: LLMProvider, data: EventInput) -> EventResult:
    """Enregistre l'imprévu sur le cycle actif puis demande l'ajustement à Claude."""
    cycle = _active_cycle(repo)
    if not cycle.plan_accepted:
        raise EventError("Le plan doit être validé")
    event = build_event(repo, cycle, data, garmin.today())
    missed: list[Session] = []
    with repo.transaction() as db:
        if event.session_id is not None:  # fatigue : la séance ratée n'est plus à faire
            s = db.get(Session, event.session_id)
            if s is not None and s.status in ("todo", "exported"):
                s.status = "missed"
                db.add(s)
                db.flush()
                db.expunge(s)  # reste lisible après la transaction
                missed.append(s)
        db.add(event)
        db.flush()
        event_id = event.id
    return _ask(repo, garmin, llm, event_id, event_note(event, missed[0] if missed else None), missed)


def delete_event(repo: Repo, event_id: int) -> None:
    """Supprime l'imprévu ; aucun ajustement (le front propose de recalculer le plan)."""
    with repo.transaction() as db:
        event = db.get(Event, event_id)
        if event is None:
            raise EventError("Imprévu introuvable")
        db.delete(event)


def resume_injury(
    repo: Repo, garmin: GarminPort, llm: LLMProvider, event_id: int, resume_date: date
) -> EventResult:
    """Clôt un arrêt ouvert et demande une reprise progressive à Claude."""
    with repo.transaction() as db:
        event = db.get(Event, event_id)
        if event is None:
            raise EventError("Imprévu introuvable")
        if event.kind != "injury" or event.end_date is not None:
            raise EventError("Cet imprévu n'est pas un arrêt en cours")
        if resume_date < event.start_date:
            raise EventError("La reprise doit être après le début de l'arrêt")
        event.end_date = max(resume_date - timedelta(days=1), event.start_date)
        days = (resume_date - event.start_date).days
        reason = event.note
        db.add(event)
    detail = f" ({reason})" if reason else ""
    duree = "un jour" if days == 1 else f"{days} jours" if days > 1 else "moins d'un jour"
    note = (
        f"Reprise après {duree} d'arrêt{detail} : "
        "reprise progressive, volume et intensité réduits les premières semaines."
    )
    return _ask(repo, garmin, llm, event_id, note)
