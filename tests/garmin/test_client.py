import json
from datetime import date
from pathlib import Path

import pytest
from garminconnect import (
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectNotFoundError,
    GarminConnectTooManyRequestsError,
)

from coach.garmin.client import GarminClient
from coach.garmin.port import (
    ActivitySummary,
    FakeGarminClient,
    GarminAuthRequired,
    GarminRateLimited,
    GarminUnavailable,
    Metrics,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "garmin"
FIXTURE_EXPECTED_THRESHOLD = 286  # round(1000 / 3.5)
FIXTURE_EXPECTED_REST = 48


def load(name):
    """Charge une fixture ; les listes sont enveloppées dans {"data": [...]}."""
    d = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return d["data"] if "data" in d else d


class FakeLib:
    """Imite `garminconnect.Garmin` : réponses fixes, ou exception à lever."""

    def __init__(self, responses=None, error=None):
        self.responses = responses if responses is not None else {}
        self.error = error
        self.calls = 0
        self.seen: list[tuple] = []

    def _answer(self, name, *args, **kwargs):
        self.calls += 1
        self.seen.append((name, args, kwargs))
        if self.error is not None:
            raise self.error
        return self.responses.get(name, {})

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return lambda *a, **k: self._answer(name, *a, **k)

    def today(self):
        return date(2026, 10, 27)


def full_lib():
    return FakeLib(
        {
            "get_max_metrics_latest": load("max_metrics_latest"),
            "get_lactate_threshold": load("lactate_threshold"),
            "get_heart_rates": load("heart_rates"),
            "get_heart_rate_zones_v2": load("heart_rate_zones_v2"),
            "get_race_predictions": load("race_predictions"),
            "get_activities_by_date": load("activities"),
            "upload_workout": load("workout_response"),
            "schedule_workout": load("schedule_response"),
        }
    )


def test_metrics_parsing_from_fixtures():
    m = GarminClient(full_lib()).metrics()
    assert m.threshold_pace_s_km == FIXTURE_EXPECTED_THRESHOLD
    assert m.hr_rest == FIXTURE_EXPECTED_REST
    assert m.vo2max == 52.3
    assert m.threshold_hr == 168
    assert m.hr_max == 187
    assert m.pred_10k_s == 2880
    assert m.hr_zones == [118, 132, 146, 160, 174]


def test_metrics_pace_with_speed_in_m_per_s():
    lib = full_lib()
    lib.responses["get_lactate_threshold"] = {"speed_and_heart_rate": {"speed": 4.0}}
    assert GarminClient(lib).metrics().threshold_pace_s_km == 250


def test_metrics_tolerates_missing_data():
    m = GarminClient(FakeLib()).metrics()
    assert m == Metrics()
    assert m.threshold_pace_s_km is None


def test_metrics_tolerates_odd_shapes():
    lib = FakeLib(
        {
            "get_max_metrics_latest": [],
            "get_lactate_threshold": {"speed_and_heart_rate": {"speed": None}},
            "get_heart_rates": None,
            "get_heart_rate_zones_v2": [{"sport": "RUNNING", "zone1Floor": 100}],
            "get_race_predictions": [{"time10K": "x"}],
        }
    )
    m = GarminClient(lib).metrics()
    assert m.hr_zones is None and m.threshold_pace_s_km is None and m.pred_10k_s is None


def test_metrics_missing_endpoint_gives_none():
    class NotFoundLib(FakeLib):
        def get_lactate_threshold(self, **kw):
            raise GarminConnectNotFoundError("404")

    m = GarminClient(NotFoundLib(full_lib().responses)).metrics()
    assert m.threshold_hr is None and m.hr_rest == 48


def test_activities_parsing():
    lib = full_lib()
    acts = GarminClient(lib).activities(date(2026, 10, 1), date(2026, 10, 27))
    a = acts[0]
    assert a.type_key == "running" and a.duration_s > 0
    assert a.garmin_id == 20000000002
    assert a.date == date(2026, 10, 25)
    assert (a.duration_s, a.distance_m, a.d_plus_m, a.avg_hr) == (5433, 16050, 212, 148)
    assert acts[1].d_plus_m is None and acts[1].avg_hr is None
    assert lib.seen[0][1] == ("2026-10-01", "2026-10-27")


def test_activities_skips_malformed_entries():
    lib = FakeLib({"get_activities_by_date": [{"activityId": 1}, "x", {"startTimeLocal": "2026-10-01 10:00:00"}]})
    assert GarminClient(lib).activities(date(2026, 10, 1), date(2026, 10, 2)) == []


def test_rate_limit_retries_once_then_raises():
    lib = FakeLib(error=GarminConnectTooManyRequestsError("429"))
    sleeps = []
    with pytest.raises(GarminRateLimited):
        GarminClient(lib, sleep=sleeps.append).activities(date(2026, 10, 1), date(2026, 10, 27))
    assert lib.calls == 2
    assert sleeps == [5]


def test_rate_limit_then_success():
    lib = full_lib()
    original = lib.get_activities_by_date
    state = {"n": 0}

    def flaky(*a, **k):
        state["n"] += 1
        if state["n"] == 1:
            raise GarminConnectTooManyRequestsError("429")
        return original(*a, **k)

    lib.get_activities_by_date = flaky
    assert GarminClient(lib, sleep=lambda s: None).activities(date(2026, 10, 1), date(2026, 10, 2))


def test_auth_error_mapped():
    lib = FakeLib(error=GarminConnectAuthenticationError("401"))
    with pytest.raises(GarminAuthRequired):
        GarminClient(lib).metrics()
    assert lib.calls == 1


def test_connection_error_mapped():
    lib = FakeLib(error=GarminConnectConnectionError("500"))
    with pytest.raises(GarminUnavailable):
        GarminClient(lib).activities(date(2026, 10, 1), date(2026, 10, 2))


def test_today_uses_api_then_falls_back():
    assert GarminClient(FakeLib()).today() == date(2026, 10, 27)

    class NoToday:
        pass

    assert GarminClient(NoToday()).today() == date.today()


def test_write_calls_and_ids():
    lib = full_lib()
    c = GarminClient(lib)
    assert c.upload_workout({"workoutName": "x"}) == 900001
    assert c.schedule(900001, date(2026, 11, 26)) == 700001
    c.reschedule(700001, date(2026, 11, 27))
    c.unschedule(700001)
    c.delete_workout(900001)
    assert [s[0] for s in lib.seen] == [
        "upload_workout", "schedule_workout", "reschedule_workout",
        "unschedule_workout", "delete_workout",
    ]
    assert lib.seen[1][1] == (900001, "2026-11-26")
    assert lib.seen[2][1] == (700001, "2026-11-27")


def test_write_response_without_id_is_unavailable():
    with pytest.raises(GarminUnavailable):
        GarminClient(FakeLib({"upload_workout": {}})).upload_workout({})


# --- authentification -----------------------------------------------------


class FakeGarminCtor:
    """Remplace `coach.garmin.client.Garmin` : consigne les constructions."""

    instances: list = []
    login_result = (None, None)
    login_error = None

    def __init__(self, *a, **kw):
        self.args, self.kw = a, kw
        self.dumped = []
        self.resumed = None
        self.client = self
        FakeGarminCtor.instances.append(self)

    def login(self, tokenstore=None):
        if FakeGarminCtor.login_error:
            raise FakeGarminCtor.login_error
        return FakeGarminCtor.login_result

    def resume_login(self, state, code):
        self.resumed = (state, code)
        return None, None

    def dump(self, path):
        self.dumped.append(path)


@pytest.fixture
def ctor(monkeypatch):
    FakeGarminCtor.instances = []
    FakeGarminCtor.login_result = (None, None)
    FakeGarminCtor.login_error = None
    monkeypatch.setattr("coach.garmin.client.Garmin", FakeGarminCtor)
    return FakeGarminCtor


def test_start_login_needs_mfa(ctor, tmp_path):
    ctor.login_result = ("needs_mfa", {"flow": "ios"})
    status, state = GarminClient.start_login("a@b.c", "pw", tmp_path)
    assert status == "needs_mfa" and state == {"flow": "ios"}
    assert ctor.instances[0].kw == {"return_on_mfa": True}
    assert ctor.instances[0].args == ("a@b.c", "pw")


def test_start_login_ok_persists_tokens(ctor, tmp_path):
    status, client = GarminClient.start_login("a@b.c", "pw", tmp_path)
    assert status == "ok" and isinstance(client, GarminClient)
    assert ctor.instances[0].dumped == [str(tmp_path)]


def test_start_login_bad_password(ctor, tmp_path):
    ctor.login_error = GarminConnectAuthenticationError("401")
    with pytest.raises(GarminAuthRequired):
        GarminClient.start_login("a@b.c", "bad", tmp_path)


def test_finish_login(ctor, tmp_path):
    client = GarminClient.finish_login({"flow": "ios"}, "123456", tmp_path)
    assert isinstance(client, GarminClient)
    inst = ctor.instances[0]
    assert inst.resumed == ({"flow": "ios"}, "123456")
    assert inst.dumped == [str(tmp_path)]


def test_from_tokens_requires_auth(ctor, tmp_path):
    ctor.login_error = GarminConnectAuthenticationError("no tokens")
    with pytest.raises(GarminAuthRequired):
        GarminClient.from_tokens(tmp_path)


def test_from_tokens_ok(ctor, tmp_path):
    assert isinstance(GarminClient.from_tokens(tmp_path), GarminClient)


# --- fake -------------------------------------------------------------------


def _act(d):
    return ActivitySummary(
        garmin_id=1, date=d, type_key="running", duration_s=60, distance_m=100, raw={}
    )


def test_fake_workout_lifecycle():
    f = FakeGarminClient()
    assert f.today() == date(2026, 11, 4)
    wid = f.upload_workout({"workoutName": "x"})
    sid = f.schedule(wid, date(2026, 11, 10))
    assert f.calendar == {date(2026, 11, 10): [sid]}
    assert f.schedules[sid] == (wid, date(2026, 11, 10))
    f.reschedule(sid, date(2026, 11, 12))
    assert f.calendar == {date(2026, 11, 12): [sid]}
    f.unschedule(sid)
    f.delete_workout(wid)
    assert f.calendar == {} and f.schedules == {} and f.workouts == {}
    assert f.calls == [
        "upload_workout", "schedule", "reschedule", "unschedule", "delete_workout",
    ]


def test_fake_fail_on_and_reads():
    f = FakeGarminClient(
        activities=[_act(date(2026, 10, 1)), _act(date(2026, 9, 1))],
        fail_on={"schedule", "metrics"},
    )
    wid = f.upload_workout({})
    with pytest.raises(GarminUnavailable):
        f.schedule(wid, date(2026, 11, 10))
    with pytest.raises(GarminUnavailable):
        f.metrics()
    assert f.calls == ["upload_workout"]  # écritures réussies seulement
    assert len(f.activities(date(2026, 10, 1), date(2026, 10, 27))) == 1


@pytest.mark.parametrize("speed,expected", [(0.35, 286), (4.0, 250), (16.0, None), (0.005, None), (0.05, None), (1.0, None)])
def test_pace_plausibility_guard(speed, expected):
    lib = full_lib()
    lib.responses["get_lactate_threshold"] = {"speed_and_heart_rate": {"speed": speed}}
    assert GarminClient(lib).metrics().threshold_pace_s_km == expected


def test_pace_guard_bounds_values():
    from coach.garmin.client import _pace_s_km

    assert _pace_s_km(1000 / 60) is None  # 60 s/km
    assert _pace_s_km(0.05) is None  # 0,5 m/s apres x10 = 2000 s/km


@pytest.mark.parametrize("method,arg", [("unschedule", 7), ("delete_workout", 9)])
def test_write_404_is_noop(method, arg):
    lib = FakeLib(error=GarminConnectNotFoundError("404"))
    getattr(GarminClient(lib), method)(arg)
    assert lib.calls == 1


@pytest.mark.parametrize("method", ["unschedule", "delete_workout"])
def test_write_other_errors_still_mapped(method):
    with pytest.raises(GarminUnavailable):
        getattr(GarminClient(FakeLib(error=GarminConnectConnectionError("500"))), method)(1)
    with pytest.raises(GarminAuthRequired):
        getattr(GarminClient(FakeLib(error=GarminConnectAuthenticationError("401"))), method)(1)
