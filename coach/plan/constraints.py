"""Règles de disponibilité du plan (jours possibles, sortie longue), en code pur."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING

from coach.llm.schemas import AdjustmentResponse, PlanResponse, SessionSpec
from coach.plan.calendar import plan_start as monday_of
from coach.plan.calendar import suggested_date
from coach.plan.models import ALL_DAYS, Goal, Session

if TYPE_CHECKING:
    from coach.plan.models import Event


@dataclass(frozen=True)
class PlanConstraints:
    available_days: tuple[str, ...]
    long_run_day: str | None
    today: date
    include_bike: bool = False
    events: tuple["Event", ...] = ()
    plan_start: date | None = None  # lundi de la semaine 1 ; sert à situer une semaine allégée

    @classmethod
    def of(cls, goal: Goal, today: date, events: Sequence["Event"] = ()) -> "PlanConstraints":
        return cls(
            available_days=tuple(goal.available_days()),
            long_run_day=goal.long_run_day,
            today=today,
            include_bike=goal.include_bike,
            events=tuple(events),
            plan_start=goal.plan_start,
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


def _fmt(d: date) -> str:
    return d.strftime("%d/%m")


def blocked_periods(c: PlanConstraints) -> list[tuple[date, date, str]]:
    """Périodes où aucune séance ne doit tomber : (début, fin incluse, libellé)."""
    periods: list[tuple[date, date, str]] = []
    for e in c.events:
        if e.kind == "unavailable" and e.end_date is not None:
            label = f"indisponibilité du {_fmt(e.start_date)} au {_fmt(e.end_date)}"
            periods.append((e.start_date, e.end_date, label))
        elif e.kind == "injury":
            if e.end_date is not None:
                periods.append((e.start_date, e.end_date, f"arrêt du {_fmt(e.start_date)} au {_fmt(e.end_date)}"))
            else:  # arrêt ouvert : bloque jusqu'à la fin de la semaine en cours
                end = max(e.start_date, monday_of(c.today) + timedelta(days=6))
                periods.append((e.start_date, end, f"arrêt depuis le {_fmt(e.start_date)}"))
    return periods


def _light_weeks(c: PlanConstraints) -> list["Event"]:
    return [e for e in c.events if e.kind == "light_week"]


def constraint_errors(
    planned: list[Planned], c: PlanConstraints, *, fixed_counts: Mapping[int, int] | None = None
) -> list[str]:
    """Violations des règles de disponibilité ; vide si tout est respecté.

    `fixed_counts` (séances done/missed/sync_error par semaine) compte dans la limite d'une semaine allégée.
    """
    errors: list[str] = []
    periods = blocked_periods(c)
    light_weeks = _light_weeks(c)
    for p in planned:
        day = p.spec.suggested_day
        monday = monday_of(p.date)
        # semaine allégée avec jours restreints : ces jours remplacent les jours possibles de l'objectif
        restricted = [e.days() for e in light_weeks if e.start_date == monday and e.days() is not None]
        allowed = set.intersection(*(set(d) for d in restricted)) if restricted else set(c.available_days)
        if not p.exported and day not in allowed:
            errors.append(f"{p.label} : {day} n'est pas un jour possible")
        # comme pour les jours possibles, une séance exportée garde sa date Garmin
        if (
            not p.exported
            and p.spec.type == "sortie_longue"
            and c.long_run_day is not None
            and day != c.long_run_day
            and not _long_run_day_free(c, monday, periods, restricted)
        ):
            errors.append(f"{p.label} : la sortie longue doit tomber le {c.long_run_day}")
        for start, end, name in periods:
            if start <= p.date <= end:
                if p.exported:
                    errors.append(f"{p.label} : séance exportée pendant {name}, à retirer (op remove)")
                else:
                    errors.append(f"{p.label} : tombe pendant {name}")
    errors += _light_week_count_errors(planned, c, fixed_counts or {})
    errors += _bike_errors(planned, c)
    return errors


def _bike_errors(planned: list[Planned], c: PlanConstraints) -> list[str]:
    """Règle 6 : vélo autorisé par l'objectif, EF/récup en FC en Z1-Z2, une séance par semaine.

    Ces contrôles portent sur le contenu, donc sur toutes les séances, exportées ou non.
    """
    errors: list[str] = []
    per_week: dict[int, int] = {}
    for p in planned:
        if p.spec.sport != "bike":
            continue
        per_week[p.spec.week_index] = per_week.get(p.spec.week_index, 0) + 1
        if not c.include_bike:
            errors.append(f"{p.label} : séance vélo non autorisée pour cet objectif")
        if p.spec.type not in ("EF", "récup") or p.spec.target_kind != "hr":
            errors.append(f"{p.label} : une séance vélo doit être de l'EF ou de la récup ciblée en FC")
        elif any(st.zone not in (None, "Z1", "Z2") for st in p.spec.iter_steps()):
            errors.append(f"{p.label} : séance vélo limitée aux zones Z1 et Z2")
    errors += [f"semaine {w} : au plus une séance vélo" for w, n in sorted(per_week.items()) if n > 1]
    return errors


def _long_run_day_free(
    c: PlanConstraints, monday: date, periods: list[tuple[date, date, str]], restricted: list[list[str] | None]
) -> bool:
    """Vrai si le jour de sortie longue est bloqué ou exclu cette semaine-là (tout jour possible convient)."""
    if any(c.long_run_day not in days for days in restricted):
        return True
    d = monday + timedelta(days=ALL_DAYS.index(c.long_run_day))
    return any(start <= d <= end for start, end, _ in periods)


def _light_week_count_errors(planned: list[Planned], c: PlanConstraints, fixed_counts: Mapping[int, int]) -> list[str]:
    """Règle 4 : séances de la semaine (déjà faites + prévues) au plus `max_sessions`."""
    if c.plan_start is None:
        return []
    errors: list[str] = []
    for e in _light_weeks(c):
        if e.max_sessions is None:
            continue
        week = (e.start_date - c.plan_start).days // 7 + 1
        upcoming = sum(1 for p in planned if p.spec.week_index == week)
        total = fixed_counts.get(week, 0) + upcoming
        msg = f"semaine {week} : {total} séances pour {e.max_sessions} au plus (semaine allégée)"
        # rien à corriger si aucune séance n'est prévue cette semaine-là
        if upcoming and total > e.max_sessions and msg not in errors:
            errors.append(msg)
    return errors
