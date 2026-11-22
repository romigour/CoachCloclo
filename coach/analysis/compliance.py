"""Séances manquées, avertissement 48 h, types d'activité par sport (le rattachement est manuel)."""

from datetime import date, timedelta

from coach.llm.schemas import HARD_TYPES
from coach.plan.calendar import week_monday
from coach.plan.models import Cycle, Session

RUNNING_TYPES = {"running", "trail_running", "treadmill_running", "track_running"}
CYCLING_TYPES = {"cycling", "road_biking", "indoor_cycling", "virtual_ride", "gravel_cycling", "mountain_biking"}


def _scheduled(s: Session) -> bool:
    """Séance planifiée sur Garmin, y compris en erreur de synchro (hors retrait en cours)."""
    return s.status == "exported" or (
        s.status == "sync_error" and not s.pending_removal and s.scheduled_date is not None
    )


def _awaiting_cleanup(s: Session) -> bool:
    """D'anciens ids Garmin restent à nettoyer : seule une action explicite (réessayer, déplacer,
    retirer) peut le faire, la synchro n'écrit jamais sur Garmin. La séance reste donc en
    `sync_error` (jamais manquée) tant que le nettoyage n'est pas fait."""
    return s.status == "sync_error" and (
        s.pending_old_workout_id is not None or s.pending_old_schedule_id is not None
    )


def activity_types_for(sport: str) -> set[str]:
    """Types d'activité Garmin correspondant au sport d'une séance (« run » ou « bike »)."""
    return CYCLING_TYPES if sport == "bike" else RUNNING_TYPES


def mark_missed(sessions: list[Session], cycle: Cycle, today: date) -> list[int]:
    """Ids des séances todo/exported dont la semaine est entièrement passée."""
    return [
        s.id
        for s in sessions
        if (s.status == "todo" or _scheduled(s))
        and not _awaiting_cleanup(s)
        and week_monday(cycle, s.week_index) + timedelta(days=6) < today
    ]


def hard_session_warnings(session: Session, target: date, others: list[Session]) -> list[str]:
    """Avertit si une séance dure est placée à moins de 48 h d'une autre séance dure planifiée."""
    if session.type not in HARD_TYPES:
        return []
    return [
        f"Séance dure à moins de 48 h de « {o.title} » ({o.scheduled_date.isoformat()})"
        for o in others
        if o.id != session.id
        and _scheduled(o)
        and o.type in HARD_TYPES
        and o.scheduled_date is not None
        and abs((o.scheduled_date - target).days) < 2
    ]
