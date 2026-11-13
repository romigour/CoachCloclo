"""Objectif de course et génération du plan."""

import json
import re
from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, Field
from sqlmodel import select

from coach.analysis.gpx import GpxSummary, analyze_gpx, summary_to_text
from coach.config import data_dir
from coach.garmin.port import GarminPort
from coach.llm.client import ask_structured
from coach.llm.prompts import SYSTEM_PROMPT, _main_goal, build_generation_prompt, fmt_duration
from coach.llm.provider import LLMProvider
from coach.llm.schemas import PlanResponse, Weekday, validate_plan
from coach.plan import calendar
from coach.plan.constraints import constraint_errors, planned_from_plan
from coach.plan.models import ALL_DAYS, Cycle, Goal, Session
from coach.plan.repo import Repo
from coach.services import CoachError
from coach.services.context import load_constraints, recent_history, refresh_snapshot
from coach.services.garmin_export import mark_for_cleanup, sync_marked

MIN_DAYS_BEFORE_RACE = 14
_NOT_FOUND = "Objectif introuvable ou archivé"
_NO_PLAN = "Aucun plan en cours"
MIN_PACE_S_KM = 150
TOO_FAST = "Temps visé invraisemblable : allure moyenne plus rapide que 2:30/km (format attendu h:mm, ex. 3:45)"
_TARGET_TIME = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$")


class GoalError(CoachError):
    """Objectif invalide."""


class GoalInput(BaseModel):
    type: Literal["route", "trail"]
    distance_km: float = Field(gt=0)
    d_plus_m: int = Field(ge=0)
    race_date: date
    sessions_per_week: int = Field(ge=2, le=7)
    gpx: bytes | None = None
    target_time_s: int | None = Field(None, gt=0)
    available_days: list[Weekday] = Field(default_factory=lambda: list(ALL_DAYS))
    long_run_day: Weekday | None = None
    include_bike: bool = False
    priority: Literal["principal", "secondaire", "plaisir"] = "principal"


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


def create_goal(repo: Repo, garmin: GarminPort, data: GoalInput) -> Goal:
    """Crée le cycle actif et son objectif.

    Le cycle actif précédent passe `done` : ses objectifs sont archivés et ses séances `todo` supprimées.
    """
    today = garmin.today()
    if data.race_date - today < timedelta(days=MIN_DAYS_BEFORE_RACE):
        raise GoalError("La course doit être dans au moins 14 jours")
    if data.target_time_s is not None:
        check_target_time(data.target_time_s, data.distance_km)
    available_days = normalize_days(data.available_days)
    check_availability(available_days, data.long_run_day, data.sessions_per_week)
    summary = analyze_gpx(data.gpx) if data.gpx is not None else None
    d_plus = data.d_plus_m
    if summary is not None and summary.d_plus_m is not None and d_plus == 0:
        d_plus = summary.d_plus_m

    cycle = Cycle(
        plan_start=calendar.plan_start(today),
        end_date=data.race_date,
        sessions_per_week=data.sessions_per_week,
        available_days_json=json.dumps(available_days),
        long_run_day=data.long_run_day,
        include_bike=data.include_bike,
    )
    goal = Goal(
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
    path = None
    try:
        with repo.transaction() as db:
            for old in db.exec(select(Cycle).where(Cycle.status == "active")).all():
                old.status = "done"
                db.add(old)
                in_old = select(Goal).where(
                    Goal.status == "active", Goal.race_date >= old.plan_start, Goal.race_date <= old.end_date
                )
                for g in db.exec(in_old).all():
                    g.status = "archived"
                    db.add(g)
                todo = select(Session).where(Session.cycle_id == old.id, Session.status == "todo")
                for s in db.exec(todo).all():
                    db.delete(s)
            db.add(cycle)
            db.add(goal)
            db.flush()  # obtient les ids
            if summary is not None:
                path = data_dir() / "gpx" / f"{goal.id}.gpx"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data.gpx)
                goal.gpx_path = str(path)
    except BaseException:
        if path is not None:
            path.unlink(missing_ok=True)
        raise
    return goal


def _get_goal(repo: Repo, goal_id: int) -> Goal:
    with repo.transaction() as db:
        goal = db.get(Goal, goal_id)
    if goal is None or goal.status != "active":
        raise GoalError(_NOT_FOUND)
    return goal


def _active_cycle(repo: Repo) -> Cycle:
    cycle = repo.active_cycle()
    if cycle is None:
        raise GoalError(_NO_PLAN)
    return cycle


def _gpx_texts(goals: list[Goal]) -> list[str]:
    return [
        summary_to_text(GpxSummary.model_validate_json(g.gpx_summary_json)) for g in goals if g.gpx_summary_json
    ]


def generate_plan(repo: Repo, garmin: GarminPort, llm: LLMProvider) -> PlanResponse:
    """Génère le plan du cycle actif avec Claude ; remplace le brouillon `todo` précédent."""
    cycle = _active_cycle(repo)
    goals = repo.goals_in(cycle)
    if not goals:
        raise GoalError(_NOT_FOUND)
    horizon = repo.horizon_goals(cycle)
    main = _main_goal(goals)
    _, zones = refresh_snapshot(repo, garmin)
    n = calendar.n_weeks(cycle.plan_start, cycle.end_date)
    from coach.services.race_strategy import race_line_for_prompt  # import tardif : race_strategy importe ce module

    today = garmin.today()
    constraints = load_constraints(repo, cycle, today)
    race_texts = [t for g in goals if (t := race_line_for_prompt(repo, g, today))]
    prompt = build_generation_prompt(
        cycle, goals, horizon, zones, recent_history(garmin), n, _gpx_texts(goals), today=today,
        race_texts=race_texts, constraints=constraints,
    )
    pace_available = zones.pace is not None
    estimate_min_s = round(MIN_PACE_S_KM * main.distance_km) if main.target_source == "claude" else None
    plan = ask_structured(
        llm,
        SYSTEM_PROMPT,
        prompt,
        PlanResponse,
        validate=lambda p: validate_plan(
            p, n_weeks=n, sessions_per_week=cycle.sessions_per_week,
            pace_available=pace_available, estimate_min_s=estimate_min_s,
        )
        + constraint_errors(planned_from_plan(cycle, p), constraints),
    )
    with repo.transaction() as db:
        todo = select(Session).where(Session.cycle_id == cycle.id, Session.status == "todo")
        for s in db.exec(todo).all():
            db.delete(s)
        for week in plan.weeks:
            for spec in week.sessions:
                db.add(Session.from_spec(spec, cycle.id))
        c = db.get(Cycle, cycle.id)
        if c is None or c.status != "active":
            raise GoalError(_NO_PLAN)
        c.plan_accepted = False
        c.needs_generation = False
        db.add(c)
        g = db.get(Goal, main.id)
        if g is not None and g.target_source == "claude":
            g.target_time_s = plan.estimated_time_s
            db.add(g)
    return plan


class GoalUpdate(BaseModel):
    race_date: date | None = None
    target_time: str | None = None


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
    from coach.services.adjust import save_proposal  # import tardif : cycle via race_strategy

    to_clean: list[int] = []
    with repo.transaction() as db:
        apply(db)
        for sid in removed_ids:
            s = db.get(Session, sid)
            if s is None:
                continue
            if s.status == "todo":
                db.delete(s)
            elif s.status == "exported":
                mark_for_cleanup(s, removal=True)
                to_clean.append(s.id)
                db.add(s)
        proposal_id = save_proposal(db, adj)
    # Retire les séances de la montre ; un échec Garmin les laisse en `sync_error` (à relancer).
    sync_marked(repo, garmin, sorted(to_clean), zones)
    return proposal_id


def update_goal(
    repo: Repo, garmin: GarminPort, llm: LLMProvider, goal_id: int, data: GoalUpdate
) -> tuple[Goal, int]:
    """Modifie la date et/ou le temps visé d'un objectif en cours et demande l'ajustement à Claude.

    La fin du cycle suit la date de course (un seul objectif par cycle à ce stade).
    Rien n'est enregistré si Claude échoue. Renvoie l'objectif enregistré et l'id de la proposition.
    """
    from coach.services.adjust import ask_adjustment  # import tardif : cycle via race_strategy

    goal = _get_goal(repo, goal_id)
    cycle = _active_cycle(repo)
    if not cycle.plan_accepted:
        raise GoalError("Le plan de l'objectif doit être validé avant de le modifier")
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
    if not update:
        raise GoalError("Aucune modification")
    edited = goal.model_copy(update=update)
    edited_cycle = cycle.model_copy(update={"end_date": edited.race_date}) if "race_date" in update else cycle

    _, zones = refresh_snapshot(repo, garmin)
    n = calendar.n_weeks(cycle.plan_start, edited_cycle.end_date)
    sessions = repo.sessions(cycle.id)
    removed_ids = _removed_after(sessions, cycle, n, edited_cycle.end_date)
    note = f"L'athlète a modifié son objectif : {' ; '.join(notes)}. Adapte les séances à venir en conséquence."
    # l'objectif modifié n'est pas encore enregistré : on le transmet à la place de celui en base
    goals = [edited if g.id == goal.id else g for g in repo.goals_in(cycle)]
    adj = ask_adjustment(
        repo, garmin, llm, edited_cycle, zones, [s for s in sessions if s.id not in removed_ids], today,
        change_note=note, goals=goals,
    )
    saved: dict[str, Goal] = {}

    def apply(db) -> None:
        g = db.get(Goal, goal_id)
        c = db.get(Cycle, cycle.id)
        if g is None or g.status != "active" or c is None or c.status != "active":
            raise GoalError(_NOT_FOUND)
        for key, value in update.items():
            setattr(g, key, value)
        db.add(g)
        c.end_date = edited_cycle.end_date
        db.add(c)
        saved["goal"] = g

    proposal_id = _save_change(repo, garmin, zones, adj, removed_ids, apply)
    return saved["goal"], proposal_id


class PlanSettingsUpdate(BaseModel):
    available_days: list[Weekday] | None = None
    long_run_day: Weekday | Literal[""] | None = None  # "" : plus de jour imposé
    include_bike: bool | None = None


def update_plan_settings(
    repo: Repo, garmin: GarminPort, llm: LLMProvider, data: PlanSettingsUpdate
) -> tuple[Cycle, int]:
    """Modifie les disponibilités du cycle actif et demande l'ajustement à Claude.

    Rien n'est enregistré si Claude échoue. Renvoie le cycle enregistré et l'id de la proposition.
    """
    from coach.services.adjust import ask_adjustment  # import tardif : cycle via race_strategy

    cycle = _active_cycle(repo)
    if not cycle.plan_accepted:
        raise GoalError("Le plan de l'objectif doit être validé avant de le modifier")
    today = garmin.today()
    update: dict = {}
    notes: list[str] = []
    available_days = cycle.available_days()
    if data.available_days is not None:
        days = normalize_days(data.available_days)
        if days != available_days:
            available_days = days
            update["available_days_json"] = json.dumps(days)
            notes.append(f"jours possibles : {', '.join(days)}")
    long_run_day = cycle.long_run_day
    if data.long_run_day is not None:
        new_day = data.long_run_day or None
        if new_day != long_run_day:
            long_run_day = new_day
            update["long_run_day"] = new_day
            notes.append(f"sortie longue le {new_day}" if new_day else "plus de jour imposé pour la sortie longue")
    if data.include_bike is not None and data.include_bike != cycle.include_bike:
        update["include_bike"] = data.include_bike
        notes.append("vélo autorisé" if data.include_bike else "plus de vélo")
    check_availability(available_days, long_run_day, cycle.sessions_per_week)
    if not update:
        raise GoalError("Aucune modification")
    edited = cycle.model_copy(update=update)

    _, zones = refresh_snapshot(repo, garmin)
    note = f"L'athlète a modifié son objectif : {' ; '.join(notes)}. Adapte les séances à venir en conséquence."
    adj = ask_adjustment(repo, garmin, llm, edited, zones, repo.sessions(cycle.id), today, change_note=note)
    saved: dict[str, Cycle] = {}

    def apply(db) -> None:
        c = db.get(Cycle, cycle.id)
        if c is None or c.status != "active":
            raise GoalError(_NO_PLAN)
        for key, value in update.items():
            setattr(c, key, value)
        db.add(c)
        saved["cycle"] = c

    proposal_id = _save_change(repo, garmin, zones, adj, set(), apply)
    return saved["cycle"], proposal_id


def accept_plan(repo: Repo) -> None:
    """Valide le plan du cycle actif : l'export vers Garmin devient possible."""
    with repo.transaction() as db:
        cycle = db.exec(select(Cycle).where(Cycle.status == "active").order_by(Cycle.id.desc())).first()
        if cycle is None:
            raise GoalError(_NO_PLAN)
        cycle.plan_accepted = True
        db.add(cycle)
