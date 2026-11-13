"""Fabriques de réponses Claude pour les tests (réutilisées par les tâches suivantes)."""

from coach.llm.schemas import GoalEstimate, PlanResponse, SessionSpec, StepSpec, WeekSpec


def make_session(**overrides) -> SessionSpec:
    """SessionSpec valide par défaut (EF, cible FC, un échauffement) ; `overrides` écrase les champs."""
    target_kind = overrides.get("target_kind", "hr")
    zone = "EF" if target_kind == "pace" else "Z2"
    data = {
        "week_index": 1,
        "order": 1,
        "suggested_day": "mardi",
        "type": "EF",
        "target_kind": "hr",
        "title": "Sortie facile",
        "description": "Footing en endurance fondamentale.",
        "chaining_note": None,
        "steps": [StepSpec(kind="warmup", duration_s=600, zone=zone)],
    }
    data.update(overrides)
    return SessionSpec(**data)


def estimates(estimated_time_s: int | None, goal_id: int = 1) -> list[GoalEstimate]:
    """Estimation unique de l'objectif `goal_id` (aucune si `estimated_time_s` est None)."""
    return [] if estimated_time_s is None else [GoalEstimate(goal_id=goal_id, seconds=estimated_time_s)]


def make_plan(
    n_weeks: int, per_week: list[int], target_kind: str = "hr", estimated_time_s: int | None = None,
    goal_id: int = 1,
) -> PlanResponse:
    """Plan de `n_weeks` semaines avec `per_week[i]` séances (orders 1..k) en semaine i+1.

    `estimated_time_s` devient l'estimation de l'objectif `goal_id`. Les séances tombent le jeudi : la
    génération refuse un jour passé, et l'aujourd'hui par défaut du faux Garmin est un mercredi.
    """
    weeks = [
        WeekSpec(
            week_index=w,
            focus=f"Semaine {w}",
            sessions=[
                make_session(week_index=w, order=o, target_kind=target_kind, suggested_day="jeudi")
                for o in range(1, per_week[w - 1] + 1)
            ],
        )
        for w in range(1, n_weeks + 1)
    ]
    return PlanResponse(summary="Plan de test", weeks=weeks, estimated_times=estimates(estimated_time_s, goal_id))


def valid_plan_json(n_weeks: int, per_week: int, estimated_time_s: int | None = 19800, goal_id: int = 1) -> str:
    """JSON d'un plan valide de `n_weeks` semaines à `per_week` séances, une de moins la dernière semaine
    (la course y compte comme une séance)."""
    counts = [per_week] * (n_weeks - 1) + [max(0, per_week - 1)]
    return make_plan(n_weeks, counts, estimated_time_s=estimated_time_s, goal_id=goal_id).model_dump_json()
