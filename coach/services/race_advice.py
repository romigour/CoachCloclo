"""Conseils du coach pour le jour J : demandés à Claude, enregistrés avec leur date et leur empreinte."""

from datetime import datetime, timezone

from coach.garmin.port import GarminPort
from coach.llm.client import ask_structured
from coach.llm.prompts import ADVICE_SYSTEM_PROMPT, build_race_advice_prompt
from coach.llm.provider import LLMProvider
from coach.llm.schemas import CoachAdvice, validate_advice
from coach.plan.repo import Repo
from coach.services.context import long_history, recent_history
from coach.services.goals import _get_goal
from coach.services.llm_usage import tracked
from coach.services.race_strategy import RaceView, _get_or_create, _view, advice_fingerprint

__all__ = ["advice_fingerprint", "ask_race_advice"]


def ask_race_advice(repo: Repo, garmin: GarminPort, llm: LLMProvider, goal_id: int) -> RaceView:
    """Demande les conseils à Claude sur le guide du moment, les enregistre et renvoie la vue à jour.

    Toute allure, durée ou heure absente du prompt est refusée (une relance, puis `LLMInvalidResponse`) ;
    rien n'est écrit en cas d'échec. L'empreinte est celle des données envoyées à Claude.
    """
    goal = _get_goal(repo, goal_id)
    today = garmin.today()
    view = _view(repo, _get_or_create(repo, garmin, goal), goal, today)
    prompt = build_race_advice_prompt(
        goal, view, recent_history(garmin), long_history(repo, today), repo.recent_done_goals(today)
    )
    with tracked(repo, "race_advice") as meter:
        advice = ask_structured(
            llm, ADVICE_SYSTEM_PROMPT, prompt, CoachAdvice, validate=lambda a: validate_advice(a, prompt), meter=meter
        )
    strategy = repo.race_strategy(goal.id)  # relue : les réglages ont pu changer pendant l'appel
    strategy.advice_json = advice.model_dump_json()
    strategy.advice_at = datetime.now(timezone.utc).replace(microsecond=0)
    strategy.advice_hash = advice_fingerprint(goal, view.plan)
    strategy = repo.update(strategy)
    # objectif relu : une modification pendant l'appel rend aussitôt les conseils « à redemander »
    return _view(repo, strategy, _get_goal(repo, goal_id), today)  # vue et copie pour le mobile
