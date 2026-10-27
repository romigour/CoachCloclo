"""Prompts de génération et d'ajustement envoyés à Claude (contexte compact en français)."""

import datetime as dt
import json

from coach.analysis.zones import Zones
from coach.llm.schemas import AdjustmentResponse, PlanResponse
from coach.plan.models import Activity, Goal, Session

HISTORY_WEEKS = 8
HISTORY_MAX_LINES = 60

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
    return (
        f"Objectif : course de type {goal.type}, {goal.distance_km:g} km, "
        f"{goal.d_plus_m} m de D+, le {goal.race_date.isoformat()}. "
        f"Le plan débute le {goal.plan_start.isoformat()}."
    )


def _schema_text(model) -> str:
    return json.dumps(model.model_json_schema(), ensure_ascii=False)


def build_generation_prompt(
    goal: Goal, zones: Zones, history: list[Activity], n_weeks: int, gpx_text: str | None
) -> str:
    """Prompt de génération du plan complet."""
    parts = [
        _goal_text(goal),
        f"Construis un plan de {n_weeks} semaines, avec au plus {goal.sessions_per_week} séances "
        f"par semaine ({goal.sessions_per_week} séances). Aujourd'hui correspond à la semaine 1 ; "
        f"la dernière semaine se termine à la course. Numérote les semaines de 1 à {n_weeks} "
        "et les séances de chaque semaine à partir de 1 (champ order).",
        _zones_text(zones),
        _history_text(history),
    ]
    if gpx_text:
        parts.append("Profil du parcours (GPX) :\n" + gpx_text)
    parts.append("Schéma JSON attendu :\n" + _schema_text(PlanResponse))
    return "\n\n".join(parts)


def _session_line(s: Session) -> str:
    return (
        f"id={s.id} | semaine {s.week_index} | {s.type} | {s.title} | "
        f"statut {s.status} | date {s.scheduled_date or '-'}"
    )


def _done_line(s: Session, a: Activity) -> str:
    return f"- prévu : {s.title} ({s.type}) -> réalisé : " + _activity_line(a)[2:]


def build_adjustment_prompt(
    goal: Goal,
    zones: Zones,
    current_week: int,
    done: list[tuple[Session, Activity]],
    missed: list[Session],
    upcoming: list[Session],
    history: list[Activity],
) -> str:
    """Prompt de proposition d'ajustements après une synchronisation."""
    parts = [
        _goal_text(goal),
        f"Nous sommes en semaine {current_week} du plan, à raison de {goal.sessions_per_week} séances "
        "maximum par semaine. Analyse les séances réalisées et manquées, puis propose des ajustements "
        "pour les séances à venir (liste vide si aucun changement n'est utile).",
        _zones_text(zones),
        "Séances réalisées (prévu -> réalisé) :\n"
        + ("\n".join(_done_line(s, a) for s, a in done) if done else "aucune"),
        "Séances manquées :\n"
        + ("\n".join(f"- {s.title} ({s.type}, semaine {s.week_index})" for s in missed) if missed else "aucune"),
        "Séances à venir :\n" + ("\n".join(_session_line(s) for s in upcoming) if upcoming else "aucune"),
        "Règles de modification : seules les séances de statut `todo` ou `exported` peuvent être "
        "modifiées (op modify, avec session_id) ou supprimées (op remove) ; les séances `done`, "
        "`missed` ou `sync_error` sont intouchables. Un ajout (op add) doit respecter le maximum de "
        f"{goal.sessions_per_week} séances par semaine et viser la semaine {current_week} ou une suivante.",
        _history_text(history),
        "Schéma JSON attendu :\n" + _schema_text(AdjustmentResponse),
    ]
    return "\n\n".join(parts)
