"""Règles de disponibilité du plan (jours possibles, sortie longue), en code pur."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

from coach.llm.schemas import AdjustmentResponse, PlanResponse, SessionSpec
from coach.plan.calendar import suggested_date
from coach.plan.models import Goal, Session

if TYPE_CHECKING:
    from coach.plan.models import Event  # créé par la tâche 6


@dataclass(frozen=True)
class PlanConstraints:
    available_days: tuple[str, ...]
    long_run_day: str | None
    today: date
    include_bike: bool = False
    events: tuple["Event", ...] = ()

    @classmethod
    def of(cls, goal: Goal, today: date, events: Sequence["Event"] = ()) -> "PlanConstraints":
        # include_bike : pas encore porté par Goal (tâche 14), désactivé en attendant
        return cls(
            available_days=tuple(goal.available_days()),
            long_run_day=goal.long_run_day,
            today=today,
            include_bike=False,
            events=tuple(events),
        )


@dataclass(frozen=True)
class Planned:
    label: str  # « séance 12 », « ajout 2 », « semaine 3, séance 1 »
    spec: SessionSpec
    date: date  # scheduled_date si exportée, sinon date suggérée
    exported: bool


def planned_from_plan(goal: Goal, plan: PlanResponse) -> list[Planned]:
    """Séances d'un plan complet, aucune n'étant encore exportée."""
    return [
        Planned(
            f"semaine {week.week_index}, séance {s.order}",
            s,
            suggested_date(goal, s.week_index, s.suggested_day),
            exported=False,
        )
        for week in plan.weeks
        for s in week.sessions
    ]


def _is_exported(s: Session) -> bool:
    return s.status == "exported" and s.scheduled_date is not None


def planned_after_adjustment(goal: Goal, upcoming: list[Session], adj: AdjustmentResponse) -> list[Planned]:
    """État du plan restant après application de `adj` aux séances `upcoming`.

    Les ajouts sont libellés « ajout {i} », i étant la position (base 1) du changement dans `adj.changes`.
    """
    removed = {ch.session_id for ch in adj.changes if ch.op == "remove"}
    modified = {ch.session_id: ch.session for ch in adj.changes if ch.op == "modify"}
    planned: list[Planned] = []
    for s in upcoming:
        if s.id in removed:
            continue
        spec = modified.get(s.id) or s.to_spec()
        if _is_exported(s):  # la date Garmin est fixée, même si la séance est modifiée
            planned.append(Planned(f"séance {s.id}", spec, s.scheduled_date, exported=True))
        else:
            planned.append(
                Planned(f"séance {s.id}", spec, suggested_date(goal, spec.week_index, spec.suggested_day), False)
            )
    for i, ch in enumerate(adj.changes, start=1):
        if ch.op == "add":
            spec = ch.session
            planned.append(
                Planned(f"ajout {i}", spec, suggested_date(goal, spec.week_index, spec.suggested_day), False)
            )
    return planned


def constraint_errors(
    planned: list[Planned], c: PlanConstraints, *, fixed_counts: Mapping[int, int] | None = None
) -> list[str]:
    """Violations des règles de disponibilité ; vide si tout est respecté.

    `fixed_counts` (séances done/missed/sync_error par semaine) servira à la règle de semaine allégée.
    """
    errors: list[str] = []
    for p in planned:
        day = p.spec.suggested_day
        if not p.exported and day not in c.available_days:
            errors.append(f"{p.label} : {day} n'est pas un jour possible")
        # comme pour les jours possibles, une séance exportée garde sa date Garmin
        if (
            not p.exported
            and p.spec.type == "sortie_longue"
            and c.long_run_day is not None
            and day != c.long_run_day
        ):
            errors.append(f"{p.label} : la sortie longue doit tomber le {c.long_run_day}")
    return errors
