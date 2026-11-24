from datetime import date, timedelta

from coach.analysis.laps import compare_session
from coach.analysis.race_plan import RacePlan, Segment
from coach.analysis.zones import compute_zones
from coach.garmin.port import LapSummary
from coach.llm.prompts import PRIORITY_RULES, RACE_DAY_RULE, SYSTEM_PROMPT, _session_line, build_adjustment_prompt, build_generation_prompt, race_text
from coach.llm.schemas import RepeatSpec, StepSpec
from coach.plan.constraints import PlanConstraints
from coach.plan.models import Event
from tests.llm.factories import make_session
from tests.plan.factories import make_activity, make_cycle, make_db_session, make_goal

ZONES = compute_zones(
    threshold_pace_s_km=240, pred_10k_s=None, hr_max=190, hr_rest=50
)
ZONES_NO_PACE = compute_zones(
    threshold_pace_s_km=None, pred_10k_s=None, hr_max=190, hr_rest=50
)


def _db(id_, **kw):
    s = make_db_session(1, **kw)
    s.id = id_
    return s


def test_generation_prompt_contains_constraints():
    p = build_generation_prompt(make_cycle(), [make_goal()], [], ZONES, [], n_weeks=14, gpx_texts=["2 montées…"])
    for needle in ["14 semaines", "3 séances", "trail", "2 montées", '"weeks"', "Z2", "seuil :", "semaine 1"]:
        assert needle in p
    assert p.rstrip().endswith("}")


def test_generation_prompt_states_today_with_weekday():
    cycle = make_cycle(plan_start=date(2026, 11, 2))
    p = build_generation_prompt(cycle, [make_goal()], [], ZONES, [], n_weeks=14, gpx_texts=[], today=date(2026, 11, 4))
    assert "Aujourd'hui : mercredi 4 novembre 2026 (semaine 1)" in p


def test_generation_prompt_mid_week_forbids_past_days():
    """Départ en milieu de semaine : les jours déjà passés de la semaine courante sont exclus."""
    cycle = make_cycle(plan_start=date(2026, 11, 9))
    p = build_generation_prompt(cycle, [make_goal()], [], ZONES, [], n_weeks=14, gpx_texts=[],
                                today=date(2026, 11, 17), first_week=2)
    assert ("En semaine 2, lundi est déjà passé : aucune séance ce jour-là "
            "(la première séance tombe au plus tôt aujourd'hui, mardi).") in p


def test_generation_prompt_on_monday_has_no_past_days_rule():
    cycle = make_cycle(plan_start=date(2026, 11, 9))
    p = build_generation_prompt(cycle, [make_goal()], [], ZONES, [], n_weeks=14, gpx_texts=[],
                                today=date(2026, 11, 16), first_week=2)
    assert "déjà passé" not in p


def test_generation_prompt_without_pace_zones_forbids_pace():
    p = build_generation_prompt(make_cycle(), [make_goal(type="route")], [], ZONES_NO_PACE, [], n_weeks=8, gpx_texts=[])
    assert "Aucune zone d'allure" in p
    assert "hr" in p


def test_generation_prompt_with_pace_has_no_missing_phrase():
    p = build_generation_prompt(make_cycle(), [make_goal()], [], ZONES, [], n_weeks=8, gpx_texts=[])
    assert "Aucune zone d'allure" not in p


def test_history_limited_to_8_weeks_most_recent_first_and_capped():
    last = date(2026, 11, 10)
    acts = [make_activity(garmin_activity_id=i, date=last - timedelta(days=i)) for i in range(0, 70)]
    p = build_generation_prompt(make_cycle(), [make_goal()], [], ZONES, acts, n_weeks=8, gpx_texts=[])
    lines = [l for l in p.splitlines() if l.startswith("- 2026-")]
    assert 0 < len(lines) <= 56
    assert lines[0].startswith("- 2026-11-10")
    assert lines == sorted(lines, reverse=True)
    assert (last - timedelta(days=60)).isoformat() not in p


def test_history_capped_at_60_lines():
    last = date(2026, 11, 10)
    acts = [make_activity(garmin_activity_id=i, date=last) for i in range(100)]
    p = build_generation_prompt(make_cycle(), [make_goal()], [], ZONES, acts, n_weeks=8, gpx_texts=[])
    assert len([l for l in p.splitlines() if l.startswith("- 2026-")]) == 60


def test_adjustment_prompt_lists_ids_and_status():
    s1, s2, s3, s4 = _db(1), _db(2), _db(3), _db(4)
    s3.status = "exported"
    s3.scheduled_date = date(2026, 11, 12)
    a1 = make_activity(d_plus_m=120, avg_hr=150)
    p = build_adjustment_prompt(
        make_cycle(), [make_goal()], [], ZONES, 4, done=[(s1, a1)], missed=[s2], upcoming=[s3, s4], history=[]
    )
    assert "id=3 | semaine 1 |" in p and "statut exported | date 2026-11-12" in p
    assert "statut todo | date -" in p
    assert "semaine 4" in p and "manquée" in p.lower()
    assert "todo" in p and '"changes"' in p
    assert s1.title in p and "150" in p


def test_system_prompt_forbids_raw_values():
    assert "jamais de valeur" in SYSTEM_PROMPT


def _segment(index, kind, start_km, d_plus_m):
    return Segment(
        kind=kind, start_km=start_km, end_km=start_km + 1, eq_km=1, d_plus_m=d_plus_m, d_minus_m=0,
        index=index, avg_grade_pct=0, time_s=None, pace_s_km=None, elapsed_s=None, clock=None,
        target_kind="hr", target_low=None, target_high=None, target_zone=None,
    )


def _race_plan(*, estimate=18720, target=18000):
    segments = [
        _segment(0, "montée", 12.4, 450),
        _segment(1, "plat", 20, 0),
        _segment(2, "montée", 30.6, 600),
        _segment(3, "montée", 5, 100),
        _segment(4, "montée", 8, 50),
        _segment(5, "montée", 40, 20),
    ]
    return RacePlan(
        distance_km=42, eq_km=50, stops_s=0, target_time_s=target,
        reference_time_s=target if target is not None else estimate,
        segments=segments, aid_passages=[], nutrition=[], warnings=[],
    )


def test_race_text_format():
    assert race_text(_race_plan()) == (
        "Stratégie jour J (indicative) : visé 5 h 00 ; "
        "montées clés km 5 (+100 m), km 12 (+450 m) et km 31 (+600 m). "
        "N'en tenir compte que pour orienter légèrement le contenu de l'affûtage, "
        "sans modifier la structure ni le volume du plan."
    )


def test_race_text_without_target():
    text = race_text(_race_plan(target=None))
    assert "temps estimé 5 h 12" in text
    assert "visé" not in text


def test_race_text_without_climbs():
    plan = _race_plan()
    plan.segments = []
    text = race_text(plan)
    assert text.startswith("Stratégie jour J (indicative) : visé 5 h 00. N'en tenir")
    assert "estimé" not in text and "montées" not in text


def test_race_text_none_without_reference():
    plan = _race_plan(estimate=None, target=None)
    assert race_text(plan) is None


def test_prompts_include_race_text():
    line = "Stratégie jour J (indicative) : visé 5 h 00."
    goal = make_goal()
    gen = build_generation_prompt(make_cycle(), [goal], [], ZONES, [], n_weeks=14, gpx_texts=[], race_texts=[line])
    adj = build_adjustment_prompt(make_cycle(), [goal], [], ZONES, 1, [], [], [], [], race_texts=[line])
    for p in (gen, adj):
        assert line in p
        assert p.index(line) < p.index("Schéma JSON attendu")
    assert "Stratégie jour J" not in build_generation_prompt(make_cycle(), [goal], [], ZONES, [], n_weeks=14, gpx_texts=[])
    assert "Stratégie jour J" not in build_adjustment_prompt(make_cycle(), [goal], [], ZONES, 1, [], [], [], [])


# --- détail par étape ---

ZONES_VMA = ZONES.model_copy(update={"pace": {**ZONES.pace, "VMA": (220, 235)}})
DETAIL_RULE = (
    "Le détail par étape compare le réalisé aux zones cibles ; "
    "appuie ton analyse dessus quand il est présent."
)


def _lap(index, step_order, duration_s, distance_m, avg_hr=None):
    pace = duration_s / (distance_m / 1000)
    return LapSummary(
        index=index, duration_s=duration_s, distance_m=distance_m,
        avg_hr=avg_hr, avg_pace_s_km=pace, step_order=step_order,
    )


def _adjustment(comparison, zones=ZONES_VMA):
    s1 = _db(1)
    return build_adjustment_prompt(
        make_cycle(), [make_goal()], [], zones, 4, done=[(s1, make_activity())], missed=[], upcoming=[], history=[],
        comparisons={1: comparison},
    )


def test_adjustment_prompt_details_workout_steps():
    spec = make_session(
        target_kind="pace",
        steps=[
            StepSpec(kind="warmup", duration_s=900),
            RepeatSpec(
                repeat=6,
                steps=[
                    StepSpec(kind="active", distance_m=400, zone="VMA"),
                    StepSpec(kind="recovery", duration_s=90),
                ],
            ),
        ],
    )
    laps = [_lap(0, 1, 902, 902 / 331 * 1000, avg_hr=138)]
    for i, pace in enumerate([228, 230, 232, 238, 241]):
        laps.append(_lap(2 * i + 1, 2, pace * 0.4, 400))
        if i < 4:
            laps.append(_lap(2 * i + 2, 3, 90, 200))
    p = _adjustment(compare_session(spec, laps, ZONES_VMA))
    assert "\n    · échauffement 15 min : 15:02, 5:31/km, 138 bpm\n" in p
    assert (
        "\n    · 6× actif 400 m VMA [3:40–3:55/km] : "
        "3:48, 3:50, 3:52, 3:58 (trop lent), 4:01 (trop lent), non réalisée\n"
    ) in p
    assert "\n    · 6× récup 90 s : " in p
    assert DETAIL_RULE in p


def test_adjustment_prompt_hr_target_lists_bpm():
    spec = make_session(
        steps=[RepeatSpec(repeat=3, steps=[StepSpec(kind="active", duration_s=600, zone="Z4")])],
    )
    laps = [_lap(0, 1, 600, 2000, avg_hr=172), _lap(1, 1, 600, 2000, avg_hr=180)]
    p = _adjustment(compare_session(spec, laps, ZONES_VMA))
    assert "    · 3× actif 10 min Z4 [162–176 bpm] : 172 bpm, 180 bpm (FC trop haute), non réalisée" in p


def test_adjustment_prompt_degraded_caps_at_30_laps():
    spec = make_session()
    laps = [_lap(i, None, 300, 1000, avg_hr=150) for i in range(35)]
    p = _adjustment(compare_session(spec, laps, ZONES_VMA))
    assert "\n    séance non suivie sur la montre, tours :\n" in p
    assert "\n    · tour 1 : 1000 m, 5:00, 5:00/km, 150 bpm\n" in p
    assert p.count("    · tour ") == 30
    assert "· tour 31" not in p
    assert "\n    … 5 tours de plus" in p


def test_adjustment_prompt_degraded_without_any_lap_has_no_dangling_header():
    p = _adjustment(compare_session(make_session(), [], ZONES_VMA))
    assert "\n    séance non suivie sur la montre : aucun tour enregistré" in p
    assert "tours :" not in p


def test_adjustment_prompt_without_comparison_unchanged():
    s1 = _db(1)
    args = dict(done=[(s1, make_activity())], missed=[], upcoming=[], history=[])
    base = build_adjustment_prompt(make_cycle(), [make_goal()], [], ZONES, 4, **args)
    assert build_adjustment_prompt(make_cycle(), [make_goal()], [], ZONES, 4, **args, comparisons=None) == base
    assert build_adjustment_prompt(make_cycle(), [make_goal()], [], ZONES, 4, **args, comparisons={}) == base
    other = {2: compare_session(make_session(), [], ZONES)}
    assert build_adjustment_prompt(make_cycle(), [make_goal()], [], ZONES, 4, **args, comparisons=other).count("    ·") == 0
    assert DETAIL_RULE not in base


def test_adjustment_prompt_mentions_step_detail_rule():
    p = _adjustment(compare_session(make_session(), [_lap(0, 1, 600, 1800)], ZONES))
    assert DETAIL_RULE in p


def test_goal_text_includes_target():
    from coach.llm.prompts import _goals_text

    assert "Temps visé : 1 h 50" in _goals_text([make_goal(target_time_s=6600, target_source="user")], [])
    assert "Temps visé" not in _goals_text([make_goal()], [])


def test_generation_prompt_asks_estimate_in_claude_mode():
    p = build_generation_prompt(
        make_cycle(), [make_goal(id=1, target_source="claude")], [], ZONES, [], n_weeks=14, gpx_texts=[]
    )
    assert "indique-le dans estimated_times (goal_id 1, en secondes)" in p and "Estime" in p


def test_generation_prompt_regeneration_in_claude_mode_asks_estimate_again():
    goal = make_goal(id=1, target_source="claude", target_time_s=6720)
    p = build_generation_prompt(make_cycle(), [goal], [], ZONES, [], n_weeks=14, gpx_texts=[])
    assert "estimated_times (goal_id 1" in p
    assert "Construis le plan pour atteindre ce temps visé" not in p
    assert "Temps visé" not in p and "Estimation précédente : 1 h 52" in p


def test_generation_prompt_targets_user_time():
    goal = make_goal(target_time_s=6600, target_source="user")
    p = build_generation_prompt(make_cycle(), [goal], [], ZONES, [], n_weeks=14, gpx_texts=[])
    assert "Construis le plan pour atteindre ce temps visé" in p and "Estime" not in p


def test_generation_prompt_legacy_goal_has_no_target_instruction():
    p = build_generation_prompt(make_cycle(), [make_goal()], [], ZONES, [], n_weeks=14, gpx_texts=[])
    assert "Estime" not in p and "atteindre ce temps visé" not in p


def test_adjustment_prompt_includes_change_note():
    p = build_adjustment_prompt(
        make_cycle(), [make_goal()], [], ZONES, 4, [], [], [], [], change_note="L'athlète a modifié son objectif : X"
    )
    assert p.index("L'athlète a modifié") < p.index("Nous sommes en semaine")


def test_prompts_list_availability_and_session_day():
    c = PlanConstraints(available_days=("mardi", "jeudi", "dimanche"), long_run_day="dimanche", today=date(2026, 11, 2))
    p = build_adjustment_prompt(make_cycle(), [make_goal()], [], ZONES, 1, [], [], [_db(1)], [], constraints=c)
    assert "Jours possibles : mardi, jeudi, dimanche" in p
    assert "Sortie longue : le dimanche" in p
    assert "| mardi |" in p  # _session_line affiche le jour conseillé
    g = build_generation_prompt(make_cycle(), [make_goal()], [], ZONES, [], n_weeks=14, gpx_texts=[], constraints=c)
    assert "Jours possibles : mardi, jeudi, dimanche" in g


def test_availability_block_omits_long_run_when_unset():
    c = PlanConstraints(available_days=("mardi", "jeudi"), long_run_day=None, today=date(2026, 11, 2))
    p = build_generation_prompt(make_cycle(), [make_goal()], [], ZONES, [], n_weeks=14, gpx_texts=[], constraints=c)
    assert "Jours possibles : mardi, jeudi." in p and "Sortie longue" not in p


def _events_prompt(*events, today=date(2026, 11, 2)):
    c = PlanConstraints(
        available_days=("mardi", "samedi"), long_run_day=None, today=today,
        events=tuple(events), plan_start=date(2026, 10, 19),
    )
    return build_generation_prompt(make_cycle(), [make_goal()], [], ZONES, [], n_weeks=14, gpx_texts=[], constraints=c)


def test_events_block_formats_each_kind():
    p = _events_prompt(
        Event(cycle_id=1, kind="unavailable", start_date=date(2026, 11, 5), end_date=date(2026, 11, 12), note="voyage"),
        Event(cycle_id=1, kind="injury", start_date=date(2026, 11, 3), note="genou"),
        Event(
            goal_id=1, kind="light_week", start_date=date(2026, 11, 2), end_date=date(2026, 11, 8),
            max_sessions=2, days_json='["mardi", "samedi"]',
        ),
        Event(cycle_id=1, kind="fatigue", start_date=date(2026, 11, 2), note="jambes lourdes"),
    )
    assert "Imprévus :" in p
    assert "- indisponible du 05/11/2026 au 12/11/2026 : voyage" in p
    assert "- blessure/maladie depuis le 03/11/2026 (reprise non connue) : genou" in p
    assert "- semaine allégée (semaine 3) : 2 séances au plus, jours possibles mardi, samedi" in p
    assert "- fatigue signalée le 02/11/2026 : jambes lourdes" in p
    # après les disponibilités, ordre chronologique
    assert p.index("Disponibilités") < p.index("Imprévus :")
    assert p.index("fatigue signalée") < p.index("blessure/maladie") < p.index("indisponible du")


def test_events_block_omits_optional_parts():
    p = _events_prompt(
        Event(cycle_id=1, kind="unavailable", start_date=date(2026, 11, 5), end_date=date(2026, 11, 12)),
        Event(cycle_id=1, kind="light_week", start_date=date(2026, 11, 2), end_date=date(2026, 11, 8), max_sessions=1),
    )
    assert "- indisponible du 05/11/2026 au 12/11/2026" + "\n" in p + "\n"
    assert "- semaine allégée (semaine 3) : 1 séance au plus" in p
    assert "jours possibles" not in p.split("Imprévus :")[1].split("\n\n")[0]


def test_events_block_excludes_past_and_old_fatigue():
    p = _events_prompt(
        Event(cycle_id=1, kind="unavailable", start_date=date(2026, 10, 20), end_date=date(2026, 10, 25), note="passé"),
        Event(cycle_id=1, kind="fatigue", start_date=date(2026, 10, 10), note="ancienne"),
    )
    assert "Imprévus" not in p


def test_events_block_keeps_fatigue_within_14_days():
    p = _events_prompt(Event(cycle_id=1, kind="fatigue", start_date=date(2026, 10, 19), note="limite"))
    assert "- fatigue signalée le 19/10/2026 : limite" in p


def test_adjustment_prompt_includes_events_block():
    c = PlanConstraints(
        available_days=("mardi",), long_run_day=None, today=date(2026, 11, 2),
        events=(Event(cycle_id=1, kind="injury", start_date=date(2026, 11, 3)),),
    )
    p = build_adjustment_prompt(make_cycle(), [make_goal()], [], ZONES, 1, [], [], [], [], constraints=c)
    assert "- blessure/maladie depuis le 03/11/2026 (reprise non connue)" in p


def _bike_prompts(include_bike):
    c = PlanConstraints(
        available_days=("mardi", "samedi"), long_run_day=None, today=date(2026, 11, 2), include_bike=include_bike
    )
    g = build_generation_prompt(make_cycle(), [make_goal()], [], ZONES, [], n_weeks=14, gpx_texts=[], constraints=c)
    a = build_adjustment_prompt(make_cycle(), [make_goal()], [], ZONES, 1, [], [], [_db(1)], [], constraints=c)
    return g, a


def test_prompts_allow_bike_when_included():
    for p in _bike_prompts(True):
        assert "Vélo autorisé : tu peux remplacer au plus une séance EF ou récup par semaine" in p
        assert "1,3 à 1,5 fois" in p
        assert "Toutes les séances sont en course à pied" not in p


def test_prompts_state_run_only_without_bike():
    for p in _bike_prompts(False):
        assert 'Toutes les séances sont en course à pied (sport "run").' in p
        assert "Vélo autorisé" not in p


def test_prompts_without_constraints_mention_no_sport_rule():
    g = build_generation_prompt(make_cycle(), [make_goal()], [], ZONES, [], n_weeks=14, gpx_texts=[])
    assert "Vélo autorisé" not in g and "course à pied" not in g


def test_session_line_flags_bike():
    assert _session_line(_db(1, sport="bike")).endswith(" | vélo")
    assert "vélo" not in _session_line(_db(1))


def test_prompts_ask_bike_steps_in_duration_only():
    for p in _bike_prompts(True):
        assert "étapes en durée uniquement" in p


def test_missed_sessions_flag_bike():
    run, bike = _db(1, title="Course ratée"), _db(2, sport="bike", title="Vélo raté")
    p = build_adjustment_prompt(make_cycle(), [make_goal()], [], ZONES, 4, [], [run, bike], [], [])
    assert f"- Vélo raté ({bike.type}, vélo, semaine {bike.week_index})" in p
    assert f"- Course ratée ({run.type}, semaine {run.week_index})" in p


def test_prompts_read_plan_settings_from_cycle():
    """Début du plan et séances par semaine viennent du cycle, plus de l'objectif."""
    cycle = make_cycle(plan_start=date(2026, 11, 9), sessions_per_week=5)
    goal = make_goal(plan_start=date(2026, 10, 26), sessions_per_week=3)
    gen = build_generation_prompt(cycle, [goal], [], ZONES, [], n_weeks=12, gpx_texts=["A", "B"], race_texts=["R1"])
    adj = build_adjustment_prompt(cycle, [goal], [], ZONES, 1, [], [], [], [])
    for p in (gen, adj):
        assert "Le plan débute le 2026-11-09." in p and "5 séances" in p and "3 séances" not in p
    assert "Profil du parcours (GPX) :\nA" in gen and "Profil du parcours (GPX) :\nB" in gen and "R1" in gen


def _first_part(prompt: str) -> str:
    return prompt.split("\n\n")[0]


def test_goal_line_exact_order_with_user_time():
    """Ordre exact : date de course, début du plan, puis temps visé (texte d'avant les cycles)."""
    goal = make_goal(target_time_s=6600, target_source="user")
    line = "Objectif : course de type trail, 42 km, 2000 m de D+, le 2027-01-31. Le plan débute le 2026-10-26."
    gen = build_generation_prompt(make_cycle(), [goal], [], ZONES, [], n_weeks=14, gpx_texts=[], today=date(2026, 11, 4))
    assert _first_part(gen) == line + " Temps visé : 1 h 50. Aujourd'hui : mercredi 4 novembre 2026 (semaine 2)."
    adj = build_adjustment_prompt(make_cycle(), [goal], [], ZONES, 2, [], [], [], [])
    assert _first_part(adj) == line + " Temps visé : 1 h 50."


def test_goal_line_exact_order_in_claude_estimate_mode():
    goal = make_goal(target_time_s=6720, target_source="claude")
    line = "Objectif : course de type trail, 42 km, 2000 m de D+, le 2027-01-31. Le plan débute le 2026-10-26."
    gen = build_generation_prompt(make_cycle(), [goal], [], ZONES, [], n_weeks=14, gpx_texts=[])
    assert _first_part(gen) == line + " Estimation précédente : 1 h 52."
    adj = build_adjustment_prompt(make_cycle(), [goal], [], ZONES, 2, [], [], [], [])
    assert _first_part(adj) == line + " Temps visé : 1 h 52."


def test_generation_prompt_lists_fixed_sessions():
    fixed =make_db_session(1, week_index=3, order=1)
    fixed.id, fixed.status = 12, "exported"
    p = build_generation_prompt(
        make_cycle(), [make_goal()], [], ZONES, [], n_weeks=14, gpx_texts=[], first_week=3, fixed=[fixed]
    )
    assert (
        "Semaines 3 à 14 seulement : les séances suivantes sont fixées et comptent dans leur semaine :\n"
        + _session_line(fixed)
    ) in p
    assert "Numérote les semaines de 3 à 14" in p
    plain = build_generation_prompt(make_cycle(), [make_goal()], [], ZONES, [], n_weeks=14, gpx_texts=[])
    assert "seulement" not in plain and "Numérote les semaines de 1 à 14" in plain


# --- plusieurs objectifs, priorités et horizon ---

_AVAIL = PlanConstraints(available_days=("mardi", "jeudi", "dimanche"), long_run_day="dimanche", today=date(2026, 11, 4))
_AVAIL_TEXT = (
    "Disponibilités : Jours possibles : mardi, jeudi, dimanche. Sortie longue : le dimanche. "
    'Ne place aucune séance un autre jour. Toutes les séances sont en course à pied (sport "run").'
)
_GEN_TEXT = (
    "Construis un plan de 14 semaines, avec au plus 3 séances par semaine (3 séances). Aujourd'hui correspond "
    "à la semaine 1 ; la dernière semaine se termine à la course. Numérote les semaines de 1 à 14 et les séances "
    "de chaque semaine à partir de 1 (champ order)."
)
_ADJ_TEXT = (
    "Nous sommes en semaine 2 du plan, à raison de 3 séances maximum par semaine. Analyse les séances réalisées "
    "et manquées, puis propose des ajustements pour les séances à venir (liste vide si aucun changement n'est utile)."
)
_LINE = "Objectif : course de type trail, 42 km, 2000 m de D+, le 2027-01-31. Le plan débute le 2026-10-26."


def _head(prompt: str) -> str:
    """Texte du prompt avant les zones."""
    return prompt.split("\n\nZones disponibles")[0]


def _gen(goals, horizon=(), **kw):
    return build_generation_prompt(
        make_cycle(), list(goals), list(horizon), ZONES, [], n_weeks=14, gpx_texts=[], today=date(2026, 11, 4),
        constraints=_AVAIL, **kw,
    )


def _adj_prompt(goals, horizon=(), **kw):
    return build_adjustment_prompt(
        make_cycle(), list(goals), list(horizon), ZONES, 2, [], [], [], [], constraints=_AVAIL, **kw
    )


def test_single_principal_prompt_unchanged():
    """Un seul Principal sans horizon : texte d'avant les cycles, au nom du champ d'estimation et à la règle
    du jour de course près."""
    today = " Aujourd'hui : mercredi 4 novembre 2026 (semaine 2)."
    _PAST_TEXT = ("En semaine 2, lundi et mardi sont déjà passés : aucune séance ce jour-là "
                  "(la première séance tombe au plus tôt aujourd'hui, mercredi).")
    user = make_goal(id=1, target_time_s=6600, target_source="user")
    assert _head(_gen([user])) == "\n\n".join([
        _LINE + " Temps visé : 1 h 50." + today, RACE_DAY_RULE, _AVAIL_TEXT, _GEN_TEXT, _PAST_TEXT,
        "Construis le plan pour atteindre ce temps visé (allures cibles, volume).",
    ])
    assert _head(_adj_prompt([user])) == "\n\n".join(
        [_LINE + " Temps visé : 1 h 50.", RACE_DAY_RULE, _AVAIL_TEXT, _ADJ_TEXT]
    )
    claude = make_goal(id=1, target_source="claude")
    assert _head(_gen([claude])) == "\n\n".join([
        _LINE + today, RACE_DAY_RULE, _AVAIL_TEXT, _GEN_TEXT, _PAST_TEXT,
        "Estime d'abord un temps réaliste pour cette course d'après l'historique et les zones, "
        "indique-le dans estimated_times (goal_id 1, en secondes), puis construis le plan pour ce temps.",
    ])
    estimated = make_goal(id=1, target_source="claude", target_time_s=6720)
    assert _head(_adj_prompt([estimated])) == "\n\n".join(
        [_LINE + " Temps visé : 1 h 52.", RACE_DAY_RULE, _AVAIL_TEXT, _ADJ_TEXT]
    )
    for p in (_gen([user]), _adj_prompt([user])):
        assert PRIORITY_RULES not in p and "Objectifs suivants" not in p


def _secondary(**kw):
    data = dict(id=2, type="route", distance_km=10, d_plus_m=0, race_date=date(2026, 12, 20),
                priority="secondaire", target_source="claude")
    data.update(kw)
    return make_goal(**data)


def test_prompt_lists_goals_with_priority_and_rules():
    principal = make_goal(id=1, target_time_s=6600, target_source="user")
    for p in (_gen([_secondary(), principal]), _adj_prompt([_secondary(), principal])):
        assert (
            "Objectifs du cycle :\n"
            "- 2026-12-20 : route, 10 km, 0 m de D+, priorité Secondaire\n"
            "- 2027-01-31 : trail, 42 km, 2000 m de D+, priorité Principal, temps visé 1 h 50\n"
            "Le plan débute le 2026-10-26."
        ) in p
        assert "Objectif : course" not in p
        assert "\n\n" + PRIORITY_RULES + "\n\n" in p
        assert (
            "Pour chaque objectif sans temps visé (ids 2 (2026-12-20)), estime un temps réaliste dans "
            "estimated_times (en secondes)."
        ) in p
    gen = _gen([_secondary(), principal])
    assert gen.startswith("Objectifs du cycle :\n") and "Le plan débute le 2026-10-26. Aujourd'hui : mercredi" in gen
    assert "Construis le plan pour atteindre les temps visés indiqués (allures cibles, volume)." in gen
    for needle in ("Principal", "Secondaire", "Plaisir", "10 jours", "mini-affûtage", "remplace une séance"):
        assert needle in PRIORITY_RULES
    assert "jour d'une course" not in PRIORITY_RULES  # règle donnée une seule fois (RACE_DAY_RULE)


def test_prompt_rules_for_lone_non_principal_goal():
    p = _gen([_secondary(target_source="user", target_time_s=3000)])
    assert "- 2026-12-20 : route, 10 km, 0 m de D+, priorité Secondaire, temps visé 0 h 50" in p
    assert PRIORITY_RULES in p and "Pour chaque objectif sans temps visé" not in p


def test_prompt_generation_shows_previous_claude_estimate():
    goals = [_secondary(target_time_s=3000), make_goal(id=1, target_source="claude", target_time_s=6720)]
    p = _gen(goals)
    assert "priorité Secondaire, estimation précédente 0 h 50\n" in p
    assert "priorité Principal, estimation précédente 1 h 52\n" in p
    assert "(ids 2 (2026-12-20), 1 (2027-01-31))" in p  # toutes les estimations sont refaites
    adj = _adj_prompt(goals)
    assert "priorité Secondaire, temps visé 0 h 50\n" in adj and "Pour chaque objectif sans temps visé" not in adj


def test_prompt_consecutive_goals_as_block():
    saturday = _secondary(id=2, race_date=date(2027, 1, 30), type="trail", distance_km=20, d_plus_m=500)
    sunday = _secondary(id=3, race_date=date(2027, 1, 31), distance_km=30, priority="plaisir")
    other = _secondary(id=4, race_date=date(2026, 12, 6), priority="plaisir")
    p = _gen([other, saturday, sunday])
    assert "- 2026-12-06 : route, 10 km, 0 m de D+, priorité Plaisir\n" in p
    assert "- 2027-01-30 : trail, 20 km, 500 m de D+, priorité Secondaire\n" in p
    assert "- 2027-01-31 : route, 30 km, 0 m de D+, priorité Plaisir\n" in p
    assert "(enchaînés, à traiter comme un bloc)" not in p
    assert "Bloc Trail de 20 km (30/01) + Course sur route de 30 km (31/01)" in p


def _t(id_, d, prio="secondaire", km=20, dplus=450, **kw):
    return make_goal(
        id=id_, race_date=d, priority=prio, distance_km=km, d_plus_m=dplus, target_source="user",
        target_time_s=7200, **kw,
    )


def test_secondary_rule_is_proportional():
    assert "proportionné" in PRIORITY_RULES
    assert "charge de fond du Principal" in _gen([_t(2, date(2027, 1, 9)), _t(1, date(2027, 1, 31), "principal")])


def test_block_rules_for_weekend():
    sat, sun = _t(2, date(2027, 1, 16)), _t(3, date(2027, 1, 17), km=30, dplus=600)
    for p in (_gen([sat, sun, _t(1, date(2027, 1, 31), "principal")]), _adj_prompt([sat, sun])):
        assert "Bloc Trail de 20 km (16/01) + Trail de 30 km (17/01) (50 km, 1050 m de D+" in p
        for needle in ("un seul défi", "jambes fatiguées", "cumul"):
            assert needle in p
        assert "(enchaînés" not in p


def test_close_group_rules():
    p = _gen([_t(2, date(2027, 1, 2)), _t(3, date(2027, 1, 9)), _t(1, date(2027, 1, 31), "principal")])
    assert "Trail de 20 km (02/01) est intégré à l'affûtage de Trail de 20 km (09/01)" in p
    p = _gen([_t(2, date(2027, 1, 2), "principal"), _t(3, date(2027, 1, 9))])
    assert "Trail de 20 km (09/01) est une course de rebond après Trail de 20 km (02/01)" in p


def test_rebound_after_done_principal():
    done = _t(2, date(2027, 1, 2), "principal", status="done")
    p = _gen([_t(3, date(2027, 1, 9))], recent=[done])
    assert "course de rebond après Trail de 20 km (02/01)" in p
    assert "- 2027-01-02" not in p


def test_day_two_keeps_block_rules_after_day_one_done():
    sat = _t(2, date(2027, 1, 16), status="done")
    sun = _t(3, date(2027, 1, 17), "principal", km=30, dplus=600)
    for p in (_gen([sun], recent=[sat]), _adj_prompt([sun], recent=[sat])):
        assert "un seul défi" in p
        assert "Objectif : course de type" not in p


def test_horizon_end_names_tapered_block():
    ultra = _t(5, date(2027, 5, 15), "principal", km=80, dplus=4000)
    p = _gen([_t(1, date(2027, 1, 10), "principal"), _t(2, date(2027, 1, 18), "principal")], [ultra])
    assert "Termine ce cycle par l'affûtage de Trail de 20 km (18/01) sans anticiper le suivant." in p


def test_horizon_marks_blocks():
    sat, sun = _t(5, date(2027, 3, 27)), _t(6, date(2027, 3, 28), km=30, dplus=600)
    p = _gen([make_goal(id=1)], [sat, sun])
    assert "- 2027-03-27 : trail, 20 km, 450 m de D+, priorité Secondaire (bloc avec Trail de 30 km (28/03))\n" in p


def test_prompt_horizon_principal_line():
    principal = make_goal(id=1, target_time_s=6600, target_source="user")
    ultra = make_goal(id=5, race_date=date(2027, 5, 15), distance_km=80, d_plus_m=4000, target_source="claude")
    later = _secondary(id=6, race_date=date(2027, 6, 13), priority="plaisir")
    for p in (_gen([principal], [ultra, later]), _adj_prompt([principal], [ultra, later])):
        assert (
            "Objectifs suivants (préparés dans un cycle ultérieur, ne pas les anticiper) :\n"
            "- 2027-05-15 : trail, 80 km, 4000 m de D+, priorité Principal\n"
            "- 2027-06-13 : route, 10 km, 0 m de D+, priorité Plaisir\n"
            "Termine ce cycle par l'affûtage de Trail de 42 km (31/01) sans anticiper le suivant."
        ) in p
        # un seul Principal dans le cycle : liste, sans règles de priorité ; l'horizon n'est pas estimé
        assert "- 2027-01-31 : trail, 42 km, 2000 m de D+, priorité Principal, temps visé 1 h 50" in p
        assert PRIORITY_RULES not in p and "ids 5" not in p
    p = _gen([principal], [later])
    assert "Objectifs suivants" in p and "Termine ce cycle" not in p
    # sans Principal dans le cycle, aucun affûtage n'est demandé pour la dernière course
    assert "Termine ce cycle" not in _gen([_secondary()], [ultra])


def test_race_day_rule_in_every_prompt():
    """La règle du jour de course est contrôlée pour tout cycle : elle figure dans chaque prompt, une fois."""
    assert RACE_DAY_RULE == "Aucune séance le jour d'une course ; la course compte comme une séance de sa semaine."
    principal = make_goal(id=1, target_time_s=6600, target_source="user")
    later = make_goal(id=5, race_date=date(2027, 5, 15), distance_km=80, target_source="claude")
    cases = [
        _gen([principal]), _adj_prompt([principal]),  # un seul Principal
        _gen([principal], [later]), _adj_prompt([principal], [later]),  # un seul Principal et un horizon
        _gen([_secondary(), principal]), _adj_prompt([_secondary(), principal]),  # plusieurs objectifs
    ]
    for p in cases:
        assert p.count(RACE_DAY_RULE) == 1
        assert p.count("jour d'une course") == 1


# --- historique long ------------------------------------------------------------------------------

from coach.analysis.long_history import LongHistory, MonthVolume, PastRace  # noqa: E402
from coach.llm.prompts import _fmt_time  # noqa: E402
from coach.plan.models import PersonalRecord  # noqa: E402

LONG = LongHistory(
    months=[
        MonthVolume(date(2026, 11, 1), runs=2, run_km=30.0, run_s=10800, d_plus_m=1000, longest_km=20.0, other_s=5400),
        MonthVolume(date(2026, 10, 1)),
    ],
    races=[PastRace(date(2026, 10, 12), "Trail des Crêtes", 32.0, 1450, 15125, 85, 420)],
    records=[
        PersonalRecord(kind="10k", value=2535, date=date(2025, 4, 6)),
        PersonalRecord(kind="longest_run", value=32400, date=date(2025, 10, 19)),
    ],
)
LONG_LINES = [
    "Historique long (pour situer le niveau de fond et la capacité de charge ; "
    "la forme actuelle reste donnée par l'historique récent) :",
    "Volume mensuel de course à pied (2 derniers mois, plus récent d'abord) :",
    "- novembre 2026 : 2 sorties, 30 km, 3 h 00, D+ 1000 m, plus longue 20.0 km | autres sports 1 h 30",
    "- octobre 2026 : aucune course",
    "Compétitions passées (plus récentes d'abord) :",
    "- 2026-10-12 : Trail des Crêtes, 32.0 km, D+ 1450 m, 4:12:05, classement 85/420",
    "Records personnels :",
    "- 10 km : 42:15 (2025-04-06)",
    "- Plus longue sortie : 32.4 km (2025-10-19)",
]


def _gen_long(**kw):
    return build_generation_prompt(make_cycle(), [make_goal()], [], ZONES, [], n_weeks=8, gpx_texts=[], **kw)


def _adj_long(**kw):
    return build_adjustment_prompt(
        make_cycle(), [make_goal()], [], ZONES, 4, done=[], missed=[], upcoming=[], history=[], **kw
    )


def test_long_history_block_format():
    lines = _gen_long(long_history=LONG).splitlines()
    for line in LONG_LINES:
        assert line in lines


def test_long_history_block_omits_empty_parts():
    lh = LongHistory(
        months=[MonthVolume(date(2026, 11, 1))],
        races=[PastRace(date(2026, 5, 1), None, 10.0, None, 2400, None, None)],
        records=[],
    )
    p = _gen_long(long_history=lh)
    assert "- 2026-05-01 : 10.0 km, 40:00" in p.splitlines()
    assert "Volume mensuel" not in p and "Records personnels" not in p


def test_long_history_single_run_and_other_sports_on_empty_month():
    lh = LongHistory(
        months=[MonthVolume(date(2026, 11, 1), runs=1, run_km=8.4, run_s=2700, longest_km=8.4),
                MonthVolume(date(2026, 10, 1), other_s=7200)],
        races=[], records=[],
    )
    lines = _gen_long(long_history=lh).splitlines()
    assert "- novembre 2026 : 1 sortie, 8 km, 0 h 45, D+ 0 m, plus longue 8.4 km" in lines
    assert "- octobre 2026 : aucune course | autres sports 2 h 00" in lines


def test_long_history_absent_by_default():
    assert "Historique long" not in _gen_long()
    assert "Historique long" not in _adj_long()
    empty = LongHistory(months=[MonthVolume(date(2026, 11, 1))], races=[], records=[])
    assert _gen_long(long_history=empty) == _gen_long()


def test_adjustment_prompt_includes_long_history():
    p = _adj_long(long_history=LONG)
    assert p.index("Historique récent") < p.index("Historique long")


def test_fmt_time():
    assert _fmt_time(2535) == "42:15"
    assert _fmt_time(5712) == "1:35:12"


# --- précisions de l'athlète ---


def test_single_goal_text_includes_notes():
    from coach.llm.prompts import _goals_text

    text = _goals_text([make_goal(target_time_s=6600, target_source="user", notes="Neige\npuis escaliers")], [])
    assert text.endswith("Temps visé : 1 h 50. Précisions de l'athlète : « Neige puis escaliers ».")


def test_goal_line_includes_notes():
    from coach.llm.prompts import _goal_line

    line = _goal_line(make_goal(priority="secondaire", notes="PR visé\r\nsur route"))
    assert line.endswith(", priorité Secondaire. Précisions de l'athlète : « PR visé sur route ».")
    assert "\n" not in line and "\r" not in line


def test_cycle_goals_notes_in_generation_and_adjustment():
    goals = [make_goal(id=1, notes="Escaliers"), make_goal(id=2, priority="secondaire", race_date=date(2026, 12, 20))]
    for p in (_gen(goals), _adj_prompt(goals)):
        assert p.count("Précisions de l'athlète") == 1 and "« Escaliers »" in p


def test_horizon_line_has_no_notes():
    horizon = [make_goal(id=2, race_date=date(2027, 6, 1), notes="Neige")]
    assert "Précisions" not in _gen([make_goal(id=1)], horizon)


def test_no_notes_prompt_unchanged():
    goal = make_goal()
    assert "Précisions" not in _gen([goal]) and "Précisions" not in _adj_prompt([goal])
