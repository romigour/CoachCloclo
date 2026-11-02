"""Rattachement des activités aux séances, séances manquées, avertissement 48 h."""

from datetime import date, timedelta

from coach.llm.schemas import HARD_TYPES, RepeatSpec
from coach.plan.calendar import week_monday
from coach.plan.models import Activity, Goal, Session

RUNNING_TYPES = {"running", "trail_running", "treadmill_running", "track_running"}
CYCLING_TYPES = {"cycling", "road_biking", "indoor_cycling", "virtual_ride", "gravel_cycling", "mountain_biking"}
_PACE_S_PER_KM = 360  # allure supposée pour convertir une distance en durée
_DURATION_TOLERANCE = 0.3  # écart de durée accepté pour un rattachement automatique


def estimate_duration_min(session: Session) -> float:
    """Durée estimée (min) : somme des étapes (répétitions multipliées), distance à 360 s/km."""
    total_s = 0.0
    for step in session.to_spec().steps:
        reps, inner = (step.repeat, step.steps) if isinstance(step, RepeatSpec) else (1, [step])
        for s in inner:
            total_s += reps * (s.duration_s if s.duration_s is not None else s.distance_m * _PACE_S_PER_KM / 1000)
    return total_s / 60


def _expected_min(session: Session) -> float:
    if session.est_duration_min is not None:
        return session.est_duration_min
    return estimate_duration_min(session)


def _scheduled(s: Session) -> bool:
    """Séance planifiée sur Garmin, y compris en erreur de synchro (hors retrait en cours)."""
    return s.status == "exported" or (
        s.status == "sync_error" and not s.pending_removal and s.scheduled_date is not None
    )


def _awaiting_cleanup(s: Session) -> bool:
    """D'anciens ids Garmin restent à nettoyer : seule une action explicite (réessayer, déplacer,
    retirer) peut le faire, la synchro n'écrit jamais sur Garmin. La séance reste donc en
    `sync_error` (ni rattachée ni manquée) tant que le nettoyage n'est pas fait."""
    return s.status == "sync_error" and (
        s.pending_old_workout_id is not None or s.pending_old_schedule_id is not None
    )


def activity_types_for(sport: str) -> set[str]:
    """Types d'activité Garmin correspondant au sport d'une séance (« run » ou « bike »)."""
    return CYCLING_TYPES if sport == "bike" else RUNNING_TYPES


def match_activities(sessions: list[Session], activities: list[Activity]) -> list[tuple[int, int]]:
    """Paires (session_id, activity_id) ; aucune écriture.

    Seules les séances planifiées sur Garmin sont rattachées automatiquement : course à ±1 jour de
    la date prévue et durée à ±30 % de la durée prévue, dans le sport de la séance. Une séance non planifiée (`todo`) ne se
    rattache qu'à la main, tout comme une activité détachée à la main."""
    free = [
        a
        for a in activities
        if a.session_id is None
        and a.match_source != "manual"
        and a.duration_s is not None
    ]
    pairs: list[tuple[int, int]] = []

    for s in (x for x in sessions if _scheduled(x) and x.scheduled_date is not None and not _awaiting_cleanup(x)):
        exp = _expected_min(s)
        cands = [
            a
            for a in free
            if a.type_key in activity_types_for(s.sport)
            and abs((a.date - s.scheduled_date).days) <= 1
            and abs(a.duration_s / 60 - exp) <= _DURATION_TOLERANCE * exp
        ]
        if not cands:
            continue
        best = min(cands, key=lambda a: (abs((a.date - s.scheduled_date).days), abs(a.duration_s / 60 - exp)))
        free.remove(best)
        pairs.append((s.id, best.id))

    return pairs


def mark_missed(sessions: list[Session], goal: Goal, today: date) -> list[int]:
    """Ids des séances todo/exported dont la semaine est entièrement passée."""
    return [
        s.id
        for s in sessions
        if (s.status == "todo" or _scheduled(s))
        and not _awaiting_cleanup(s)
        and week_monday(goal, s.week_index) + timedelta(days=6) < today
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
