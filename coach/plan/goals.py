"""Règles pures des objectifs : écart entre courses, fin de cycle, classification d'un changement."""

from datetime import date, timedelta
from typing import Literal

from coach.plan.models import PRIORITY_LABELS, Goal

MIN_GAP_DAYS = 14

ChangeKind = Literal["close", "draft", "regenerate", "shrink", "adjust", "horizon"]


def goal_label(goal: Goal) -> str:
    """Libellé court d'un objectif, distance au format français."""
    distance = f"{goal.distance_km:g}".replace(".", ",")
    prefix = "Trail" if goal.type == "trail" else "Course sur route"
    return f"{prefix} de {distance} km"


def gap_conflict(goal: Goal, others: list[Goal]) -> str | None:
    """Message du premier objectif actif trop proche (hors Plaisir), sinon None."""
    if goal.priority == "plaisir":
        return None
    for other in others:
        if other.id == goal.id or other.status != "active" or other.priority == "plaisir":
            continue
        days = abs((goal.race_date - other.race_date).days)
        if days < MIN_GAP_DAYS:
            return (
                f"{goal_label(other)} du {other.race_date:%d/%m/%Y} ({PRIORITY_LABELS[other.priority]}) "
                f"est à {days} jours : passe l'un des deux en Plaisir ou déplace-le"
            )
    return None


def cycle_end(goals: list[Goal]) -> date | None:
    """Fin du cycle : premier Principal (sinon dernier objectif), étendue aux jours consécutifs."""
    if not goals:
        return None
    ordered = sorted(goals, key=lambda g: g.race_date)
    end = next((g.race_date for g in ordered if g.priority == "principal"), ordered[-1].race_date)
    dates = {g.race_date for g in ordered}
    while end + timedelta(days=1) in dates:
        end += timedelta(days=1)
    return end


def classify_change(
    *, plan_accepted: bool, old_end: date, new_end: date | None, touched_in_cycle: bool
) -> ChangeKind:
    """Nature du changement d'objectif sur le cycle courant."""
    if new_end is None:
        return "close"
    if new_end != old_end:
        if not plan_accepted:
            return "draft"
        return "regenerate" if new_end > old_end else "shrink"
    if touched_in_cycle:
        return "draft" if not plan_accepted else "adjust"
    return "horizon"
