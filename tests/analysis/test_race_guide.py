from datetime import date

import pytest

from coach.analysis.gpx import ProfilePoint
from coach.analysis.race_guide import build_phases, build_race_guide, build_splits, distance_band
from coach.analysis.race_guide_texts import PHASE_ADVICE, PREPARATION, PRINCIPLE, ROAD_CLIMB_HINT
from coach.analysis.race_plan import (
    AidStation,
    RaceBasis,
    RaceSettings,
    build_race_plan,
    grade_multiplier,
)

BASIS = RaceBasis(
    captured_on=date(2026, 11, 1),
    pred_5k_s=None,
    pred_10k_s=None,
    pred_half_s=None,
    pred_marathon_s=None,
    threshold_pace_s_km=None,
    hr={"Z2": (120, 140), "Z3": (141, 155), "Z4": (156, 170)},
)


def road(distance_km, target_s, profile=None, settings=None):
    return build_race_plan(
        distance_km=distance_km,
        trail=False,
        profile=profile,
        basis=BASIS,
        settings=settings or RaceSettings(),
        today=date(2026, 11, 10),
        target_time_s=target_s,
    )


def hill_profile(up_m=600, km_each=10):
    """Montée régulière puis descente régulière, pas de 50 m."""
    n = round(km_each / 0.05)
    up = [ProfilePoint(km=i * 0.05, ele_m=up_m * i / n) for i in range(n + 1)]
    down = [ProfilePoint(km=km_each + i * 0.05, ele_m=up_m - up_m * i / n) for i in range(1, n + 1)]
    return up + down


def trail(stations=(), target_s=10800):
    return build_race_plan(
        distance_km=20,
        trail=True,
        profile=hill_profile(),
        basis=BASIS,
        settings=RaceSettings(aid_stations=list(stations)),
        today=date(2026, 11, 10),
        target_time_s=target_s,
    )


@pytest.mark.parametrize(
    "km,band", [(5, "court"), (12, "court"), (21.0975, "semi"), (42.195, "marathon"), (80, "ultra"),
     (12.5, "semi"), (25, "semi"), (26, "marathon"), (45, "marathon"), (46, "ultra")]
)
def test_distance_band(km, band):
    assert distance_band(km) == band


def test_road_phases_10k():
    phases = build_phases(road(10, 2700), False, BASIS, "08:00")
    assert [p.name for p in phases] == ["Départ", "Cœur de course", "Final"]
    assert [p.start_km for p in phases] == [0, 1.5, 8.5]
    assert [p.end_km for p in phases] == [1.5, 8.5, 10]
    assert phases[0].pace_low_s_km > phases[1].pace_low_s_km
    assert phases[0].pace_high_s_km - phases[0].pace_low_s_km == 10
    assert phases[-1].elapsed_end_s == 2700
    assert phases[-1].clock_end == "08:45"
    assert phases[0].hr_zone is None and phases[0].advice == ""


def test_road_phases_marathon():
    phases = build_phases(road(42.195, 12600), False, BASIS, "08:00")
    assert [p.name for p in phases] == ["Départ", "Installation", "Cœur de course", "Final"]
    assert phases[-1].end_km == 42.195
    assert [p.end_km for p in phases[:-1]] == [4.0, 17.0, 36.0]


def test_phases_without_reference_have_no_numbers():
    plan = road(10, None)
    phases = build_phases(plan, False, BASIS, "08:00")
    assert len(phases) == 3
    assert all(p.pace_low_s_km is None and p.elapsed_end_s is None and p.clock_end is None for p in phases)
    assert build_splits(plan, "08:00") == []
    t = build_phases(build_race_plan(
        distance_km=10, trail=True, profile=None, basis=BASIS, settings=RaceSettings(),
        today=date(2026, 11, 10),
    ), True, BASIS, "08:00")
    assert all(p.hr_zone is None and p.hr_low is None for p in t)


def test_splits_marathon():
    splits = build_splits(road(42.195, 12600), "08:00")
    assert [s.label for s in splits] == ["5 km", "10 km", "Semi", "25 km", "30 km", "35 km", "Arrivée"]
    assert splits[2].km == 21.0975
    assert splits[-1].km == 42.195 and splits[-1].elapsed_s == 12600 and splits[-1].clock == "11:30"
    assert [s.elapsed_s for s in splits] == sorted(s.elapsed_s for s in splits)


def test_splits_5k_no_duplicate():
    splits = build_splits(road(5, 1500), "08:00")
    assert [(s.km, s.label) for s in splits] == [(5, "Arrivée")]


def test_splits_ultra_every_10_km():
    splits = build_splits(road(80, 36000), "06:00")
    assert [s.label for s in splits] == [f"{k} km" for k in range(10, 80, 10)] + ["Arrivée"]


def test_splits_empty_on_trail():
    assert build_splits(trail(), "08:00") == []


def test_trail_phases_time_based_snap_to_aid():
    plain = build_phases(trail(), True, BASIS, "08:00")
    assert [p.name for p in plain] == ["Départ", "Installation", "Cœur de course", "Final"]
    assert plain[1].hr_zone == "Z3" and (plain[1].hr_low, plain[1].hr_high) == (141, 155)
    assert plain[0].hr_zone == "Z2" and plain[0].pace_low_s_km is None
    # la montée (6 %) coûte plus cher que la descente : la borne de 10 % du temps tombe sous 2 km
    m1, m2 = grade_multiplier(0.06), grade_multiplier(-0.06)
    raw = (m1 + m2) / m1
    station = AidStation(km=round(raw + 0.05, 2), name="Col", stop_min=0)
    snapped = build_phases(trail([station]), True, BASIS, "08:00")
    assert snapped[0].end_km == station.km
    assert snapped[1].start_km == station.km
    far = AidStation(km=5, name="Loin", stop_min=0)
    assert build_phases(trail([far]), True, BASIS, "08:00")[0].end_km == plain[0].end_km


def test_phase_terrain_lists_climbs():
    phases = build_phases(road(20, 6000, hill_profile()), False, BASIS, "08:00")
    # coupée à 2,4 km par le plan, relue d'un bloc, dans la phase qui en couvre le plus (km 2–8)
    assert [p.terrain for p in phases] == [[], ["Montée km 0–10,1, +600 m"], [], []]
    assert not any(t.startswith("Descente") for p in phases for t in p.terrain)  # route : montées seules
    tr = build_phases(trail(), True, BASIS, "08:00")
    assert tr[2].terrain == ["Descente km 10,1–20, −597 m"]  # km 6,5–16 en couvre le plus
    low = build_phases(road(4, 1200, hill_profile(up_m=100, km_each=2)), False, BASIS, "08:00")
    assert any("Montée" in t for p in low for t in p.terrain)  # +100 m passe le seuil route (20 m)
    mild = build_phases(trail(), True, BASIS, "08:00")
    assert all(not t.startswith("Montée") or int(t.rsplit("+", 1)[1].split()[0]) >= 100 for p in mild for t in p.terrain)


GEL = "Gel (25 g) + quelques gorgées"


def guide(plan, trail=False, settings=None):
    return build_race_guide(plan=plan, trail=trail, settings=settings or RaceSettings(), basis=BASIS)


def test_road_gels_half():
    settings = RaceSettings(carbs_g_h=45)
    g = guide(road(21.0975, 6300, settings=settings), settings=settings)
    n = g.nutrition
    assert (n.carbs_g_h, n.recommended) == (45, False)
    assert [i.clock for i in n.intakes] == ["08:40", "09:13"]  # 40 min puis 25/45 h ≈ 33 min ; rien après 1:30
    assert all(i.what == GEL for i in n.intakes)
    assert 0 < n.intakes[0].km < n.intakes[1].km < 21.0975
    assert n.principle.startswith("Tu as choisi 45 g de glucides par heure")
    rec = guide(road(21.0975, 6300)).nutrition
    assert (rec.carbs_g_h, rec.water_ml_h, rec.recommended) == (45, 400, True)
    assert [i.clock for i in rec.intakes] == ["08:40", "09:13"]
    assert rec.principle == PRINCIPLE[(False, "moyen")]


def test_no_gels_10k():
    n = guide(road(10, 2700)).nutrition
    assert (n.carbs_g_h, n.intakes) == (0, [])
    assert n.principle == PRINCIPLE[(False, "court")]
    forced = RaceSettings(carbs_g_h=60)
    assert guide(road(10, 2700, settings=forced), settings=forced).nutrition.intakes == []  # 45 min : fin trop proche


def test_trail_has_no_gel_list():
    g = guide(trail(target_s=5 * 3600), trail=True)
    assert g.nutrition.intakes == [] and g.nutrition.carbs_g_h == 75
    assert g.nutrition.principle == PRINCIPLE[(True, "long")]
    assert g.avg_pace_s_km is None and g.splits == []


def test_morning_wraps_midnight():
    settings = RaceSettings(start_time="04:00")
    g = guide(road(21.0975, 6300, settings=settings), settings=settings)
    assert [m.clock for m in g.morning] == ["01:00", "03:00", "03:35", "04:00"]
    assert g.morning[2].label.endswith("10 min de footing")
    assert g.morning[-1].label == "Départ"


def test_morning_warmup_by_band():
    short = guide(road(10, 2700)).morning
    assert [m.clock for m in short] == ["06:00", "07:00", "07:30", "08:00"]
    assert short[2].label.endswith("15–20 min de footing + 3 accélérations")
    long = guide(road(42.195, 12600)).morning
    assert [m.clock for m in long] == ["05:00", "07:00", "07:45", "08:00"]
    assert long[2].label.endswith("5 min de mobilité")


def test_guide_without_reference():
    g = guide(road(10, None))
    assert g.reference_time_s is None and g.avg_pace_s_km is None
    assert g.splits == [] and g.nutrition.intakes == []
    assert all(p.pace_low_s_km is None and p.clock_end is None and p.advice for p in g.phases)
    assert [b.title for b in g.preparation] == ["La semaine d'avant", "La veille", "Le matin"]
    assert all(b.items for b in g.preparation)
    assert [m.clock for m in g.morning] == ["06:00", "07:00", "07:30", "08:00"]


def test_guide_road_summary():
    g = guide(road(21.0975, 6300))
    assert (g.band, g.reference_time_s, g.avg_pace_s_km) == ("semi", 6300, 299)
    assert [s.label for s in g.splits][-1] == "Arrivée"


@pytest.mark.parametrize("km,band", [(10, "court"), (21.0975, "semi"), (42.195, "marathon"), (80, "ultra")])
@pytest.mark.parametrize("is_trail", [False, True])
def test_every_phase_has_advice(km, band, is_trail):
    plan = build_race_plan(distance_km=km, trail=is_trail, profile=None, basis=BASIS, settings=RaceSettings(),
                           today=date(2026, 11, 10), target_time_s=round(km * 360))
    g = guide(plan, trail=is_trail)
    assert g.band == band
    assert all(p.advice and p.advice.startswith(PHASE_ADVICE[(is_trail, band, p.name)]) for p in g.phases)
    assert all(b.items for b in g.preparation)
    assert {b.title for b in g.preparation} == set(PREPARATION[(is_trail, band)])


def test_road_climb_adds_effort_hint():
    g = guide(road(20, 6000, hill_profile()))
    hilly = g.phases[1]
    assert hilly.terrain and hilly.advice.startswith(PHASE_ADVICE[(False, "semi", "Installation")])
    assert hilly.advice.endswith(ROAD_CLIMB_HINT)
    assert not g.phases[0].advice.endswith(ROAD_CLIMB_HINT)


def test_texts_never_per_kilo():
    texts = list(PHASE_ADVICE.values()) + list(PRINCIPLE.values())
    texts += [item for blocks in PREPARATION.values() for items in blocks.values() for item in items]
    assert texts and all("/kg" not in t and "par kilo" not in t for t in texts)


def flat_profile(distance_km, step=0.05):
    n = round(distance_km / step)
    return [ProfilePoint(km=min(i * step, distance_km), ele_m=100) for i in range(n + 1)]


def test_flat_gpx_half_keeps_paced_start_and_finish():
    plan = road(21.0975, 6300, flat_profile(21.0975))
    assert [(s.start_km, s.end_km) for s in plan.segments] == [
        (0, pytest.approx(0.12 * 21.0975)), (pytest.approx(0.12 * 21.0975), pytest.approx(0.88 * 21.0975)),
        (pytest.approx(0.88 * 21.0975), 21.0975),
    ]
    assert plan.segments[-1].elapsed_s == 6300
    g = guide(plan)
    paces = {p.name: p.pace_high_s_km for p in g.phases}
    assert paces["Départ"] > paces["Cœur de course"] > paces["Final"]
    assert g.phases[-1].elapsed_end_s == 6300 and g.splits[-1].elapsed_s == 6300


def test_trail_climb_listed_once():
    phases = build_phases(trail(), True, BASIS, "08:00")
    lines = [t for p in phases for t in p.terrain]
    assert lines.count("Montée km 0–10,1, +600 m") == 1
    assert len(lines) == len(set(lines))
    holder = next(p for p in phases if "Montée km 0–10,1, +600 m" in p.terrain)
    covered = {p.name: min(p.end_km, 10.05) - max(p.start_km, 0) for p in phases}
    assert holder.name == max(covered, key=covered.get)


def test_road_start_range_never_faster_than_average():
    g = guide(road(10, 3000))
    start = g.phases[0]
    assert start.pace_low_s_km >= g.avg_pace_s_km
    assert start.pace_high_s_km - start.pace_low_s_km == 10
    core = g.phases[1]
    assert core.pace_high_s_km - core.pace_low_s_km == 10


def test_short_race_has_no_empty_phase():
    phases = build_phases(road(1, 300), False, BASIS, "08:00")
    assert phases and all(p.end_km > p.start_km for p in phases)
    assert all(p.pace_low_s_km is not None for p in phases)
    assert phases[-1].end_km == 1


def _gels(text):
    return "gel" in text.lower()


def test_no_gel_advice_without_intakes():
    fast = guide(road(21.0975, 4200))  # moins de 1 h 15 : aucun gel
    assert fast.nutrition.intakes == []
    assert not any(_gels(p.advice) for p in fast.phases)
    for km in (21.0975, 42.195):
        bare = guide(road(km, None))
        assert not any(_gels(p.advice) for p in bare.phases)
        assert not any("passages" in p.advice for p in bare.phases)
    paced = guide(road(21.0975, 6300))
    assert paced.nutrition.intakes and any(_gels(p.advice) for p in paced.phases)
    assert any("passages" in p.advice for p in paced.phases)
    assert any(_gels(p.advice) for p in guide(road(42.195, 12600)).phases)


def test_chosen_carbs_acknowledged():
    forced = RaceSettings(carbs_g_h=60)
    n = guide(road(10, 2700, settings=forced), settings=forced).nutrition
    assert n.carbs_g_h == 60 and not n.recommended
    assert n.principle.startswith("Tu as choisi 60 g de glucides par heure")
    assert "pas besoin de glucides" not in n.principle and not _gels(n.principle)  # aucun gel prévu sur 45 min
    water = RaceSettings(water_ml_h=300)
    w = guide(road(21.0975, 6300, settings=water), settings=water).nutrition
    assert w.principle.startswith(PRINCIPLE[(False, "moyen")]) and "Tu as choisi 300 ml d'eau par heure" in w.principle
    t = RaceSettings(carbs_g_h=40)
    tn = guide(build_race_plan(distance_km=20, trail=True, profile=hill_profile(), basis=BASIS, settings=t,
                               today=date(2026, 11, 10), target_time_s=5 * 3600), trail=True, settings=t).nutrition
    assert tn.principle.startswith("Tu as choisi 40 g de glucides par heure") and "60 à 90" not in tn.principle
