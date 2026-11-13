from datetime import date

import pytest

from coach.analysis.laps import StepComparison
from coach.analysis.zones import compute_zones
from coach.garmin.port import (
    FakeGarminClient,
    GarminAuthRequired,
    GarminRateLimited,
    GarminUnavailable,
    LapSummary,
)
from coach.plan.models import AthleteSnapshot
from coach.services.laps import (
    MAX_FETCHES_PAR_SYNCHRO,
    fetch_laps,
    fetch_missing_laps,
    latest_zones,
    session_comparison,
)
from tests.plan.factories import make_activity, make_db_session, make_cycle

LAP = LapSummary(index=0, duration_s=600, distance_m=1800, step_order=1)


def _matched_activity(repo, garmin_id=1):
    cycle = repo.add(make_cycle())
    session = repo.add(make_db_session(cycle.id))
    activity = repo.add(make_activity(garmin_activity_id=garmin_id, session_id=session.id))
    return session, activity


def test_fetch_missing_laps_only_for_matched_activities(repo):
    _, matched = _matched_activity(repo, garmin_id=1)
    free = repo.add(make_activity(garmin_activity_id=2))
    garmin = FakeGarminClient(laps={1: [LAP], 2: [LAP]})
    calls = []
    original = garmin.activity_laps
    garmin.activity_laps = lambda gid: calls.append(gid) or original(gid)

    assert fetch_missing_laps(repo, garmin) == 1
    assert calls == [1]
    assert len(repo.laps(matched.id)) == 1
    assert repo.laps(free.id) is None


def test_fetch_missing_laps_skips_already_fetched(repo):
    _, activity = _matched_activity(repo)
    repo.save_laps(activity.id, [])  # lecture réussie sans aucun tour
    garmin = FakeGarminClient(laps={1: [LAP]})
    garmin.activity_laps = lambda gid: (_ for _ in ()).throw(AssertionError("appel inattendu"))

    assert fetch_missing_laps(repo, garmin) == 0
    assert repo.laps(activity.id) == []


def test_fetch_laps_error_is_swallowed(repo):
    _, activity = _matched_activity(repo)
    garmin = FakeGarminClient(laps={1: [LAP]}, fail_on={"activity_laps"})

    assert fetch_laps(repo, garmin, activity) is False
    assert repo.laps(activity.id) is None


def _recording(garmin, behaviour):
    calls = []

    def activity_laps(gid):
        calls.append(gid)
        return behaviour(gid)

    garmin.activity_laps = activity_laps
    return calls


def _many_matched(repo, n):
    cycle = repo.add(make_cycle())
    session = repo.add(make_db_session(cycle.id))
    return [repo.add(make_activity(garmin_activity_id=i, session_id=session.id)) for i in range(1, n + 1)]


@pytest.mark.parametrize("error", [GarminRateLimited, GarminAuthRequired])
def test_fetch_missing_laps_stops_on_rate_limit_or_auth(repo, error):
    _many_matched(repo, 3)
    garmin = FakeGarminClient()

    def boom(gid):
        raise error("stop")

    calls = _recording(garmin, boom)

    assert fetch_missing_laps(repo, garmin) == 0
    assert len(calls) == 1


def test_fetch_missing_laps_unavailable_does_not_stop_the_loop(repo):
    acts = _many_matched(repo, 2)
    garmin = FakeGarminClient()

    def behaviour(gid):
        if gid == 1:
            raise GarminUnavailable("panne")
        return [LAP]

    calls = _recording(garmin, behaviour)

    assert fetch_missing_laps(repo, garmin) == 1
    assert calls == [1, 2]
    assert repo.laps(acts[0].id) is None
    assert len(repo.laps(acts[1].id)) == 1


def test_fetch_missing_laps_caps_fetches_per_sync(repo):
    acts = _many_matched(repo, 25)
    garmin = FakeGarminClient()
    calls = _recording(garmin, lambda gid: [LAP])

    assert fetch_missing_laps(repo, garmin) == MAX_FETCHES_PAR_SYNCHRO == 20
    assert len(calls) == 20
    assert sum(repo.laps(a.id) is not None for a in acts) == 20

    calls.clear()
    assert fetch_missing_laps(repo, garmin) == 5
    assert len(calls) == 5
    assert all(repo.laps(a.id) is not None for a in acts)


@pytest.mark.parametrize("error", [GarminUnavailable, GarminRateLimited, GarminAuthRequired])
def test_fetch_laps_never_raises(repo, error):
    _, activity = _matched_activity(repo)
    garmin = FakeGarminClient()

    def boom(gid):
        raise error("x")

    _recording(garmin, boom)

    assert fetch_laps(repo, garmin, activity) is False
    assert repo.laps(activity.id) is None


def test_session_comparison_reasons(repo):
    cycle = repo.add(make_cycle())
    session = repo.add(make_db_session(cycle.id))
    assert session_comparison(repo, session, None) == "no_activity"

    activity = repo.add(make_activity(session_id=session.id))
    assert session_comparison(repo, session, None) == "no_laps"

    repo.save_laps(activity.id, [LAP])
    assert isinstance(session_comparison(repo, session, None), StepComparison)


def test_latest_zones(repo):
    assert latest_zones(repo) is None
    zones = compute_zones(
        threshold_pace_s_km=300, pred_10k_s=None, garmin_hr_zones=None, hr_max=190, hr_rest=50
    )
    repo.add(AthleteSnapshot(date=date(2026, 11, 1), zones_json=zones.model_dump_json()))
    assert latest_zones(repo) == zones
