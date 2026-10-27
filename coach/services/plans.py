"""Objectif de course et génération du plan."""

from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, Field
from sqlmodel import select

from coach.analysis.gpx import GpxSummary, analyze_gpx, summary_to_text
from coach.config import data_dir
from coach.garmin.port import GarminPort
from coach.llm.client import ask_structured
from coach.llm.prompts import SYSTEM_PROMPT, build_generation_prompt
from coach.llm.provider import LLMProvider
from coach.llm.schemas import PlanResponse, validate_plan
from coach.plan import calendar
from coach.plan.models import Goal, Session
from coach.plan.repo import Repo
from coach.services import CoachError
from coach.services.context import recent_history, refresh_snapshot

MIN_DAYS_BEFORE_RACE = 14
_NOT_FOUND = "Objectif introuvable ou archivé"


class GoalError(CoachError):
    """Objectif invalide."""


class GoalInput(BaseModel):
    type: Literal["route", "trail"]
    distance_km: float = Field(gt=0)
    d_plus_m: int = Field(ge=0)
    race_date: date
    sessions_per_week: int = Field(ge=2, le=7)
    gpx: bytes | None = None


def create_goal(repo: Repo, garmin: GarminPort, data: GoalInput) -> Goal:
    """Crée l'objectif actif ; archive le précédent et ses séances `todo`."""
    today = garmin.today()
    if data.race_date - today < timedelta(days=MIN_DAYS_BEFORE_RACE):
        raise GoalError("La course doit être dans au moins 14 jours")
    summary = analyze_gpx(data.gpx) if data.gpx is not None else None
    d_plus = data.d_plus_m
    if summary is not None and summary.d_plus_m is not None and d_plus == 0:
        d_plus = summary.d_plus_m

    goal = Goal(
        type=data.type,
        distance_km=data.distance_km,
        d_plus_m=d_plus,
        race_date=data.race_date,
        sessions_per_week=data.sessions_per_week,
        plan_start=calendar.plan_start(today),
        gpx_summary_json=summary.model_dump_json() if summary is not None else None,
    )
    path = None
    try:
        with repo.transaction() as db:
            for old in db.exec(select(Goal).where(Goal.status == "active")).all():
                old.status = "archived"
                db.add(old)
                todo = select(Session).where(Session.goal_id == old.id, Session.status == "todo")
                for s in db.exec(todo).all():
                    db.delete(s)
            db.add(goal)
            db.flush()  # obtient l'id
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


def generate_plan(repo: Repo, garmin: GarminPort, llm: LLMProvider, goal_id: int) -> PlanResponse:
    """Génère le plan avec Claude ; remplace le brouillon `todo` précédent."""
    goal = _get_goal(repo, goal_id)
    _, zones = refresh_snapshot(repo, garmin)
    n = calendar.n_weeks(goal.plan_start, goal.race_date)
    gpx_text = (
        summary_to_text(GpxSummary.model_validate_json(goal.gpx_summary_json))
        if goal.gpx_summary_json
        else None
    )
    prompt = build_generation_prompt(goal, zones, recent_history(garmin), n, gpx_text)
    pace_available = zones.pace is not None
    plan = ask_structured(
        llm,
        SYSTEM_PROMPT,
        prompt,
        PlanResponse,
        validate=lambda p: validate_plan(
            p, n_weeks=n, sessions_per_week=goal.sessions_per_week, pace_available=pace_available
        ),
    )
    with repo.transaction() as db:
        todo = select(Session).where(Session.goal_id == goal_id, Session.status == "todo")
        for s in db.exec(todo).all():
            db.delete(s)
        for week in plan.weeks:
            for spec in week.sessions:
                db.add(Session.from_spec(spec, goal_id))
        g = db.get(Goal, goal_id)
        if g is None:
            raise GoalError(_NOT_FOUND)
        g.plan_accepted = False
        db.add(g)
    return plan


def accept_plan(repo: Repo, goal_id: int) -> None:
    """Valide le plan : l'export vers Garmin devient possible."""
    with repo.transaction() as db:
        goal = db.get(Goal, goal_id)
        if goal is None or goal.status != "active":
            raise GoalError(_NOT_FOUND)
        goal.plan_accepted = True
        db.add(goal)
