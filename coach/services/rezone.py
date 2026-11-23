"""Renvoi à la montre des séances exportées quand les zones de FC changent.

Une séance à venir dont le workout Garmin dépend des zones FC est remplacée (même machinerie
que l'application d'une proposition : upload, planification, puis retrait de l'ancien) dès que
ses bornes bougent d'au moins `RESEND_MIN_BPM` bpm.
"""

import json
from datetime import date

from pydantic import BaseModel

from coach.analysis.zones import HrZoneName, Zones
from coach.export.garmin_workout import session_to_workout_json
from coach.garmin.port import GarminPort
from coach.plan.models import Session
from coach.plan.repo import Repo
from coach.services.garmin_export import mark_for_cleanup, sync_marked, workout_name

RESEND_MIN_BPM = 2
_HR_TARGET_KEY = "heart.rate.zone"


class Rezone(BaseModel):
    resent: int
    failed: list[int]


def _stored_hr(session: Session) -> dict[HrZoneName, tuple[int, int]] | None:
    """Zones FC du dernier envoi ; None pour un export antérieur à leur enregistrement."""
    if session.export_hr_zones_json is None:
        return None
    return {name: (low, high) for name, (low, high) in json.loads(session.export_hr_zones_json).items()}


def _has_hr_target(node: dict | list) -> bool:
    """Le workout (ou une partie) contient-il une cible de FC ?"""
    if isinstance(node, list):
        return any(_has_hr_target(n) for n in node)
    if node.get("workoutTargetTypeKey") == _HR_TARGET_KEY:
        return True
    return any(_has_hr_target(v) for v in node.values() if isinstance(v, (dict, list)))


def needs_resend(session: Session, zones: Zones) -> bool:
    """Le workout envoyé à la montre est-il assez différent de celui des zones actuelles ?"""
    spec, name = session.to_spec(), workout_name(session)
    try:
        current = session_to_workout_json(spec, zones, name=name)
    except ValueError:
        return False  # séance non convertible avec les zones actuelles : on garde l'envoi existant
    stored = _stored_hr(session)
    if stored is None:
        # export ancien : zones inconnues, comparé à un workout sans cible FC
        return _has_hr_target(current)
    exported = Zones(pace=zones.pace, hr=stored, source=zones.source)
    if session_to_workout_json(spec, exported, name=name) == current:
        return False
    shift = max(
        (
            max(abs(stored[z][0] - zones.hr[z][0]), abs(stored[z][1] - zones.hr[z][1]))
            for z in stored.keys() & zones.hr.keys()
        ),
        default=0,
    )
    return shift >= RESEND_MIN_BPM


def resend_for_zones(repo: Repo, garmin: GarminPort, zones: Zones, today: date) -> Rezone:
    """Remplace sur Garmin les séances exportées à venir du cycle actif dont les zones FC ont bougé.

    La séance du jour n'est renvoyée que si aucune activité n'est encore enregistrée aujourd'hui.
    Un échec Garmin laisse la séance en `sync_error` (ancien workout conservé jusqu'à la reprise).
    """
    cycle = repo.active_cycle()
    if cycle is None:
        return Rezone(resent=0, failed=[])
    today_open = not repo.has_activity_on(today)
    candidates = [
        s
        for s in repo.sessions(cycle.id)
        if s.status == "exported"
        and s.scheduled_date is not None
        and (s.scheduled_date > today or (s.scheduled_date == today and today_open))
        and needs_resend(s, zones)
    ]
    ids: list[int] = []
    with repo.transaction() as db:
        for c in candidates:
            s = db.get(Session, c.id)
            if s is None or s.status != "exported":  # changée entre-temps
                continue
            mark_for_cleanup(s, removal=False)
            db.add(s)
            ids.append(s.id)
    failed = sync_marked(repo, garmin, ids, zones)
    return Rezone(resent=len(ids) - len(failed), failed=failed)
