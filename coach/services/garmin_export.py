"""Export, déplacement, retrait et application d'une proposition : seul point d'écriture vers Garmin.

Ordre sûr de remplacement d'une séance exportée : upload du nouveau, planification du nouveau,
puis seulement retrait de l'ancien. Un échec avant le nouveau `schedule` laisse l'ancien en place.

Sortie d'une séance `sync_error` : réessayer, déplacer (nouvelle date dans la semaine, puis même
synchro) ou retirer (nettoie ids actuels et anciens). La synchro des activités n'y touche pas tant
que d'anciens ids restent à nettoyer (voir `compliance._awaiting_cleanup`) : aucun orphelin Garmin.
"""

from datetime import date

from pydantic import TypeAdapter
from sqlmodel import select

from coach.analysis.compliance import hard_session_warnings
from coach.analysis.zones import Zones
from coach.export.garmin_workout import session_to_workout_json
from coach.garmin.port import (
    GarminAuthRequired,
    GarminPort,
    GarminRateLimited,
    GarminUnavailable,
)
from coach.llm.schemas import Change, GoalEstimate
from coach.plan import calendar
from coach.plan.constraints import allowed_days, blocked_periods
from coach.plan.goals import goal_label
from coach.plan.models import ALL_DAYS, Cycle, Goal, Proposal, Session
from coach.plan.repo import Repo
from coach.services import CoachError
from coach.services.context import load_constraints

_GARMIN_ERRORS = (GarminUnavailable, GarminAuthRequired, GarminRateLimited)
_EARLY_ERRORS = (GarminAuthRequired, GarminRateLimited)
_CHANGES = TypeAdapter(list[Change])
_ESTIMATES = TypeAdapter(list[GoalEstimate])
_PENDING_MSG = "Synchronisation Garmin en cours"
_UNAVAILABLE_DAY = "Jour hors de tes disponibilités"


class ExportError(CoachError):
    """Export, déplacement ou application de proposition impossible."""


# --- aides ---------------------------------------------------------------------------------


def _zones(repo: Repo) -> Zones:
    snap = repo.latest_snapshot()
    if snap is None:
        raise ExportError("Synchronise d'abord tes données Garmin")
    return Zones.model_validate_json(snap.zones_json)


def _cycle(repo: Repo, session: Session) -> Cycle:
    with repo.transaction() as db:
        cycle = db.get(Cycle, session.cycle_id)
    if cycle is None:
        raise ExportError("Plan introuvable")
    return cycle


def _get(repo: Repo, session_id: int) -> Session:
    try:
        return repo.session(session_id)
    except KeyError as e:
        raise ExportError("Séance introuvable") from e


def _check_day(repo: Repo, session: Session, d: date) -> None:
    if calendar.week_of(_cycle(repo, session), d) != session.week_index:
        raise ExportError("Le jour choisi doit appartenir à la semaine de la séance")


def _check_not_past(garmin: GarminPort, d: date) -> None:
    if d < garmin.today():
        raise ExportError("Impossible de planifier une séance à une date passée")


def _lower_first(text: str) -> str:
    """« Course sur route… » → « course sur route… » (en milieu de phrase)."""
    return text[:1].lower() + text[1:]


def _warnings(repo: Repo, session: Session, d: date) -> list[str]:
    warnings = hard_session_warnings(session, d, repo.sessions(session.cycle_id))
    cycle = _cycle(repo, session)
    # `today = d` : un arrêt ouvert bloque jusqu'au dimanche de la semaine de `d`
    goals = repo.goals_in(cycle)
    constraints = load_constraints(repo, cycle, d, goals)
    # non bloquant : l'athlète peut vouloir garder une séance (ex. échauffement) le jour d'une course
    warnings += [f"Ce jour-là, tu cours {_lower_first(goal_label(g))}" for g in goals if g.race_date == d]
    if ALL_DAYS[d.weekday()] not in allowed_days(constraints, d):
        warnings.append(_UNAVAILABLE_DAY)
    for start, end, label in blocked_periods(constraints):
        if start <= d <= end:
            warnings.append(f"Pendant ton imprévu : {label}")
    return warnings


def _name(session: Session) -> str:
    return f"S{session.week_index} – {session.title}"


def _upload_and_schedule(
    garmin: GarminPort, session: Session, zones: Zones, d: date, state: dict | None = None
) -> tuple[int, int]:
    """Upload puis planifie ; si la planification échoue, supprime le workout téléversé."""
    workout = session_to_workout_json(session.to_spec(), zones, name=_name(session))
    workout_id = garmin.upload_workout(workout)
    if state is not None:
        state["wrote"] = True
    try:
        schedule_id = garmin.schedule(workout_id, d)
    except Exception:
        try:
            garmin.delete_workout(workout_id)
        except _GARMIN_ERRORS:
            pass  # meilleur effort : on remonte l'erreur d'origine
        raise
    return workout_id, schedule_id


# --- export / déplacement / retrait ---------------------------------------------------------


def check_export(repo: Repo, session_id: int, d: date) -> list[str]:
    """Avertissements d'un export le jour `d`, sans aucune écriture."""
    session = _get(repo, session_id)
    _check_day(repo, session, d)
    return _warnings(repo, session, d)


def export_session(repo: Repo, garmin: GarminPort, session_id: int, d: date) -> list[str]:
    session = _get(repo, session_id)
    if session.status != "todo":
        raise ExportError("Séance déjà exportée : déplace-la plutôt")
    _check_day(repo, session, d)
    _check_not_past(garmin, d)
    zones = _zones(repo)
    warnings = _warnings(repo, session, d)
    workout_id, schedule_id = _upload_and_schedule(garmin, session, zones, d)
    session.status = "exported"
    session.scheduled_date = d
    session.garmin_workout_id = workout_id
    session.garmin_schedule_id = schedule_id
    session.sync_error = None
    repo.update(session)
    return warnings


def move_session(repo: Repo, garmin: GarminPort, session_id: int, d: date) -> list[str]:
    """Déplace une séance exportée ; pour une `sync_error`, change la date puis relance la synchro."""
    session = _get(repo, session_id)
    retrying = session.status == "sync_error"
    if retrying and session.pending_removal:
        raise ExportError("Séance en cours de retrait : retire-la ou réessaie")
    if not retrying and (session.status != "exported" or session.garmin_schedule_id is None):
        raise ExportError("Seule une séance exportée peut être déplacée")
    _check_day(repo, session, d)
    _check_not_past(garmin, d)
    warnings = _warnings(repo, session, d)
    if session.garmin_schedule_id is not None:
        garmin.reschedule(session.garmin_schedule_id, d)
    session.scheduled_date = d
    repo.update(session)
    if retrying and not _sync(repo, garmin, session_id, None, early=True):
        raise ExportError(repo.session(session_id).sync_error or "Synchronisation échouée")
    return warnings


_ID_PAIRS = (
    ("garmin_schedule_id", "garmin_workout_id"),
    ("pending_old_schedule_id", "pending_old_workout_id"),
)


def unschedule_session(repo: Repo, garmin: GarminPort, session_id: int) -> None:
    """Retire du calendrier Garmin (ids actuels et, pour une `sync_error`, anciens ids à nettoyer)."""
    session = _get(repo, session_id)
    if session.status not in ("exported", "sync_error"):
        raise ExportError("Seule une séance exportée peut être retirée du calendrier")
    for schedule_attr, workout_attr in _ID_PAIRS:  # chaque id effacé dès qu'il est traité
        if getattr(session, schedule_attr) is not None:
            garmin.unschedule(getattr(session, schedule_attr))
            setattr(session, schedule_attr, None)
            session = repo.update(session)
        if getattr(session, workout_attr) is not None:
            garmin.delete_workout(getattr(session, workout_attr))
            setattr(session, workout_attr, None)
            session = repo.update(session)
    if session.pending_removal:
        with repo.transaction() as db:
            db.delete(db.get(Session, session_id))
        return
    session.status = "todo"
    session.scheduled_date = None
    session.sync_error = None
    repo.update(session)


# --- synchronisation après remplacement / retrait -----------------------------------------


def _sync(repo: Repo, garmin: GarminPort, session_id: int, zones: Zones | None, *, early: bool) -> bool:
    """Termine la synchro Garmin d'une séance ; True si réussie, sinon la met en `sync_error`.

    `early` : une erreur d'authentification/quota survenue avant toute écriture est propagée.
    """
    session = repo.session(session_id)
    state = {"wrote": False}
    try:
        if not session.pending_removal and session.garmin_schedule_id is None:
            if session.scheduled_date is None:
                raise ExportError("Séance sans date prévue : ré-exporte-la")
            if zones is None:
                zones = _zones(repo)
            session.garmin_workout_id, session.garmin_schedule_id = _upload_and_schedule(
                garmin, session, zones, session.scheduled_date, state
            )
            session = repo.update(session)
        # retrait : les ids actuels éventuels (séance en `sync_error` à la clôture d'un cycle) partent aussi
        for schedule_attr, workout_attr in _ID_PAIRS if session.pending_removal else _ID_PAIRS[1:]:
            if getattr(session, schedule_attr) is not None:
                garmin.unschedule(getattr(session, schedule_attr))
                state["wrote"] = True
                setattr(session, schedule_attr, None)
                session = repo.update(session)
            if getattr(session, workout_attr) is not None:
                garmin.delete_workout(getattr(session, workout_attr))
                state["wrote"] = True
                setattr(session, workout_attr, None)
                session = repo.update(session)
    except (*_GARMIN_ERRORS, ValueError) as e:
        if early and isinstance(e, _EARLY_ERRORS) and not state["wrote"]:
            raise
        session = repo.session(session_id)
        session.status = "sync_error"
        session.sync_error = f"Synchronisation Garmin échouée : {e}"
        repo.update(session)
        return False
    if session.pending_removal:
        with repo.transaction() as db:
            db.delete(db.get(Session, session_id))
    else:
        session.status = "exported"
        session.sync_error = None
        repo.update(session)
    return True


def sync_marked(repo: Repo, garmin: GarminPort, session_ids: list[int], zones: Zones | None) -> list[int]:
    """Synchronise Garmin les séances marquées par `mark_for_cleanup`, après commit.

    Une erreur Garmin laisse la séance en `sync_error` sans interrompre les autres ;
    renvoie les ids des séances restées en `sync_error`.
    """
    return [sid for sid in session_ids if not _sync(repo, garmin, sid, zones, early=False)]


def retry_pending_cleanup(repo: Repo, garmin: GarminPort, today: date) -> list[int]:
    """Relance, quel que soit leur cycle, les séances en `sync_error` qui ont encore quelque chose à
    retirer de la montre (retrait, ou anciens ids d'un remplacement) ; un remplacement dont la nouvelle
    version reste à téléverser à une date passée est laissé à l'athlète. Renvoie les ids encore en erreur."""
    with repo.transaction() as db:
        stmt = select(Session).where(Session.status == "sync_error").order_by(Session.id)
        candidates = list(db.exec(stmt))
    ids = [
        s.id
        for s in candidates
        if s.pending_removal
        or (
            (s.pending_old_schedule_id is not None or s.pending_old_workout_id is not None)
            and (s.garmin_schedule_id is not None or (s.scheduled_date is not None and s.scheduled_date >= today))
        )
    ]
    return sync_marked(repo, garmin, ids, None)


def retry_sync_error(repo: Repo, garmin: GarminPort, session_id: int) -> None:
    """Relance l'étape Garmin qui avait échoué pour une séance en `sync_error`."""
    session = _get(repo, session_id)
    if session.status != "sync_error":
        raise ExportError("Cette séance n'a pas d'erreur de synchronisation")
    if (
        not session.pending_removal
        and session.garmin_schedule_id is None
        and session.scheduled_date is not None
        and session.scheduled_date < garmin.today()
    ):
        raise ExportError("Date passée : retire la séance ou choisis une nouvelle date")
    if not _sync(repo, garmin, session_id, None, early=True):
        raise ExportError(repo.session(session_id).sync_error or "Synchronisation échouée")


# --- propositions -----------------------------------------------------------------------------


def _pending_proposal(repo: Repo, proposal_id: int) -> Proposal:
    with repo.transaction() as db:
        proposal = db.get(Proposal, proposal_id)
    if proposal is None:
        raise ExportError("Proposition introuvable")
    if proposal.status != "pending":
        raise ExportError("Cette proposition n'est plus en attente")
    return proposal


def reject_proposal(repo: Repo, proposal_id: int) -> None:
    with repo.transaction() as db:
        proposal = db.get(Proposal, proposal_id)
        if proposal is None:
            raise ExportError("Proposition introuvable")
        if proposal.status != "pending":
            raise ExportError("Cette proposition n'est plus en attente")
        proposal.status = "rejected"
        db.add(proposal)


def mark_for_cleanup(s: Session, *, removal: bool) -> None:
    """Conserve les ids Garmin actuels à nettoyer ; la séance n'a plus de planification."""
    s.pending_old_workout_id = s.garmin_workout_id
    s.pending_old_schedule_id = s.garmin_schedule_id
    s.garmin_workout_id = None
    s.garmin_schedule_id = None
    s.pending_removal = removal
    s.status = "sync_error"
    s.sync_error = _PENDING_MSG


def _apply_estimates(db, proposal: Proposal) -> None:
    """Temps estimés de la proposition, pour les objectifs à venir dont le temps revient encore à Claude."""
    for estimate in _ESTIMATES.validate_json(proposal.estimates_json):
        g = db.get(Goal, estimate.goal_id)
        if g is not None and g.status == "active" and g.target_source == "claude":
            g.target_time_s = estimate.seconds
            db.add(g)


def apply_proposal(repo: Repo, garmin: GarminPort, proposal_id: int) -> list[int]:
    """Applique la proposition en base (une transaction), puis synchronise Garmin.

    Renvoie les ids des séances passées en `sync_error`.
    """
    changes = _CHANGES.validate_json(_pending_proposal(repo, proposal_id).changes_json)
    # Les zones sont nécessaires dès qu'une séance exportée sera remplacée : on vérifie avant d'écrire.
    zones = None
    for c in changes:
        if c.op == "modify" and _get(repo, c.session_id).status == "exported":
            zones = _zones(repo)
            break
    if zones is not None:  # toutes les conversions avant la moindre écriture
        for c in changes:
            if c.op == "modify" and _get(repo, c.session_id).status == "exported":
                try:
                    session_to_workout_json(c.session, zones, name=c.session.title)
                except ValueError as e:
                    raise ExportError(f"Conversion Garmin impossible : {e}") from e

    to_sync: list[int] = []
    with repo.transaction() as db:
        proposal = db.get(Proposal, proposal_id)
        if proposal is None or proposal.status != "pending":
            raise ExportError("Cette proposition n'est plus en attente")
        cycle: Cycle | None = None
        for c in changes:
            if c.op == "add":
                if cycle is None:
                    cycle = db.exec(
                        select(Cycle).where(Cycle.status == "active").order_by(Cycle.id.desc())
                    ).first()
                    if cycle is None:
                        raise ExportError("Aucun plan en cours")
                db.add(Session.from_spec(c.session, cycle_id=cycle.id))
                continue
            s = db.get(Session, c.session_id)
            if s is None:
                raise ExportError(f"Séance {c.session_id} introuvable")
            if s.status not in ("todo", "exported"):
                raise ExportError(
                    "Séance en erreur de synchronisation : réessaie d'abord"
                    if s.status == "sync_error"
                    else "Séance déjà réalisée ou manquée : l'historique ne peut pas changer"
                )
            if c.op == "modify":
                fresh = Session.from_spec(c.session, cycle_id=s.cycle_id)
                for f in (
                    "week_index", "order", "suggested_day", "chaining_note", "type",
                    "sport", "target_kind", "title", "description", "steps_json",
                ):  # fmt: skip
                    setattr(s, f, getattr(fresh, f))
                s.est_duration_min = s.est_distance_km = None
                if s.status == "exported":
                    mark_for_cleanup(s, removal=False)
                    to_sync.append(s.id)
                db.add(s)
            elif s.status == "todo":
                db.delete(s)
            else:  # exported
                mark_for_cleanup(s, removal=True)
                to_sync.append(s.id)
                db.add(s)
        _apply_estimates(db, proposal)
        proposal.status = "accepted"
        db.add(proposal)

    return sync_marked(repo, garmin, to_sync, zones)
