"""Prompts de génération et d'ajustement envoyés à Claude (contexte compact en français)."""

import datetime as dt
import json
from typing import get_args

from coach.analysis.laps import StepComparison, StepResult
from coach.analysis.race_plan import RacePlan
from coach.analysis.zones import Zones
from coach.llm.schemas import AdjustmentResponse, PlanResponse, Weekday
from coach.plan.calendar import week_of
from coach.plan.constraints import PlanConstraints
from coach.plan.goals import goal_label
from coach.plan.models import PRIORITY_LABELS, Activity, Cycle, Event, Goal, Session

HISTORY_WEEKS = 8
HISTORY_MAX_LINES = 60
MAX_LAP_LINES = 30
_WEEKDAYS = get_args(Weekday)
_MONTHS = (
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)

SYSTEM_PROMPT = """Tu es un entraîneur expérimenté de course à pied sur route et de trail.
Tu construis et ajustes des plans d'entraînement personnalisés à partir des données Garmin de l'athlète.

Règles impératives :
- Réponds uniquement par un JSON conforme au schéma fourni, sans texte autour ni bloc de code.
- Dans le champ "zone" des étapes, utilise uniquement les noms de zones fournis dans la demande ; \
n'écris jamais de valeur chiffrée d'allure ou de fréquence cardiaque dans les étapes, les titres ou les descriptions.
- Choisis target_kind "pace" pour la route et le fractionné sur plat ; choisis "hr" pour le trail, \
les côtes et l'endurance fondamentale (EF).
- Avec target_kind "pace", les zones sont des noms d'allure (récup, EF, marathon, seuil, VMA) ; \
avec "hr", ce sont des zones de FC (Z1 à Z5).
- Rédige tous les textes (résumés, titres, descriptions, analyses, raisons) en français.
- Respecte la progressivité : charge croissante, semaines allégées régulières, affûtage avant la course."""


def _fmt_pace(s: int) -> str:
    return f"{s // 60}:{s % 60:02d}"

_KIND_LABELS = {"warmup": "échauffement", "active": "actif", "recovery": "récup", "cooldown": "retour au calme"}
_VERDICT_LABELS = {"fast": "trop vite", "slow": "trop lent", "hr_high": "FC trop haute", "hr_low": "FC trop basse"}
_INDENT = "    "
_DETAIL_RULE = (
    "Le détail par étape compare le réalisé aux zones cibles ; "
    "appuie ton analyse dessus quand il est présent."
)


def _planned_volume(r: StepResult) -> str:
    if r.planned_distance_m is not None:
        return f"{r.planned_distance_m} m"
    d = r.planned_duration_s or 0
    return f"{d // 60} min" if d >= 60 and d % 60 == 0 else f"{d} s"


def _zone_text(r: StepResult, target_kind: str) -> str:
    if r.zone is None:
        return ""
    if r.target_low is None or r.target_high is None:
        return f" {r.zone}"
    if target_kind == "pace":
        return f" {r.zone} [{_fmt_pace(round(r.target_low))}–{_fmt_pace(round(r.target_high))}/km]"
    return f" {r.zone} [{round(r.target_low)}–{round(r.target_high)} bpm]"


def _step_head(r: StepResult, target_kind: str) -> str:
    return f"{_KIND_LABELS[r.kind]} {_planned_volume(r)}{_zone_text(r, target_kind)}"


def _with_verdict(text: str, r: StepResult) -> str:
    return f"{text} ({_VERDICT_LABELS[r.verdict]})" if r.verdict in _VERDICT_LABELS else text


def _simple_step_line(r: StepResult, target_kind: str) -> str:
    head = _step_head(r, target_kind)
    if not r.done:
        return f"{head} : non réalisée"
    parts = []
    if r.duration_s is not None:
        parts.append(_fmt_pace(round(r.duration_s)))
    if r.avg_pace_s_km is not None:
        parts.append(f"{_fmt_pace(round(r.avg_pace_s_km))}/km")
    if r.avg_hr is not None:
        parts.append(f"{r.avg_hr} bpm")
    return _with_verdict(f"{head} : {', '.join(parts)}", r)


def _repeat_value(r: StepResult, target_kind: str) -> str:
    if not r.done:
        return "non réalisée"
    if target_kind == "pace":
        value = _fmt_pace(round(r.avg_pace_s_km)) if r.avg_pace_s_km is not None else "?"
    else:
        value = f"{r.avg_hr} bpm" if r.avg_hr is not None else "?"
    return _with_verdict(value, r)


def _repeat_lines(group: list[StepResult], target_kind: str) -> list[str]:
    by_position: dict[int, list[StepResult]] = {}
    for r in group:
        by_position.setdefault(r.position, []).append(r)
    return [
        f"{len(rs)}× {_step_head(rs[0], target_kind)} : " + ", ".join(_repeat_value(r, target_kind) for r in rs)
        for _, rs in sorted(by_position.items())
    ]


def _lap_line(n: int, lap) -> str:
    parts = [f"{round(lap.distance_m)} m", _fmt_pace(round(lap.duration_s))]
    if lap.avg_pace_s_km is not None:
        parts.append(f"{_fmt_pace(round(lap.avg_pace_s_km))}/km")
    if lap.avg_hr is not None:
        parts.append(f"{lap.avg_hr} bpm")
    return f"· tour {n} : " + ", ".join(parts)


def _comparison_lines(c: StepComparison) -> list[str]:
    """Lignes (sans indentation) du détail par étape, ou des tours bruts en mode dégradé."""
    if not c.followed_workout:
        if not c.laps:
            return ["séance non suivie sur la montre : aucun tour enregistré"]
        lines = ["séance non suivie sur la montre, tours :"]
        lines += [_lap_line(n, lap) for n, lap in enumerate(c.laps[:MAX_LAP_LINES], start=1)]
        if len(c.laps) > MAX_LAP_LINES:
            lines.append(f"… {len(c.laps) - MAX_LAP_LINES} tours de plus")
        return lines
    groups: dict[int, list[StepResult]] = {}
    for r in c.steps:
        groups.setdefault(r.group, []).append(r)
    lines = []
    for group in groups.values():
        if group[0].iteration is None:
            lines.append("· " + _simple_step_line(group[0], c.target_kind))
        else:
            lines += ["· " + line for line in _repeat_lines(group, c.target_kind)]
    return lines


def _zones_text(zones: Zones) -> str:
    lines = ["Zones disponibles (références uniquement, ne cite que les noms dans \"zone\") :"]
    if zones.pace is None:
        lines.append(
            "Aucune zone d'allure n'est disponible : Aucune zone d'allure, "
            'utilise exclusivement target_kind "hr".'
        )
    else:
        lines.append("Allures :")
        for name, (fast, slow) in zones.pace.items():
            lines.append(f"- {name} : {_fmt_pace(fast)}–{_fmt_pace(slow)} /km")
    lines.append("Fréquence cardiaque :")
    for name, (lo, hi) in zones.hr.items():
        lines.append(f"- {name} : {lo}–{hi} bpm")
    return "\n".join(lines)


def _activity_line(a: Activity) -> str:
    parts = [a.date.isoformat(), a.type_key]
    parts.append(f"{round(a.duration_s / 60)} min" if a.duration_s is not None else "durée ?")
    parts.append(f"{a.distance_m / 1000:.1f} km" if a.distance_m is not None else "distance ?")
    parts.append(f"D+ {round(a.d_plus_m)} m" if a.d_plus_m is not None else "D+ ?")
    parts.append(f"FC moy {round(a.avg_hr)} bpm" if a.avg_hr is not None else "FC ?")
    return "- " + " | ".join(parts)


def _history_text(history: list[Activity]) -> str:
    if not history:
        return "Historique récent : aucune activité."
    cutoff = max(a.date for a in history) - dt.timedelta(weeks=HISTORY_WEEKS)
    recent = sorted((a for a in history if a.date > cutoff), key=lambda a: a.date, reverse=True)
    lines = [_activity_line(a) for a in recent[:HISTORY_MAX_LINES]]
    return f"Historique récent ({HISTORY_WEEKS} dernières semaines, plus récent d'abord) :\n" + "\n".join(lines)


NEW_GOAL_ID = 0  # id provisoire d'un objectif pas encore enregistré (ajout), dans le prompt et les estimations

PRIORITY_RULES = """Préparation selon la priorité :
- Principal : affûtage complet avant la course.
- Secondaire : une séance spécifique dans les 10 jours avant, un mini-affûtage de quelques jours (volume \
réduit, intensité conservée), une récupération après, sans casser la progression vers le Principal.
- Plaisir : pas d'affûtage ; la course remplace une séance de sa semaine (souvent la sortie longue), avec une \
récupération légère après si elle est longue."""
# rappelé dans tout prompt, un ou plusieurs objectifs : c'est contrôlé (constraint_errors)
RACE_DAY_RULE = "Aucune séance le jour d'une course ; la course compte comme une séance de sa semaine."


def _goal_id(goal: Goal) -> int:
    return goal.id if goal.id is not None else NEW_GOAL_ID


def _single_goal_text(goal: Goal, *, generation: bool = False, plan_start: dt.date | None = None) -> str:
    """Texte d'un cycle à un seul objectif Principal (inchangé depuis l'objectif unique).

    `generation` : un temps issu d'une estimation de Claude est présenté comme estimation précédente.
    `plan_start` ajoute le début du plan juste après la date de course.
    """
    text = (
        f"Objectif : course de type {goal.type}, {goal.distance_km:g} km, "
        f"{goal.d_plus_m} m de D+, le {goal.race_date.isoformat()}."
    )
    if plan_start is not None:
        text += f" Le plan débute le {plan_start.isoformat()}."
    if goal.target_time_s is not None:
        if generation and goal.target_source == "claude":
            text += f" Estimation précédente : {fmt_duration(goal.target_time_s)}."
        else:
            text += f" Temps visé : {fmt_duration(goal.target_time_s)}."
    return text


def _is_single(goals: list[Goal], horizon: list[Goal]) -> bool:
    """Un seul objectif, Principal, et rien après : le texte d'avant les cycles est conservé."""
    return len(goals) == 1 and goals[0].priority == "principal" and not horizon


def _goal_line(goal: Goal, *, generation: bool = False, with_time: bool = True, block: bool = False) -> str:
    """« - 2027-03-28 : trail, 20 km, 800 m de D+, priorité Secondaire, temps visé 2 h 10 »."""
    text = (
        f"- {goal.race_date.isoformat()} : {goal.type}, {goal.distance_km:g} km, {goal.d_plus_m} m de D+, "
        f"priorité {PRIORITY_LABELS[goal.priority]}"
    )
    if with_time and goal.target_time_s is not None:
        label = "estimation précédente" if generation and goal.target_source == "claude" else "temps visé"
        text += f", {label} {fmt_duration(goal.target_time_s)}"
    return text + (" (enchaînés, à traiter comme un bloc)" if block else "")


def _goals_text(
    goals: list[Goal], horizon: list[Goal], *, generation: bool = False, plan_start: dt.date | None = None
) -> str:
    """Objectifs du cycle : texte d'avant les cycles pour un seul Principal sans horizon, sinon une ligne
    par objectif ; deux courses à des dates consécutives sont signalées comme un bloc."""
    if not goals:
        raise ValueError("le cycle n'a aucun objectif")
    if _is_single(goals, horizon):
        return _single_goal_text(goals[0], generation=generation, plan_start=plan_start)
    ordered = sorted(goals, key=lambda g: g.race_date)
    dates = {g.race_date for g in ordered}
    one_day = dt.timedelta(days=1)
    lines = [
        _goal_line(g, generation=generation, block=g.race_date - one_day in dates or g.race_date + one_day in dates)
        for g in ordered
    ]
    text = "Objectifs du cycle :\n" + "\n".join(lines)
    if plan_start is not None:
        text += f"\nLe plan débute le {plan_start.isoformat()}."
    return text


def _first_principal(goals: list[Goal]) -> Goal | None:
    """Principal qui termine le cycle (le premier), None si le cycle n'en a pas."""
    return next((g for g in sorted(goals, key=lambda g: g.race_date) if g.priority == "principal"), None)


def _cycle_rules(goals: list[Goal], horizon: list[Goal]) -> list[str]:
    """Règles de priorité (plusieurs objectifs ou un objectif non Principal), règle du jour de course
    (toujours) et horizon, une partie chacun."""
    parts: list[str] = []
    if len(goals) > 1 or any(g.priority != "principal" for g in goals):
        parts.append(PRIORITY_RULES)
    parts.append(RACE_DAY_RULE)
    if horizon:
        text = "Objectifs suivants (préparés dans un cycle ultérieur, ne pas les anticiper) :\n" + "\n".join(
            _goal_line(g, with_time=False) for g in sorted(horizon, key=lambda g: g.race_date)
        )
        end = _first_principal(goals)
        if end is not None and any(g.priority == "principal" for g in horizon):
            text += f"\nTermine ce cycle par l'affûtage de {goal_label(end)} sans anticiper le suivant."
        parts.append(text)
    return parts


def generation_estimates(goals: list[Goal]) -> list[Goal]:
    """Objectifs que la génération estime : ceux du cycle dont le temps revient à Claude."""
    return [g for g in goals if g.target_source == "claude"]


def adjustment_estimates(goals: list[Goal]) -> list[Goal]:
    """Objectifs qu'un ajustement doit estimer : ceux du cycle en mode `claude` encore sans temps."""
    return [g for g in goals if g.target_source == "claude" and g.target_time_s is None]


def estimate_floors(goals: list[Goal], min_pace_s_km: int) -> dict[int, int]:
    """Plancher d'estimation par objectif (id provisoire pour un objectif pas encore enregistré)."""
    return {_goal_id(g): round(min_pace_s_km * g.distance_km) for g in goals}


def _estimate_text(to_estimate: list[Goal]) -> str:
    """« Pour chaque objectif sans temps visé (ids 3 (2027-03-28), 5 (2027-03-29)), estime… »."""
    ordered = sorted(to_estimate, key=lambda g: g.race_date)
    ids = ", ".join(f"{_goal_id(g)} ({g.race_date.isoformat()})" for g in ordered)
    return (
        f"Pour chaque objectif sans temps visé (ids {ids}), estime un temps réaliste dans estimated_times "
        "(en secondes)."
    )


def _target_parts(goals: list[Goal], horizon: list[Goal]) -> list[str]:
    """Consigne de génération sur les temps : estimation par objectif, ou plan construit pour les temps visés."""
    to_estimate = generation_estimates(goals)
    if _is_single(goals, horizon):
        goal = goals[0]
        if to_estimate:
            return [
                "Estime d'abord un temps réaliste pour cette course d'après l'historique et les zones, "
                f"indique-le dans estimated_times (goal_id {_goal_id(goal)}, en secondes), "
                "puis construis le plan pour ce temps."
            ]
        if goal.target_time_s is not None:
            return ["Construis le plan pour atteindre ce temps visé (allures cibles, volume)."]
        return []
    parts = [_estimate_text(to_estimate)] if to_estimate else []
    if any(g.target_source != "claude" and g.target_time_s is not None for g in goals):
        parts.append("Construis le plan pour atteindre les temps visés indiqués (allures cibles, volume).")
    return parts


_BIKE_RULE = (
    "Vélo autorisé : tu peux remplacer au plus une séance EF ou récup par semaine par du vélo d'endurance douce "
    "(sport \"bike\", target_kind \"hr\", zones Z1 ou Z2, étapes en durée uniquement), sur route ou home-trainer, "
    "jamais à la place d'une séance clé ; compte une durée d'environ 1,3 à 1,5 fois celle de la séance de course "
    "remplacée."
)
_RUN_ONLY_RULE = 'Toutes les séances sont en course à pied (sport "run").'


def _availability_text(c: PlanConstraints) -> str:
    text = f"Disponibilités : Jours possibles : {', '.join(c.available_days)}."
    if c.long_run_day is not None:
        text += f" Sortie longue : le {c.long_run_day}."
    text += " Ne place aucune séance un autre jour."
    return text + " " + (_BIKE_RULE if c.include_bike else _RUN_ONLY_RULE)


def _fmt_date(d: dt.date) -> str:
    return d.strftime("%d/%m/%Y")


FATIGUE_DAYS = 14  # une fatigue signalée plus tôt n'est plus d'actualité


def _event_line(e: Event, c: PlanConstraints) -> str:
    note = f" : {e.note}" if e.note else ""
    if e.kind == "unavailable":
        return f"- indisponible du {_fmt_date(e.start_date)} au {_fmt_date(e.end_date)}{note}"
    if e.kind == "injury":
        if e.end_date is None:
            return f"- blessure/maladie depuis le {_fmt_date(e.start_date)} (reprise non connue){note}"
        return f"- blessure/maladie du {_fmt_date(e.start_date)} au {_fmt_date(e.end_date)}{note}"
    if e.kind == "light_week":
        if c.plan_start is not None:
            label = f"semaine {(e.start_date - c.plan_start).days // 7 + 1}"
        else:
            label = f"semaine du {_fmt_date(e.start_date)}"
        text = f"- semaine allégée ({label}) : {e.max_sessions} séance{'s' if (e.max_sessions or 0) > 1 else ''} au plus"
        if e.days() is not None:
            text += f", jours possibles {', '.join(e.days())}"
        return text + note
    return f"- fatigue signalée le {_fmt_date(e.start_date)}{note}"


def _events_text(c: PlanConstraints) -> str | None:
    """Imprévus en cours ou à venir et fatigues récentes, par date de début ; None s'il n'y en a pas."""

    def relevant(e: Event) -> bool:
        if e.kind == "fatigue":
            return 0 <= (c.today - e.start_date).days <= FATIGUE_DAYS
        return e.end_date is None or e.end_date >= c.today

    events = sorted((e for e in c.events if relevant(e)), key=lambda e: e.start_date)
    if not events:
        return None
    return "Imprévus :\n" + "\n".join(_event_line(e, c) for e in events)


def _today_text(cycle: Cycle, today: dt.date) -> str:
    """« Aujourd'hui : mercredi 4 novembre 2026 (semaine 1). »"""
    week = week_of(cycle, today)
    return (
        f"Aujourd'hui : {_WEEKDAYS[today.weekday()]} {today.day} {_MONTHS[today.month - 1]} "
        f"{today.year} (semaine {week})."
    )


def fmt_duration(s: int) -> str:
    """« 5 h 12 » (arrondi à la minute)."""
    h, m = divmod(round(s / 60), 60)
    return f"{h} h {m:02d}"


def race_text(plan: RacePlan) -> str | None:
    """Résumé indicatif de la stratégie du jour J ; None sans temps de référence."""
    if plan.reference_time_s is None:
        return None
    label = "visé" if plan.target_time_s is not None else "temps estimé"
    text = f"Stratégie jour J (indicative) : {label} {fmt_duration(plan.reference_time_s)}"
    climbs = sorted(
        sorted((s for s in plan.segments if s.kind == "montée"), key=lambda s: s.d_plus_m, reverse=True)[:3],
        key=lambda s: s.start_km,
    )
    if climbs:
        labels = [f"km {round(s.start_km)} (+{s.d_plus_m} m)" for s in climbs]
        text += " ; montées clés " + (labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + " et " + labels[-1])
    return (
        text + ". N'en tenir compte que pour orienter légèrement le contenu de l'affûtage, "
        "sans modifier la structure ni le volume du plan."
    )


def _schema_text(model) -> str:
    return json.dumps(model.model_json_schema(), ensure_ascii=False)


def build_generation_prompt(
    cycle: Cycle,
    goals: list[Goal],
    horizon: list[Goal],
    zones: Zones,
    history: list[Activity],
    n_weeks: int,
    gpx_texts: list[str],
    today: dt.date | None = None,
    race_texts: list[str] = (),
    constraints: PlanConstraints | None = None,
    *,
    first_week: int = 1,
    fixed: list[Session] = (),
    recovery_note: str | None = None,
) -> str:
    """Prompt de génération du plan du cycle ; `today` situe le jour courant dans la semaine `first_week`.

    `first_week` > 1 ou `fixed` non vide : seule la suite du plan est demandée, les séances `fixed`
    (faites ou exportées) comptant dans leur semaine.
    `horizon` : objectifs au-delà du cycle, rappelés sans être préparés. `recovery_note` (récupération
    après la dernière course du cycle précédent) suit la ligne des objectifs.
    """
    parts = [
        _goals_text(goals, horizon, generation=True, plan_start=cycle.plan_start)
        + (" " + _today_text(cycle, today) if today is not None else ""),
        *([recovery_note] if recovery_note else []),
        *_cycle_rules(goals, horizon),
        *([_availability_text(constraints)] if constraints is not None else []),
        *([t] if constraints is not None and (t := _events_text(constraints)) else []),
        f"Construis un plan de {n_weeks} semaines, avec au plus {cycle.sessions_per_week} séances "
        f"par semaine ({cycle.sessions_per_week} séances). Aujourd'hui correspond à la semaine {first_week} ; "
        f"la dernière semaine se termine à la course. Numérote les semaines de {first_week} à {n_weeks} "
        "et les séances de chaque semaine à partir de 1 (champ order).",
    ]
    if fixed:
        parts.append(
            f"Semaines {first_week} à {n_weeks} seulement : les séances suivantes sont fixées et comptent "
            "dans leur semaine :\n" + "\n".join(_session_line(s) for s in fixed)
        )
    elif first_week > 1:
        parts.append(f"Semaines {first_week} à {n_weeks} seulement : les semaines précédentes sont passées.")
    parts += _target_parts(goals, horizon)
    parts += [
        _zones_text(zones),
        _history_text(history),
    ]
    parts += ["Profil du parcours (GPX) :\n" + t for t in gpx_texts if t]
    parts += [t for t in race_texts if t]
    parts.append("Schéma JSON attendu :\n" + _schema_text(PlanResponse))
    return "\n\n".join(parts)


def _session_line(s: Session) -> str:
    return (
        f"id={s.id} | semaine {s.week_index} | {s.suggested_day} | {s.type} | {s.title} | "
        f"statut {s.status} | date {s.scheduled_date or '-'}" + (" | vélo" if s.sport == "bike" else "")
    )


def _kind(s: Session) -> str:
    return f"{s.type}, vélo" if s.sport == "bike" else s.type


def _done_line(s: Session, a: Activity) -> str:
    return f"- prévu : {s.title} ({_kind(s)}) -> réalisé : " + _activity_line(a)[2:]


def _done_block(s: Session, a: Activity, comparisons: dict[int, StepComparison]) -> str:
    comparison = comparisons.get(s.id)
    if comparison is None:
        return _done_line(s, a)
    detail = [_INDENT + line for line in _comparison_lines(comparison)]
    return "\n".join([_done_line(s, a), *detail])


def build_adjustment_prompt(
    cycle: Cycle,
    goals: list[Goal],
    horizon: list[Goal],
    zones: Zones,
    current_week: int,
    done: list[tuple[Session, Activity]],
    missed: list[Session],
    upcoming: list[Session],
    history: list[Activity],
    comparisons: dict[int, StepComparison] | None = None,
    race_texts: list[str] = (),
    change_note: str | None = None,
    constraints: PlanConstraints | None = None,
) -> str:
    """Prompt de proposition d'ajustements après une synchronisation.

    `comparisons` (clé = Session.id) ajoute le détail par étape sous les séances réalisées concernées.
    `change_note` signale une modification de l'objectif, insérée juste après le descriptif des objectifs.
    `horizon` : objectifs au-delà du cycle, rappelés sans être préparés.
    """
    comparisons = comparisons or {}
    to_estimate = adjustment_estimates(goals)
    parts = [
        _goals_text(goals, horizon, plan_start=cycle.plan_start),
        *([change_note] if change_note else []),
        *_cycle_rules(goals, horizon),
        *([_estimate_text(to_estimate)] if to_estimate else []),
        *([_availability_text(constraints)] if constraints is not None else []),
        *([t] if constraints is not None and (t := _events_text(constraints)) else []),
        f"Nous sommes en semaine {current_week} du plan, à raison de {cycle.sessions_per_week} séances "
        "maximum par semaine. Analyse les séances réalisées et manquées, puis propose des ajustements "
        "pour les séances à venir (liste vide si aucun changement n'est utile).",
        _zones_text(zones),
        "Séances réalisées (prévu -> réalisé) :\n"
        + ("\n".join(_done_block(s, a, comparisons) for s, a in done) if done else "aucune")
        + (f"\n{_DETAIL_RULE}" if comparisons else ""),
        "Séances manquées :\n"
        + ("\n".join(f"- {s.title} ({_kind(s)}, semaine {s.week_index})" for s in missed) if missed else "aucune"),
        "Séances à venir :\n" + ("\n".join(_session_line(s) for s in upcoming) if upcoming else "aucune"),
        "Règles de modification : seules les séances de statut `todo` ou `exported` peuvent être "
        "modifiées (op modify, avec session_id) ou supprimées (op remove) ; les séances `done`, "
        "`missed` ou `sync_error` sont intouchables. Une séance `exported` reste dans sa semaine ; "
        "chaque session_id apparaît au plus une fois. Un ajout (op add) ou une modification doit "
        f"respecter le maximum de {cycle.sessions_per_week} séances par semaine et viser la semaine "
        f"{current_week} ou une suivante.",
        _history_text(history),
    ]
    parts += [t for t in race_texts if t]
    parts.append("Schéma JSON attendu :\n" + _schema_text(AdjustmentResponse))
    return "\n\n".join(parts)
