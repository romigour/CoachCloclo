"""Objectifs de course : création, ajout, modification et retrait, et leurs effets sur le cycle actif."""

import json
import re
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from sqlmodel import Session as DbSession
from sqlmodel import select

from coach.analysis.gpx import GpxSummary, analyze_gpx
from coach.config import data_dir
from coach.garmin.port import GarminPort
from coach.llm.prompts import NEW_GOAL_ID, fmt_duration
from coach.llm.provider import LLMProvider
from coach.llm.schemas import Weekday
from coach.plan import calendar
from coach.plan.goals import cycle_end, classify_change, gap_conflict, goal_label
from coach.plan.models import ALL_DAYS, PRIORITY_LABELS, Cycle, Goal, Proposal, Session
from coach.plan.repo import Repo
from coach.services import CoachError
from coach.services.context import refresh_snapshot
from coach.services.garmin_export import mark_for_cleanup, sync_marked

Priority = Literal["principal", "secondaire", "plaisir"]

MIN_DAYS_BEFORE_RACE = 14
_NOT_FOUND = "Objectif introuvable ou archivé"
_NO_PLAN = "Aucun plan en cours"
_NOTE_END = "Adapte les séances à venir en conséquence."
MIN_PACE_S_KM = 150
TOO_FAST = "Temps visé invraisemblable : allure moyenne plus rapide que 2:30/km (format attendu h:mm, ex. 3:45)"
_TARGET_TIME = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$")


class GoalError(CoachError):
    """Objectif invalide."""


class GoalInput(BaseModel):
    """Nouvel objectif ; les réglages du plan ne servent (et ne sont obligatoires) que sans cycle actif."""

    type: Literal["route", "trail"]
    distance_km: float = Field(gt=0)
    d_plus_m: int = Field(ge=0)
    race_date: date
    sessions_per_week: int | None = Field(None, ge=2, le=7)
    gpx: bytes | None = None
    target_time_s: int | None = Field(None, gt=0)
    available_days: list[Weekday] = Field(default_factory=lambda: list(ALL_DAYS))
    long_run_day: Weekday | None = None
    include_bike: bool = False
    priority: Priority = "principal"


class GoalUpdate(BaseModel):
    race_date: date | None = None
    target_time: str | None = None
    priority: Priority | None = None


class ChangeResult(BaseModel):
    """Effet d'un changement d'objectif sur le plan : proposition d'ajustement ou génération à refaire."""

    proposal_id: int | None
    needs_generation: bool


def normalize_days(days: list[str]) -> list[str]:
    """Jours sans doublon, dans l'ordre de la semaine."""
    return [d for d in ALL_DAYS if d in set(days)]


def check_availability(available_days: list[str], long_run_day: str | None, sessions_per_week: int) -> None:
    """Refuse des jours possibles incompatibles avec le nombre de séances ou la sortie longue."""
    if len(available_days) < sessions_per_week:
        raise GoalError(
            f"Il faut au moins {sessions_per_week} jours possibles pour {sessions_per_week} séances par semaine"
        )
    if long_run_day is not None and long_run_day not in available_days:
        raise GoalError("Le jour de la sortie longue doit faire partie des jours possibles")


def parse_target_time(text: str) -> int:
    """« h:mm » ou « h:mm:ss » en secondes (même règle que le front)."""
    m = _TARGET_TIME.match(text.strip())
    if m:
        h, mn, sec = int(m[1]), int(m[2]), int(m[3] or 0)
        total = h * 3600 + mn * 60 + sec
        if mn <= 59 and sec <= 59 and total > 0:
            return total
    raise GoalError("Temps visé invalide : format attendu h:mm, ex. 3:45")


def check_target_time(seconds: int, distance_km: float) -> None:
    """Refuse un temps visé à une allure moyenne invraisemblable."""
    if seconds < MIN_PACE_S_KM * distance_km:
        raise GoalError(TOO_FAST)


def _get_goal(repo: Repo, goal_id: int) -> Goal:
    with repo.transaction() as db:
        goal = db.get(Goal, goal_id)
    if goal is None or goal.status != "active":
        raise GoalError(_NOT_FOUND)
    return goal


def _describe(goal: Goal) -> str:
    """« Trail de 42 km du 07/02/2027 (Principal) »."""
    return f"{goal_label(goal)} du {goal.race_date:%d/%m/%Y} ({PRIORITY_LABELS[goal.priority]})"


# --- enregistrement commun ------------------------------------------------------------------


def _removed_after(sessions: list[Session], cycle: Cycle, n: int, race_date: date) -> set[int]:
    """Séances à venir au-delà de la dernière semaine `n` ou après `race_date` : à retirer."""
    return {
        s.id
        for s in sessions
        if s.status in ("todo", "exported")
        and (
            s.week_index > n
            or (s.scheduled_date or calendar.suggested_date(cycle, s.week_index, s.suggested_day)) > race_date
        )
    }


def _save_change(
    repo: Repo,
    garmin: GarminPort,
    zones,
    adj,
    removed_ids: set[int],
    apply,
) -> int:
    """Enregistre en une transaction la modification (`apply(db)`), les retraits et la proposition,
    puis retire de la montre les séances exportées ; renvoie l'id de la proposition."""
    from coach.services.adjust import save_proposal  # import tardif : adjust importe race_strategy, qui importe ce module

    with repo.transaction() as db:
        apply(db)
        to_clean = _remove_sessions(db, removed_ids)
        proposal_id = save_proposal(db, adj)
    # Retire les séances de la montre ; un échec Garmin les laisse en `sync_error` (à relancer).
    sync_marked(repo, garmin, to_clean, zones)
    return proposal_id


def _remove_sessions(db: DbSession, removed_ids: set[int]) -> list[int]:
    """Supprime les séances `todo` et marque pour retrait les exportées ; renvoie ces dernières (à
    retirer de la montre après commit)."""
    to_clean: list[int] = []
    for sid in sorted(removed_ids):
        s = db.get(Session, sid)
        if s is None:
            continue
        if s.status == "todo":
            db.delete(s)
        elif s.status == "exported":
            mark_for_cleanup(s, removal=True)
            to_clean.append(s.id)
            db.add(s)
    return to_clean


def stale_pending(db: DbSession) -> None:
    """Passe les propositions en attente à `stale` (le plan qu'elles ajustaient a changé)."""
    for p in db.exec(select(Proposal).where(Proposal.status == "pending")).all():
        p.status = "stale"
        db.add(p)


def _active_in(db: DbSession, cycle_id: int) -> Cycle:
    c = db.get(Cycle, cycle_id)
    if c is None or c.status != "active":
        raise GoalError(_NO_PLAN)
    return c


def _close_cycle(db: DbSession, c: Cycle) -> list[int]:
    """Clôt le cycle : séances `todo` supprimées, exportées marquées pour retrait, propositions périmées.

    Renvoie les ids des séances à retirer de la montre (après commit).
    """
    c.status = "done"
    db.add(c)
    to_clean: list[int] = []
    for s in db.exec(select(Session).where(Session.cycle_id == c.id)).all():
        if s.status == "todo":
            db.delete(s)
        elif s.status == "exported":
            mark_for_cleanup(s, removal=True)
            to_clean.append(s.id)
            db.add(s)
    stale_pending(db)
    return to_clean


def _reshape(
    repo: Repo,
    garmin: GarminPort,
    llm: LLMProvider,
    *,
    before: Goal | None,
    after: Goal | None,
    note: str,
    write: Callable[[DbSession], Goal],
) -> tuple[Goal, ChangeResult]:
    """Applique un changement d'objectif (`before` → `after`, l'un des deux absent pour un ajout ou un
    retrait) et ses effets sur le cycle actif ; `write(db)` enregistre l'objectif.

    Rien n'est enregistré si la règle d'écart, Claude ou le retrait du Jour J sur Garmin échoue.
    """
    from coach.services.adjust import ask_adjustment  # import tardif : adjust importe race_strategy
    from coach.services.race_strategy import withdraw_race  # import tardif : race_strategy importe ce module

    # 1. objectifs actifs après le changement
    others = [g for g in repo.upcoming_goals() if before is None or g.id != before.id]
    if after is not None and (conflict := gap_conflict(after, others)):
        raise GoalError(conflict)
    goals_after = sorted(others + ([after] if after is not None else []), key=lambda g: g.race_date)

    def withdraw() -> None:
        # retrait : le Jour J exporté quitte la montre avant toute écriture ; une erreur Garmin remonte
        if after is None and before is not None:
            strategy = repo.race_strategy(before.id)
            if strategy is not None and strategy.garmin_workout_id is not None:
                withdraw_race(repo, garmin, before.id)

    cycle = repo.active_cycle()
    if cycle is None:  # pas de plan en cours : seul l'objectif change
        withdraw()
        with repo.transaction() as db:
            saved = write(db)
        return saved, ChangeResult(proposal_id=None, needs_generation=False)

    # 2. nouvelle fin du cycle et nature du changement
    new_end = cycle_end([g for g in goals_after if g.race_date >= cycle.plan_start])
    touched = (before is not None and cycle.plan_start <= before.race_date <= cycle.end_date) or (
        after is not None and new_end is not None and cycle.plan_start <= after.race_date <= new_end
    )
    kind = classify_change(
        plan_accepted=cycle.plan_accepted, old_end=cycle.end_date, new_end=new_end, touched_in_cycle=touched
    )
    saved: dict[str, Goal] = {}

    # 3. effets selon la nature du changement
    if kind in ("adjust", "shrink"):
        edited_cycle = cycle.model_copy(update={"end_date": new_end})
        _, zones = refresh_snapshot(repo, garmin)
        sessions = repo.sessions(cycle.id)
        removed_ids = _removed_after(sessions, cycle, calendar.n_weeks(cycle.plan_start, new_end), new_end)
        adj = ask_adjustment(
            repo, garmin, llm, edited_cycle, zones, [s for s in sessions if s.id not in removed_ids],
            garmin.today(),
            change_note=note,
            goals=[g for g in goals_after if cycle.plan_start <= g.race_date <= new_end],
            horizon=[g for g in goals_after if g.race_date > new_end],
        )
        withdraw()

        def apply(db: DbSession) -> None:
            c = _active_in(db, cycle.id)
            saved["goal"] = write(db)
            c.end_date = new_end
            db.add(c)
            if before is None:  # ajout : l'estimation du nouvel objectif porte l'id provisoire
                for estimate in adj.estimated_times:
                    if estimate.goal_id == NEW_GOAL_ID:
                        estimate.goal_id = saved["goal"].id

        proposal_id = _save_change(repo, garmin, zones, adj, removed_ids, apply)
        return saved["goal"], ChangeResult(proposal_id=proposal_id, needs_generation=False)

    removed_ids: set[int] = set()
    if kind in ("regenerate", "draft") and new_end < cycle.end_date:
        # fin avancée : séances au-delà retirées comme pour un report de date
        removed_ids = _removed_after(
            repo.sessions(cycle.id), cycle, calendar.n_weeks(cycle.plan_start, new_end), new_end
        )
    withdraw()
    to_clean: list[int] = []
    with repo.transaction() as db:
        c = _active_in(db, cycle.id)
        saved["goal"] = write(db)
        if kind in ("regenerate", "draft"):
            # les autres séances restent affichées jusqu'à « Générer » ; le brouillon est périmé
            c.end_date = new_end
            c.needs_generation = True
            c.plan_accepted = False
            db.add(c)
            to_clean = _remove_sessions(db, removed_ids)
            stale_pending(db)
        elif kind == "close":
            to_clean = _close_cycle(db, c)
    if to_clean:
        sync_marked(repo, garmin, to_clean, None)  # un retrait n'a pas besoin des zones
    return saved["goal"], ChangeResult(proposal_id=None, needs_generation=kind in ("regenerate", "draft"))


# --- opérations -------------------------------------------------------------------------------


def _new_goal(data: GoalInput, summary: GpxSummary | None, cycle: Cycle) -> Goal:
    d_plus = data.d_plus_m
    if summary is not None and summary.d_plus_m is not None and d_plus == 0:
        d_plus = summary.d_plus_m
    return Goal(
        type=data.type,
        distance_km=data.distance_km,
        d_plus_m=d_plus,
        race_date=data.race_date,
        priority=data.priority,
        target_time_s=data.target_time_s,
        target_source="user" if data.target_time_s else "claude",
        gpx_summary_json=summary.model_dump_json() if summary is not None else None,
        # champs de plan hérités (colonnes obligatoires) : copie du cycle, plus lus
        sessions_per_week=cycle.sessions_per_week,
        plan_start=cycle.plan_start,
        available_days_json=cycle.available_days_json,
        long_run_day=cycle.long_run_day,
        include_bike=cycle.include_bike,
    )


def _insert(db: DbSession, goal: Goal, gpx: bytes | None, written: list[Path]) -> Goal:
    """Ajoute l'objectif et enregistre son GPX (chemin noté dans `written` pour l'annuler en cas d'échec)."""
    goal = Goal(**goal.model_dump())  # copie neuve : `goal` a pu être transmis à Claude
    db.add(goal)
    db.flush()  # obtient l'id
    if gpx is not None and goal.gpx_summary_json is not None:
        path = data_dir() / "gpx" / f"{goal.id}.gpx"
        path.parent.mkdir(parents=True, exist_ok=True)
        written.append(path)
        path.write_bytes(gpx)
        goal.gpx_path = str(path)
        db.add(goal)
    return goal


def _create_first(repo: Repo, garmin: GarminPort, data: GoalInput, summary: GpxSummary | None) -> Goal:
    """Sans cycle actif : crée le cycle avec les réglages du plan et son premier objectif."""
    today = garmin.today()
    if data.sessions_per_week is None:
        raise GoalError("Indique le nombre de séances par semaine")
    if data.race_date - today < timedelta(days=MIN_DAYS_BEFORE_RACE):
        raise GoalError("La course doit être dans au moins 14 jours")
    available_days = normalize_days(data.available_days)
    check_availability(available_days, data.long_run_day, data.sessions_per_week)
    cycle = Cycle(
        plan_start=calendar.plan_start(today),
        end_date=data.race_date,
        sessions_per_week=data.sessions_per_week,
        available_days_json=json.dumps(available_days),
        long_run_day=data.long_run_day,
        include_bike=data.include_bike,
        needs_generation=True,
    )
    written: list[Path] = []
    try:
        with repo.transaction() as db:
            db.add(cycle)
            goal = _insert(db, _new_goal(data, summary, cycle), data.gpx, written)
    except BaseException:
        for path in written:
            path.unlink(missing_ok=True)
        raise
    return goal


def add_goal(repo: Repo, garmin: GarminPort, llm: LLMProvider, data: GoalInput) -> tuple[Goal, ChangeResult]:
    """Ajoute un objectif : crée le cycle s'il n'y en a pas, sinon l'intègre au cycle actif."""
    if data.target_time_s is not None:
        check_target_time(data.target_time_s, data.distance_km)
    summary = analyze_gpx(data.gpx) if data.gpx is not None else None
    cycle = repo.active_cycle()
    if cycle is None:
        goal = _create_first(repo, garmin, data, summary)
        return goal, ChangeResult(proposal_id=None, needs_generation=True)
    if data.race_date <= garmin.today():
        raise GoalError("La course doit être après aujourd'hui")
    new = _new_goal(data, summary, cycle)
    written: list[Path] = []
    try:
        return _reshape(
            repo, garmin, llm,
            before=None,
            after=new,
            note=f"L'athlète a ajouté l'objectif {_describe(new)}. {_NOTE_END}",
            write=lambda db: _insert(db, new, data.gpx, written),
        )
    except BaseException:
        for path in written:
            path.unlink(missing_ok=True)
        raise


def _write_goal(goal_id: int, update: dict) -> Callable[[DbSession], Goal]:
    def write(db: DbSession) -> Goal:
        g = db.get(Goal, goal_id)
        if g is None or g.status != "active":
            raise GoalError(_NOT_FOUND)
        for key, value in update.items():
            setattr(g, key, value)
        db.add(g)
        return g

    return write


def update_goal(
    repo: Repo, garmin: GarminPort, llm: LLMProvider, goal_id: int, data: GoalUpdate
) -> tuple[Goal, ChangeResult]:
    """Modifie la date, le temps visé et/ou la priorité d'un objectif à venir et adapte le cycle.

    Rien n'est enregistré si Claude échoue. Renvoie l'objectif enregistré et l'effet sur le plan.
    """
    goal = _get_goal(repo, goal_id)
    today = garmin.today()
    update: dict = {}
    notes: list[str] = []
    if data.race_date is not None and data.race_date != goal.race_date:
        if data.race_date <= today:
            raise GoalError("La course doit être après aujourd'hui")
        update["race_date"] = data.race_date
        notes.append(f"course déplacée du {goal.race_date:%d/%m/%Y} au {data.race_date:%d/%m/%Y}")
    if data.target_time is not None:
        seconds = parse_target_time(data.target_time)
        check_target_time(seconds, goal.distance_km)
        if seconds != goal.target_time_s:
            update |= {"target_time_s": seconds, "target_source": "user"}
            before = (
                f" au lieu de {fmt_duration(goal.target_time_s)}" if goal.target_time_s is not None
                else ", aucun auparavant"
            )
            notes.append(f"temps visé {fmt_duration(seconds)}{before}")
    if data.priority is not None and data.priority != goal.priority:
        update["priority"] = data.priority
        notes.append(f"priorité {PRIORITY_LABELS[data.priority]} au lieu de {PRIORITY_LABELS[goal.priority]}")
    if not update:
        raise GoalError("Aucune modification")
    return _reshape(
        repo, garmin, llm,
        before=goal,
        after=goal.model_copy(update=update),
        note=f"L'athlète a modifié l'objectif {_describe(goal)} : {' ; '.join(notes)}. {_NOTE_END}",
        write=_write_goal(goal_id, update),
    )


def remove_goal(repo: Repo, garmin: GarminPort, llm: LLMProvider, goal_id: int) -> ChangeResult:
    """Retire un objectif (`archived`) et adapte le cycle ; retirer le dernier objectif clôt le cycle."""
    goal = _get_goal(repo, goal_id)
    _, result = _reshape(
        repo, garmin, llm,
        before=goal,
        after=None,
        note=f"L'athlète a retiré l'objectif {_describe(goal)}. {_NOTE_END}",
        write=_write_goal(goal_id, {"status": "archived"}),
    )
    return result
