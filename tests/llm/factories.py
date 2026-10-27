"""Fabriques de réponses Claude pour les tests (réutilisées par les tâches suivantes)."""

from coach.llm.schemas import PlanResponse, SessionSpec, StepSpec, WeekSpec


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


def make_plan(n_weeks: int, per_week: list[int], target_kind: str = "hr") -> PlanResponse:
    """Plan de `n_weeks` semaines avec `per_week[i]` séances (orders 1..k) en semaine i+1."""
    weeks = [
        WeekSpec(
            week_index=w,
            focus=f"Semaine {w}",
            sessions=[
                make_session(week_index=w, order=o, target_kind=target_kind)
                for o in range(1, per_week[w - 1] + 1)
            ],
        )
        for w in range(1, n_weeks + 1)
    ]
    return PlanResponse(summary="Plan de test", weeks=weeks)


def valid_plan_json(n_weeks: int, per_week: int) -> str:
    """JSON d'un plan valide de `n_weeks` semaines à `per_week` séances."""
    return make_plan(n_weeks, [per_week] * n_weeks).model_dump_json()
