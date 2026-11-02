"""Prompts de génération et d'ajustement envoyés à Claude (contexte compact en français)."""

import datetime as dt
import json
from typing import get_args

from coach.analysis.laps import StepComparison, StepResult
from coach.analysis.race_plan import RacePlan
from coach.analysis.zones import Zones
from coach.llm.schemas import AdjustmentResponse, PlanResponse, Weekday
from coach.plan.calendar import week_of
from coach.plan.models import Activity, Goal, Session

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


def _goal_text(goal: Goal) -> str:
    text = (
        f"Objectif : course de type {goal.type}, {goal.distance_km:g} km, "
        f"{goal.d_plus_m} m de D+, le {goal.race_date.isoformat()}. "
        f"Le plan débute le {goal.plan_start.isoformat()}."
    )
    if goal.target_time_s is not None:
        text += f" Temps visé : {_fmt_duration(goal.target_time_s)}."
    return text


def _today_text(goal: Goal, today: dt.date) -> str:
    """« Aujourd'hui : mercredi 4 novembre 2026 (semaine 1). »"""
    week = week_of(goal, today)
    return (
        f"Aujourd'hui : {_WEEKDAYS[today.weekday()]} {today.day} {_MONTHS[today.month - 1]} "
        f"{today.year} (semaine {week})."
    )


def _fmt_duration(s: int) -> str:
    """« 5 h 12 » (arrondi à la minute)."""
    h, m = divmod(round(s / 60), 60)
    return f"{h} h {m:02d}"


def race_text(plan: RacePlan) -> str | None:
    """Résumé indicatif de la stratégie du jour J ; None sans temps de référence."""
    if plan.reference_time_s is None:
        return None
    times = []
    if plan.predicted_time_s is not None:
        times.append(f"temps prévu {_fmt_duration(plan.predicted_time_s)}")
    if plan.target_time_s is not None:
        times.append(f"visé {_fmt_duration(plan.target_time_s)}")
    text = "Stratégie jour J (indicative) : " + ", ".join(times)
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
    goal: Goal,
    zones: Zones,
    history: list[Activity],
    n_weeks: int,
    gpx_text: str | None,
    today: dt.date | None = None,
    race_text: str | None = None,
) -> str:
    """Prompt de génération du plan complet ; `today` situe le jour courant dans la semaine 1."""
    parts = [
        _goal_text(goal) + (" " + _today_text(goal, today) if today is not None else ""),
        f"Construis un plan de {n_weeks} semaines, avec au plus {goal.sessions_per_week} séances "
        f"par semaine ({goal.sessions_per_week} séances). Aujourd'hui correspond à la semaine 1 ; "
        f"la dernière semaine se termine à la course. Numérote les semaines de 1 à {n_weeks} "
        "et les séances de chaque semaine à partir de 1 (champ order).",
    ]
    if goal.target_time_s is not None:
        parts.append("Construis le plan pour atteindre ce temps visé (allures cibles, volume).")
    elif goal.target_source == "claude":
        parts.append(
            "Estime d'abord un temps réaliste pour cette course d'après l'historique et les zones, "
            "indique-le dans estimated_time_s (en secondes), puis construis le plan pour ce temps."
        )
    parts += [
        _zones_text(zones),
        _history_text(history),
    ]
    if gpx_text:
        parts.append("Profil du parcours (GPX) :\n" + gpx_text)
    if race_text:
        parts.append(race_text)
    parts.append("Schéma JSON attendu :\n" + _schema_text(PlanResponse))
    return "\n\n".join(parts)


def _session_line(s: Session) -> str:
    return (
        f"id={s.id} | semaine {s.week_index} | {s.type} | {s.title} | "
        f"statut {s.status} | date {s.scheduled_date or '-'}"
    )


def _done_line(s: Session, a: Activity) -> str:
    return f"- prévu : {s.title} ({s.type}) -> réalisé : " + _activity_line(a)[2:]


def _done_block(s: Session, a: Activity, comparisons: dict[int, StepComparison]) -> str:
    comparison = comparisons.get(s.id)
    if comparison is None:
        return _done_line(s, a)
    detail = [_INDENT + line for line in _comparison_lines(comparison)]
    return "\n".join([_done_line(s, a), *detail])


def build_adjustment_prompt(
    goal: Goal,
    zones: Zones,
    current_week: int,
    done: list[tuple[Session, Activity]],
    missed: list[Session],
    upcoming: list[Session],
    history: list[Activity],
    comparisons: dict[int, StepComparison] | None = None,
    race_text: str | None = None,
    change_note: str | None = None,
) -> str:
    """Prompt de proposition d'ajustements après une synchronisation.

    `comparisons` (clé = Session.id) ajoute le détail par étape sous les séances réalisées concernées.
    `change_note` signale une modification de l'objectif, insérée juste après le descriptif de l'objectif.
    """
    comparisons = comparisons or {}
    parts = [
        _goal_text(goal),
        *([change_note] if change_note else []),
        f"Nous sommes en semaine {current_week} du plan, à raison de {goal.sessions_per_week} séances "
        "maximum par semaine. Analyse les séances réalisées et manquées, puis propose des ajustements "
        "pour les séances à venir (liste vide si aucun changement n'est utile).",
        _zones_text(zones),
        "Séances réalisées (prévu -> réalisé) :\n"
        + ("\n".join(_done_block(s, a, comparisons) for s, a in done) if done else "aucune")
        + (f"\n{_DETAIL_RULE}" if comparisons else ""),
        "Séances manquées :\n"
        + ("\n".join(f"- {s.title} ({s.type}, semaine {s.week_index})" for s in missed) if missed else "aucune"),
        "Séances à venir :\n" + ("\n".join(_session_line(s) for s in upcoming) if upcoming else "aucune"),
        "Règles de modification : seules les séances de statut `todo` ou `exported` peuvent être "
        "modifiées (op modify, avec session_id) ou supprimées (op remove) ; les séances `done`, "
        "`missed` ou `sync_error` sont intouchables. Une séance `exported` reste dans sa semaine ; "
        "chaque session_id apparaît au plus une fois. Un ajout (op add) ou une modification doit "
        f"respecter le maximum de {goal.sessions_per_week} séances par semaine et viser la semaine "
        f"{current_week} ou une suivante.",
        _history_text(history),
    ]
    if race_text:
        parts.append(race_text)
    parts.append("Schéma JSON attendu :\n" + _schema_text(AdjustmentResponse))
    return "\n\n".join(parts)
