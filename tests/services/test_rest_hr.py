import json
from datetime import date, timedelta

import pytest

from coach.analysis.rest_hr import WINDOW_DAYS, NightRecord
from coach.analysis.zones import Zones, hr_zones
from coach.garmin.port import FakeGarminClient, GarminAuthRequired, Metrics, NightRest
from coach.plan.models import AthleteSnapshot
from coach.services.context import refresh_snapshot
from coach.services.garmin_export import export_session
from coach.services.rest_hr import (
    NIGHTS_KEY,
    apply_manual,
    cached_nights,
    load_manual,
    refresh_nights,
    resolve_rest_hr,
    rest_hr_view,
    save_manual,
)
from tests.plan.factories import make_cycle, make_db_session, zones_rest

T = date(2026, 11, 23)
METRICS = Metrics(hr_max=182, hr_rest=55, threshold_pace_s_km=300)
THREE_WORN_NIGHTS = {
    T: NightRest(hr_rest=46, slept=True),
    T - timedelta(days=1): NightRest(hr_rest=48, slept=True),
    T - timedelta(days=2): NightRest(hr_rest=47, slept=True),
}


def fake(nights: dict[date, NightRest], **kwargs) -> FakeGarminClient:
    return FakeGarminClient(today=T, metrics=METRICS, nights=nights, **kwargs)


def test_refresh_snapshot_uses_worn_nights(repo):
    nights = {**THREE_WORN_NIGHTS, T - timedelta(days=3): NightRest(hr_rest=62)}  # nuit non portée
    snap, zones = refresh_snapshot(repo, fake(nights))
    assert (snap.hr_rest, snap.hr_rest_source, snap.hr_rest_nights) == (47, "nights", 3)
    assert zones.hr["Z2"] == hr_zones(182, 47)["Z2"]


def test_manual_wins(repo):
    save_manual(repo, 44)
    snap, _ = refresh_snapshot(repo, fake(THREE_WORN_NIGHTS))
    assert (snap.hr_rest, snap.hr_rest_source, snap.hr_rest_nights) == (44, "manual", None)


def test_manual_roundtrip(repo):
    assert load_manual(repo) is None
    save_manual(repo, 44)
    assert load_manual(repo) == 44
    save_manual(repo, None)
    assert load_manual(repo) is None


def test_refresh_snapshot_without_nights_falls_back_to_garmin(repo):
    snap, zones = refresh_snapshot(repo, fake({}))
    assert (snap.hr_rest, snap.hr_rest_source) == (55, "garmin") and zones.hr


def test_last_good_after_nights_snapshot(repo):
    refresh_snapshot(repo, fake(THREE_WORN_NIGHTS))  # 47, nights
    repo.set_state(NIGHTS_KEY, {})  # plus de nuits en cache
    snap, _ = refresh_snapshot(repo, fake({}))
    assert (snap.hr_rest, snap.hr_rest_source) == (47, "last_good")


def test_last_good_ignores_manual_snapshots(repo):
    save_manual(repo, 44)
    refresh_snapshot(repo, fake({}))
    save_manual(repo, None)
    snap, _ = refresh_snapshot(repo, fake({}))
    assert (snap.hr_rest, snap.hr_rest_source) == (55, "garmin")


def test_resolve_rest_hr_uses_last_nights_snapshot(repo):
    refresh_snapshot(repo, fake(THREE_WORN_NIGHTS))
    rest = resolve_rest_hr(repo, [], T, garmin_value=55)
    assert (rest.value, rest.source) == (47, "last_good")


def test_nights_cached_then_only_today_and_yesterday_reread(repo):
    g = fake(THREE_WORN_NIGHTS)
    refresh_nights(repo, g)
    assert len(g.night_calls) == WINDOW_DAYS
    g.night_calls.clear()
    refresh_nights(repo, g)
    assert sorted(g.night_calls) == [T - timedelta(days=1), T]


def test_refresh_nights_returns_window_records(repo):
    records = refresh_nights(repo, fake(THREE_WORN_NIGHTS))
    assert len(records) == WINDOW_DAYS
    assert NightRecord(day=T, hr_rest=46, slept=True) in records
    assert cached_nights(repo) == records


def test_cache_keeps_only_window(repo):
    old = T - timedelta(days=WINDOW_DAYS)
    repo.set_state(NIGHTS_KEY, {old.isoformat(): {"hr_rest": 40, "slept": True}})
    records = refresh_nights(repo, fake(THREE_WORN_NIGHTS))
    assert old not in {r.day for r in records}
    assert old.isoformat() not in repo.get_state(NIGHTS_KEY)


def test_night_error_skips_day(repo):
    g = fake(THREE_WORN_NIGHTS, fail_on={"night_rest"})
    assert refresh_nights(repo, g) == [] and cached_nights(repo) == []


def test_night_auth_required_propagates(repo):
    class AuthFake(FakeGarminClient):
        def night_rest(self, day: date) -> NightRest:
            raise GarminAuthRequired("reconnexion")

    with pytest.raises(GarminAuthRequired):
        refresh_nights(repo, AuthFake(today=T, metrics=METRICS))


def _cache_nights(repo, nights: dict[date, NightRest]) -> None:
    repo.set_state(NIGHTS_KEY, {d.isoformat(): {"hr_rest": n.hr_rest, "slept": n.slept} for d, n in nights.items()})


def _garmin_snapshot(repo, **over) -> AthleteSnapshot:
    data = {
        "date": T - timedelta(days=1),
        "vo2max": 52.0,
        "hr_max": 182,
        "hr_rest": 55,
        "threshold_hr": 165,
        "threshold_pace_s_km": 300,
        "zones_json": zones_rest(55).model_dump_json(),
        "hr_rest_source": "garmin",
    }
    data.update(over)
    return repo.add(AthleteSnapshot(**data))


def test_view_without_snapshot(repo):
    save_manual(repo, 44)
    _cache_nights(repo, THREE_WORN_NIGHTS)
    assert rest_hr_view(repo, T) == {
        "value": None,
        "source": None,
        "nights": None,
        "manual": 44,
        "auto_value": 47,
        "auto_nights": 3,
    }


def test_view_reads_latest_snapshot(repo):
    _garmin_snapshot(repo, hr_rest=47, hr_rest_source="nights", hr_rest_nights=3)
    view = rest_hr_view(repo, T)
    assert (view["value"], view["source"], view["nights"], view["manual"]) == (47, "nights", 3, None)
    assert (view["auto_value"], view["auto_nights"]) == (None, None)


def test_apply_manual_without_snapshot_only_saves(repo):
    g = fake({})
    result = apply_manual(repo, g, 44)
    assert load_manual(repo) == 44 and repo.latest_snapshot() is None
    assert (result["applied"], result["manual"], result["value"], result["resent"], result["failed"]) == (
        False, 44, None, 0, []
    )
    assert g.calls == []


def test_apply_manual_new_snapshot_and_zones(repo):
    prev = _garmin_snapshot(repo)
    g = fake({}, fail_on={"metrics"})  # aucune lecture des métriques ni des nuits
    result = apply_manual(repo, g, 44)
    snap = repo.latest_snapshot()
    assert snap.id != prev.id and snap.date == T
    assert (snap.vo2max, snap.hr_max, snap.threshold_hr, snap.threshold_pace_s_km) == (52.0, 182, 165, 300)
    assert (snap.hr_rest, snap.hr_rest_source, snap.hr_rest_nights) == (44, "manual", None)
    zones = Zones.model_validate_json(snap.zones_json)
    assert zones == Zones(pace=zones_rest(55).pace, hr=hr_zones(182, 44), source=zones_rest(55).source)
    assert (result["applied"], result["value"], result["source"], result["resent"]) == (True, 44, "manual", 0)
    assert g.night_calls == []


def test_clear_manual_falls_back_to_cached_nights(repo):
    _garmin_snapshot(repo)
    _cache_nights(repo, THREE_WORN_NIGHTS)
    apply_manual(repo, fake({}), 44)
    result = apply_manual(repo, fake({}), None)
    assert (result["value"], result["source"], result["nights"], result["manual"]) == (47, "nights", 3, None)


def test_clear_manual_without_nights_keeps_garmin_value(repo):
    _garmin_snapshot(repo)
    result = apply_manual(repo, fake({}), None)
    assert (result["value"], result["source"]) == (55, "garmin")
    assert Zones.model_validate_json(repo.latest_snapshot().zones_json).hr == hr_zones(182, 55)


def test_clear_manual_returns_to_last_garmin_value(repo):
    # dernier instantané manuel, pas de nuits : la FC repos Garmin du dernier instantané Garmin revient
    _garmin_snapshot(repo)
    apply_manual(repo, fake({}), 44)
    result = apply_manual(repo, fake({}), None)
    assert (result["value"], result["source"], result["manual"]) == (55, "garmin", None)
    assert Zones.model_validate_json(repo.latest_snapshot().zones_json).hr == hr_zones(182, 55)


def test_clear_manual_without_garmin_snapshot_keeps_last(repo):
    _garmin_snapshot(repo, hr_rest=44, hr_rest_source="manual")
    result = apply_manual(repo, fake({}), None)
    assert (result["value"], result["source"]) == (44, "garmin")


def test_apply_manual_without_hr_max_keeps_zones(repo):
    _garmin_snapshot(repo, hr_max=None)
    apply_manual(repo, fake({}), 44)
    snap = repo.latest_snapshot()
    assert snap.hr_rest == 44 and Zones.model_validate_json(snap.zones_json) == zones_rest(55)


def _exported_hr_session(repo, g) -> int:
    cycle = repo.add(make_cycle(plan_start=date(2026, 11, 23)))
    sid = repo.add(make_db_session(cycle.id, week_index=1, order=1)).id
    export_session(repo, g, sid, T + timedelta(days=1))
    return sid


def test_apply_manual_resends_watch_sessions(repo):
    _garmin_snapshot(repo)
    g = fake({})
    sid = _exported_hr_session(repo, g)
    result = apply_manual(repo, g, 44)
    assert (result["resent"], result["failed"]) == (1, [])
    assert json.loads(repo.session(sid).export_hr_zones_json)["Z2"] == list(hr_zones(182, 44)["Z2"])


def test_apply_manual_resend_failure_keeps_value(repo):
    _garmin_snapshot(repo)
    g = fake({})
    sid = _exported_hr_session(repo, g)
    g.fail_on = {"upload_workout"}
    result = apply_manual(repo, g, 44)
    assert (result["resent"], result["failed"], result["value"]) == (0, [sid], 44)
    assert load_manual(repo) == 44 and repo.session(sid).status == "sync_error"
