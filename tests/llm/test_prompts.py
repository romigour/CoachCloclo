from datetime import date, timedelta

from coach.analysis.zones import compute_zones
from coach.llm.prompts import SYSTEM_PROMPT, build_adjustment_prompt, build_generation_prompt
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
