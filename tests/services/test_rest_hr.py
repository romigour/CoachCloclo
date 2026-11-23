from datetime import date, timedelta

import pytest

from coach.analysis.rest_hr import WINDOW_DAYS, NightRecord
from coach.analysis.zones import hr_zones
from coach.garmin.port import FakeGarminClient, GarminAuthRequired, Metrics, NightRest
from coach.services.context import refresh_snapshot
from coach.services.rest_hr import (
    NIGHTS_KEY,
    cached_nights,
    load_manual,
    refresh_nights,
    resolve_rest_hr,
    save_manual,
)

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
