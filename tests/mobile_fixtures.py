"""Fixtures partagées Python -> TypeScript pour la version mobile (lecture seule).

Génère deux bases d'exemple (dumps SQL) et les réponses JSON des routes de l'API Python sur ces
bases ; les tests TS chargent les dumps dans un client libsql en mémoire et comparent leur sortie à
`expected.json`. Tout est déterministe : ids et horodatages fixés explicitement.

Régénération : `uv run python -m tests.mobile_fixtures`
"""

import json
import os
import sqlite3
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from coach.api.app import create_app
from coach.analysis.zones import compute_zones
from coach.garmin.port import FakeGarminClient, Metrics
from coach.llm.provider import FakeLLMProvider
from coach.plan.models import (
    Activity,
    AthleteSnapshot,
    Cycle,
    Event,
    Goal,
    PersonalRecord,
    Proposal,
    Race,
    Session,
)
from coach.plan.repo import Repo, make_engine

FIXTURES_DIR = Path(__file__).parent.parent / "web" / "src" / "lib" / "turso" / "__fixtures__"
SCENARIOS = ("active", "between")
CREATED = datetime(2026, 3, 1, 8, 0, 0, tzinfo=timezone.utc)
METRICS = Metrics(hr_max=190, hr_rest=50, threshold_pace_s_km=300)
# clés propres au bureau, absentes de la version mobile
DESKTOP_STATUS_KEYS = ("garmin", "llm_mode", "storage")


def _step(kind: str, zone: str, **length) -> dict:
    return {"kind": kind, "zone": zone, **length}


def _steps(*steps: dict) -> str:
    return json.dumps(list(steps), ensure_ascii=False)


def _session(id: int, week: int, order: int, **over) -> Session:
    data = {
        "id": id,
        "cycle_id": 1,
        "week_index": week,
        "order": order,
        "suggested_day": "mardi",
        "type": "EF",
        "sport": "run",
        "target_kind": "hr",
        "title": f"Séance {id}",
        "description": f"Description de la séance {id}.",
        "steps_json": _steps(_step("warmup", "Z2", duration_s=600)),
        "status": "todo",
    }
    data.update(over)
    return Session(**data)


def _goal(id: int, **over) -> Goal:
    data = {
        "id": id,
        "created_at": CREATED,
        "type": "trail",
        "distance_km": 42.0,
        "d_plus_m": 2000,
        "race_date": date(2026, 3, 22),
        "sessions_per_week": 3,
        "plan_start": date(2026, 3, 2),
        "plan_accepted": True,
        "priority": "principal",
    }
    data.update(over)
    return Goal(**data)


def _activity(id: int, day: date, **over) -> Activity:
    data = {
        "id": id,
        "garmin_activity_id": 9000 + id,
        "date": day,
        "type_key": "running",
        "duration_s": 2700.0,
        "distance_m": 9000.0,
        "raw_json": "{}",
    }
    data.update(over)
    return Activity(**data)


def _zones_json(hr_max: int, hr_rest: int, threshold: int) -> str:
    zones = compute_zones(
        threshold_pace_s_km=threshold, pred_10k_s=None, garmin_hr_zones=None, hr_max=hr_max, hr_rest=hr_rest
    )
    return zones.model_dump_json()


def _build_active(repo: Repo) -> None:
    repo.add(
        Cycle(
            id=1, created_at=CREATED, status="active", plan_start=date(2026, 3, 2), end_date=date(2026, 3, 22),
            sessions_per_week=3, long_run_day="dimanche", include_bike=True, plan_accepted=True,
        )
    )
    # objectifs : 2 dans le cycle, 1 au-delà (horizon), 1 courue, 1 archivé (absent partout)
    repo.add(_goal(1, race_date=date(2026, 3, 15), distance_km=21.1, d_plus_m=300, type="route",
                   target_time_s=6600, target_source="user",
                   gpx_summary_json=json.dumps({"distance_km": 21.1, "d_plus_m": 300})))
    repo.add(_goal(2, race_date=date(2026, 3, 22), priority="secondaire", target_source="claude"))
    repo.add(_goal(3, race_date=date(2026, 9, 6), distance_km=80.0, d_plus_m=5000, plan_accepted=False))
    repo.add(_goal(4, race_date=date(2025, 11, 2), status="done", distance_km=10.0, d_plus_m=0, type="route",
                   priority="plaisir", target_time_s=2700, target_source="user"))
    repo.add(_goal(5, race_date=date(2026, 4, 12), status="archived"))

    repeat = [
        _step("warmup", "EF", duration_s=600),
        {"repeat": 5, "steps": [_step("active", "seuil", distance_m=1000), _step("recovery", "récup", duration_s=90)]},
        _step("cooldown", "EF", duration_s=300),
    ]
    sessions = [
        _session(1, 1, 1, status="done", suggested_day="mardi", title="EF mardi"),
        _session(2, 1, 2, status="missed", suggested_day="jeudi", type="seuil", target_kind="pace",
                 title="Seuil jeudi", chaining_note="Après le vélo",
                 steps_json=json.dumps(repeat, ensure_ascii=False)),
        _session(3, 1, 3, status="exported", suggested_day="dimanche", type="sortie longue",
                 title="Sortie longue", scheduled_date=date(2026, 3, 8), garmin_workout_id=111,
                 garmin_schedule_id=222),
        _session(4, 2, 1, status="sync_error", title="Séance en erreur", sync_error="Garmin indisponible"),
        _session(5, 2, 2, sport="bike", suggested_day="mercredi", title="Vélo récup",
                 steps_json=_steps(_step("active", "Z1", duration_s=2400))),
        _session(6, 2, 3, status="todo", suggested_day="samedi", title="Fartlek"),
        _session(7, 3, 1, status="todo", suggested_day="mardi", title="Dernier footing"),
        _session(8, 3, 2, status="todo", suggested_day="dimanche", type="course", target_kind="pace",
                 title="Course objectif",
                 steps_json=_steps(_step("active", "marathon", distance_m=21100))),
    ]
    for s in sessions:
        repo.add(s)

    # imprévus : blessure ouverte, semaine allégée avec jours, fatigue liée à une séance
    repo.add(Event(id=1, cycle_id=1, created_at=CREATED, kind="injury", start_date=date(2026, 3, 10),
                   end_date=None, note="Tendinite"))
    repo.add(Event(id=2, cycle_id=1, created_at=CREATED, kind="light_week", start_date=date(2026, 3, 16),
                   end_date=date(2026, 3, 22), max_sessions=2, days_json=json.dumps(["mardi", "dimanche"]),
                   note="Déplacement"))
    repo.add(Event(id=3, cycle_id=1, created_at=CREATED, kind="fatigue", start_date=date(2026, 3, 5),
                   end_date=date(2026, 3, 5), session_id=2))

    repo.add(Proposal(id=1, created_at=CREATED, analysis="Charge un peu haute, on allège.", status="pending"))

    repo.add(AthleteSnapshot(id=1, date=date(2026, 2, 20), vo2max=50.0, hr_max=188, hr_rest=52,
                             threshold_pace_s_km=310.0, zones_json=_zones_json(188, 52, 310)))
    repo.add(AthleteSnapshot(id=2, date=date(2026, 3, 1), vo2max=52.0, hr_max=190, hr_rest=50,
                             threshold_pace_s_km=300.0, zones_json=_zones_json(190, 50, 300)))

    zone_s = {f"hrTimeInZone_{i}": float(i * 100) for i in range(1, 6)}
    activities = [
        _activity(1, date(2026, 3, 3), session_id=1, match_source="auto", avg_hr=140.0, avg_pace_s_km=300.0,
                  d_plus_m=50.0, raw_json=json.dumps({"activityName": "Footing", "maxHR": 165,
                                                      "startTimeLocal": "2026-03-03 07:00:00"})),
        _activity(2, date(2026, 3, 4), type_key="cycling", duration_s=3600.0, distance_m=25000.0, avg_hr=120.0,
                  raw_json=json.dumps({"activityName": "Vélo libre"})),
        _activity(3, date(2026, 3, 9), raw_json="pas du json"),
        _activity(4, date(2026, 3, 10), raw_json='{"maxHR": true, "vO2MaxValue": "52"}'),
        _activity(5, date(2026, 3, 12), raw_json=json.dumps({"eventType": {"typeKey": "race"}})),
        _activity(6, date(2026, 3, 15), distance_m=21100.0, duration_s=6500.0, d_plus_m=300.0, avg_hr=170.0,
                  raw_json=json.dumps({"activityName": "Semi", "eventType": {"typeKey": "race"}})),
        _activity(7, date(2026, 3, 16), raw_json=json.dumps({"eventType": {"typeKey": "race"}})),
        _activity(8, date(2026, 3, 17), duration_s=0.0, distance_m=0.0),
        _activity(9, date(2026, 3, 18), raw_json=json.dumps(zone_s)),
        _activity(10, date(2026, 3, 19),
                  raw_json=json.dumps({k: v for k, v in zone_s.items() if k != "hrTimeInZone_5"})),
    ]
    for a in activities:
        repo.add(a)
    repo.add(Race(id=1, activity_id=6, name="Semi de test", official_time_s=6480, overall_rank=120,
                  overall_total=900, category="V1H", category_rank=15, category_total=100))
    repo.add(Race(id=2, activity_id=7, name="Course exclue", excluded=True))

    repo.replace_records([
        PersonalRecord(id=1, kind="5k", value=1350.0, garmin_activity_id=9001, date=date(2026, 3, 3)),
        PersonalRecord(id=2, kind="longest_run", value=21100.0, garmin_activity_id=None, date=None),
    ])
    repo.set_state("history", {"status": "done", "imported": 42, "error": None})


def _build_between(repo: Repo) -> None:
    repo.add(
        Cycle(
            id=1, created_at=datetime(2020, 1, 1, 8, 0, 0, tzinfo=timezone.utc), status="done",
            plan_start=date(2020, 1, 6), end_date=date(2020, 3, 1), sessions_per_week=4,
            long_run_day="samedi", include_bike=False, plan_accepted=True,
        )
    )
    repo.add(_goal(1, race_date=date(2099, 6, 1), plan_start=date(2099, 3, 2), plan_accepted=False,
                   distance_km=50.0, d_plus_m=1000))


def build(scenario: str, path: Path) -> None:
    """Peuple la base `path` (schéma réel via `make_engine`) avec le scénario `scenario`."""
    repo = Repo(make_engine(path))
    {"active": _build_active, "between": _build_between}[scenario](repo)
    repo.engine.dispose()


def _dump(path: Path) -> str:
    conn = sqlite3.connect(path)
    try:
        lines = list(conn.iterdump())
    finally:
        conn.close()
    # SQLAlchemy crée les index dans un ordre qui varie d'un processus à l'autre (hachage de chaînes) :
    # on les retrie, chacun dans l'un des emplacements qu'occupaient les index
    is_index = [l.startswith(("CREATE INDEX", "CREATE UNIQUE INDEX")) for l in lines]
    ordered = iter(sorted(l for l, i in zip(lines, is_index) if i))
    lines = [next(ordered) if i else l for l, i in zip(lines, is_index)]
    return "".join(f"{line}\n" for line in lines)


def _responses(path: Path) -> dict:
    """Réponses JSON des routes de lecture sur la base `path`."""
    repo = Repo(make_engine(path))
    app = create_app(
        lan=False,
        garmin_factory=lambda: FakeGarminClient(metrics=METRICS),
        llm_factory=lambda: FakeLLMProvider([]),
        repo=repo,
        extra_hosts={"testserver"},
    )
    client = TestClient(app, headers={"X-Coach": "1"})

    def get(url: str):
        r = client.get(url)
        assert r.status_code == 200, (url, r.status_code, r.text)
        return r.json()

    status = get("/api/status")
    for key in DESKTOP_STATUS_KEYS:
        status.pop(key)
    plan = get("/api/plan")
    out = {
        "status": status,
        "plan": plan,
        "events": get("/api/cycle/events"),
        "activities": {str(w["week_index"]): get(f"/api/activities?week={w['week_index']}") for w in plan["weeks"]},
        "zones": get("/api/zones"),
        "stats_activities": get("/api/stats/activities"),
        "stats_records": get("/api/stats/records"),
    }
    repo.engine.dispose()
    return out


def generate(out_dir: Path) -> None:
    """Écrit `active.sql`, `between.sql` et `expected.json` dans `out_dir`."""
    out_dir.mkdir(parents=True, exist_ok=True)
    expected = {}
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["COACH_HOME"] = tmp  # réglages (llm_mode…) lus depuis COACH_HOME, jamais ceux du poste
        for scenario in SCENARIOS:
            db = Path(tmp) / f"{scenario}.db"
            build(scenario, db)
            before = _dump(db)
            expected[scenario] = _responses(db)
            if _dump(db) != before:
                raise RuntimeError(f"Les routes GET ont modifié la base du scénario {scenario}")
            (out_dir / f"{scenario}.sql").write_text(before, encoding="utf-8", newline="\n")
    text = json.dumps(expected, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    (out_dir / "expected.json").write_text(text, encoding="utf-8", newline="\n")


def main() -> None:
    generate(FIXTURES_DIR)


if __name__ == "__main__":
    main()
