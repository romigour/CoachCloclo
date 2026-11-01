from datetime import date, timedelta

from coach.analysis.laps import compare_session
from coach.analysis.zones import compute_zones
from coach.garmin.port import LapSummary
from coach.llm.prompts import SYSTEM_PROMPT, build_adjustment_prompt, build_generation_prompt
from coach.llm.schemas import RepeatSpec, StepSpec
from tests.llm.factories import make_session
from tests.plan.factories import make_activity, make_db_session, make_goal

ZONES = compute_zones(
    threshold_pace_s_km=240, pred_10k_s=None, garmin_hr_zones=None, hr_max=190, hr_rest=50
)
ZONES_NO_PACE = compute_zones(
    threshold_pace_s_km=None, pred_10k_s=None, garmin_hr_zones=None, hr_max=190, hr_rest=50
)


def _db(id_, **kw):
    s = make_db_session(1, **kw)
    s.id = id_
    return s


def test_generation_prompt_contains_constraints():
    p = build_generation_prompt(make_goal(), ZONES, [], n_weeks=14, gpx_text="2 montées…")
    for needle in ["14 semaines", "3 séances", "trail", "2 montées", '"weeks"', "Z2", "seuil :", "semaine 1"]:
        assert needle in p
    assert p.rstrip().endswith("}")


def test_generation_prompt_states_today_with_weekday():
    goal = make_goal(plan_start=date(2026, 11, 2))
    p = build_generation_prompt(goal, ZONES, [], n_weeks=14, gpx_text=None, today=date(2026, 11, 4))
    assert "Aujourd'hui : mercredi 4 novembre 2026 (semaine 1)" in p


def test_generation_prompt_without_pace_zones_forbids_pace():
    p = build_generation_prompt(make_goal(type="route"), ZONES_NO_PACE, [], n_weeks=8, gpx_text=None)
    assert "Aucune zone d'allure" in p
    assert "hr" in p


def test_generation_prompt_with_pace_has_no_missing_phrase():
    p = build_generation_prompt(make_goal(), ZONES, [], n_weeks=8, gpx_text=None)
    assert "Aucune zone d'allure" not in p


def test_history_limited_to_8_weeks_most_recent_first_and_capped():
    last = date(2026, 11, 10)
    acts = [make_activity(garmin_activity_id=i, date=last - timedelta(days=i)) for i in range(0, 70)]
    p = build_generation_prompt(make_goal(), ZONES, acts, n_weeks=8, gpx_text=None)
    lines = [l for l in p.splitlines() if l.startswith("- 2026-")]
    assert 0 < len(lines) <= 56
    assert lines[0].startswith("- 2026-11-10")
    assert lines == sorted(lines, reverse=True)
    assert (last - timedelta(days=60)).isoformat() not in p


def test_history_capped_at_60_lines():
    last = date(2026, 11, 10)
    acts = [make_activity(garmin_activity_id=i, date=last) for i in range(100)]
    p = build_generation_prompt(make_goal(), ZONES, acts, n_weeks=8, gpx_text=None)
    assert len([l for l in p.splitlines() if l.startswith("- 2026-")]) == 60


def test_adjustment_prompt_lists_ids_and_status():
    s1, s2, s3, s4 = _db(1), _db(2), _db(3), _db(4)
    s3.status = "exported"
    s3.scheduled_date = date(2026, 11, 12)
    a1 = make_activity(d_plus_m=120, avg_hr=150)
    p = build_adjustment_prompt(
        make_goal(), ZONES, 4, done=[(s1, a1)], missed=[s2], upcoming=[s3, s4], history=[]
    )
    assert "id=3 | semaine 1 |" in p and "statut exported | date 2026-11-12" in p
    assert "statut todo | date -" in p
    assert "semaine 4" in p and "manquée" in p.lower()
    assert "todo" in p and '"changes"' in p
    assert s1.title in p and "150" in p


def test_system_prompt_forbids_raw_values():
    assert "jamais de valeur" in SYSTEM_PROMPT


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
        make_goal(), zones, 4, done=[(s1, make_activity())], missed=[], upcoming=[], history=[],
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
        laps.append(_lap(2 * i + 1, 3, pace * 0.4, 400))
        if i < 4:
            laps.append(_lap(2 * i + 2, 4, 90, 200))
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
    laps = [_lap(0, 2, 600, 2000, avg_hr=172), _lap(1, 2, 600, 2000, avg_hr=180)]
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
    base = build_adjustment_prompt(make_goal(), ZONES, 4, **args)
    assert build_adjustment_prompt(make_goal(), ZONES, 4, **args, comparisons=None) == base
    assert build_adjustment_prompt(make_goal(), ZONES, 4, **args, comparisons={}) == base
    other = {2: compare_session(make_session(), [], ZONES)}
    assert build_adjustment_prompt(make_goal(), ZONES, 4, **args, comparisons=other).count("    ·") == 0
    assert DETAIL_RULE not in base


def test_adjustment_prompt_mentions_step_detail_rule():
    p = _adjustment(compare_session(make_session(), [_lap(0, 1, 600, 1800)], ZONES))
    assert DETAIL_RULE in p
