import threading
from datetime import date, datetime, timedelta, timezone

import pytest

from coach.garmin.port import (
    ActivitySummary,
    FakeGarminClient,
    GarminAuthRequired,
    GarminUnavailable,
    PersonalRecordSummary,
)
from coach.plan.models import PersonalRecord
from coach.services.history import (
    HistoryRunner,
    HistoryState,
    import_history,
    load_state,
    recover_orphan,
    refresh_records,
    save_state,
)
from coach.storage.lock import IMPORT_TTL, LOCK_MSG, GarminLocked, held_elsewhere, release, try_acquire


def make_activities(n: int) -> list[ActivitySummary]:
    return [
        ActivitySummary(
            garmin_id=i,
            date=date(2020, 1, 1) + timedelta(days=i),
            type_key="running",
            duration_s=3000,
            distance_m=10000,
            raw={},
        )
        for i in range(1, n + 1)
    ]


class FailingPageGarmin(FakeGarminClient):
    """Fake dont la pagination échoue à partir de l'offset 100."""

    def activities_page(self, offset, limit):
        if offset >= 100:
            raise GarminUnavailable("Garmin coupé")
        return super().activities_page(offset, limit)


def test_import_paginates_until_empty_page(repo, coach_home):
    garmin = FakeGarminClient(activities=make_activities(250))
    calls: list[float] = []
    assert import_history(repo, garmin, sleep=calls.append) == 250
    assert len(repo.all_activities()) == 250
    # pages 100, 100, 50, puis une page vide qui arrête l'import : une pause entre chaque appel
    assert calls == [1.0, 1.0, 1.0]
    state = load_state(repo)
    assert state.status == "done" and state.imported == 250
    assert state.finished_at is not None


class LossyPageGarmin(FakeGarminClient):
    """Fake dont la première page pleine perd une activité illisible (99 sur 100)."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.offsets: list[int] = []

    def activities_page(self, offset, limit):
        self.offsets.append(offset)
        page = super().activities_page(offset, limit)
        return page[1:] if offset == 0 else page


def test_import_continues_after_page_with_unparsable_entry(repo, coach_home):
    garmin = LossyPageGarmin(activities=make_activities(250))
    assert import_history(repo, garmin, sleep=lambda s: None) == 249
    assert garmin.offsets == [0, 100, 200, 300]
    assert load_state(repo).status == "done"


def test_import_resumes_without_duplicates(repo, coach_home):
    garmin = FakeGarminClient(activities=make_activities(250))
    import_history(repo, garmin, sleep=lambda s: None)
    assert import_history(repo, garmin, sleep=lambda s: None) == 0
    assert len(repo.all_activities()) == 250


def test_import_error_keeps_activities(repo, coach_home):
    garmin = FailingPageGarmin(activities=make_activities(250))
    with pytest.raises(GarminUnavailable):
        import_history(repo, garmin, sleep=lambda s: None)
    assert len(repo.all_activities()) == 100
    state = load_state(repo)
    assert state.status == "error" and state.error and state.imported == 100


def test_import_auth_error_message(repo, coach_home):
    garmin = FakeGarminClient(activities=make_activities(5))
    garmin.activities_page = lambda offset, limit: (_ for _ in ()).throw(GarminAuthRequired())
    with pytest.raises(GarminAuthRequired):
        import_history(repo, garmin, sleep=lambda s: None)
    assert load_state(repo).error == "Connexion Garmin expirée : reconnecte-toi dans les Réglages"


def test_import_refreshes_records(repo, coach_home):
    records = [
        PersonalRecordSummary(kind="5k", value=1200.0, garmin_activity_id=3, date=date(2024, 5, 1)),
        PersonalRecordSummary(kind="10k", value=2500.0),
    ]
    garmin = FakeGarminClient(activities=make_activities(3), personal_records=records)
    import_history(repo, garmin, sleep=lambda s: None)
    assert len(repo.records()) == 2


def test_refresh_records_failure_keeps_table(repo, coach_home):
    repo.replace_records([PersonalRecord(kind="5k", value=1300.0)])
    garmin = FakeGarminClient(fail_on={"personal_records"})
    assert refresh_records(repo, garmin) is False
    assert [(r.kind, r.value) for r in repo.records()] == [("5k", 1300.0)]


def test_state_defaults_when_missing_or_corrupt(repo):
    assert load_state(repo) == HistoryState()
    repo.set_state("history", {"status": "n'importe quoi"})
    assert load_state(repo) == HistoryState()


def test_runner_refuses_second_start(repo, coach_home):
    gate = threading.Event()
    garmin = FakeGarminClient(activities=make_activities(3))

    def factory():
        assert gate.wait(timeout=5)
        return garmin

    runner = HistoryRunner(repo, factory)
    try:
        assert runner.start() is True
        assert runner.running
        assert runner.start() is False
    finally:
        gate.set()
        runner.join(timeout=5)
    assert not runner.running
    assert load_state(repo).status == "done"


def test_runner_factory_auth_error_sets_error_state(repo, coach_home):
    def factory():
        raise GarminAuthRequired()

    runner = HistoryRunner(repo, factory)
    assert runner.start() is True
    runner.join(timeout=5)
    state = load_state(repo)
    assert state.status == "error"
    assert state.error == "Connexion Garmin expirée : reconnecte-toi dans les Réglages"


def test_runner_logs_import_failure(repo, coach_home, caplog):
    garmin = FailingPageGarmin(activities=make_activities(250))
    runner = HistoryRunner(repo, lambda: garmin)
    with caplog.at_level("ERROR", logger="coach.services.history"):
        assert runner.start() is True
        runner.join(timeout=5)
    assert load_state(repo).status == "error"
    assert any(r.exc_info for r in caplog.records)


def test_recover_orphan(repo, coach_home):
    save_state(repo, HistoryState(status="running", imported=4))
    recover_orphan(repo)
    state = load_state(repo)
    assert state.status == "error" and state.error == "Import interrompu"


def test_recover_orphan_keeps_running_import_of_other_pc(repo, coach_home):
    save_state(repo, HistoryState(status="running", imported=4))
    try_acquire(repo, "autre-pc", IMPORT_TTL, datetime.now(timezone.utc))
    recover_orphan(repo, "moi")
    assert load_state(repo).status == "running"
    calls = []
    runner = HistoryRunner(repo, lambda: calls.append(1) or FakeGarminClient(), holder="moi")
    assert runner.start() is False
    runner.join(timeout=5)
    assert calls == [] and load_state(repo).status == "running"


def test_recover_orphan_marks_interrupted_when_lock_expired(repo, coach_home):
    save_state(repo, HistoryState(status="running", imported=4))
    try_acquire(repo, "autre-pc", IMPORT_TTL, datetime.now(timezone.utc) - timedelta(minutes=10))
    recover_orphan(repo, "moi")
    state = load_state(repo)
    assert state.status == "error" and state.error == "Import interrompu"


def test_recover_orphan_marks_own_running_import_interrupted(repo, coach_home):
    """Verrou encore détenu par ce PC (arrêt brutal) : l'import est bien orphelin."""
    save_state(repo, HistoryState(status="running"))
    try_acquire(repo, "moi", IMPORT_TTL, datetime.now(timezone.utc))
    recover_orphan(repo, "moi")
    assert load_state(repo).status == "error"


def test_import_refused_when_locked_elsewhere_keeps_other_state(repo, coach_home):
    save_state(repo, HistoryState(status="running", imported=7))
    try_acquire(repo, "autre-pc", IMPORT_TTL, datetime.now(timezone.utc))
    with pytest.raises(GarminLocked):
        import_history(repo, FakeGarminClient(activities=make_activities(3)), sleep=lambda s: None, holder="moi")
    assert load_state(repo) == HistoryState(status="running", imported=7)


def test_import_holds_lock_per_page_then_releases(repo, coach_home):
    seen = []

    class Spy(FakeGarminClient):
        def activities_page(self, offset, limit):
            seen.append(held_elsewhere(repo, "autre-pc", datetime.now(timezone.utc)))
            return super().activities_page(offset, limit)

    import_history(repo, Spy(activities=make_activities(150)), sleep=lambda s: None, holder="moi")
    assert seen == [True, True, True]
    assert not held_elsewhere(repo, "autre-pc", datetime.now(timezone.utc))


def test_import_stops_when_lock_lost_between_pages(repo, coach_home):
    def steal(_s):
        release(repo, "moi")
        try_acquire(repo, "autre-pc", IMPORT_TTL, datetime.now(timezone.utc))

    with pytest.raises(GarminLocked):
        import_history(repo, FakeGarminClient(activities=make_activities(150)), sleep=steal, holder="moi")
    assert load_state(repo).error == LOCK_MSG


def test_state_roundtrip_in_db(repo):
    save_state(repo, HistoryState(status="done", imported=3))
    assert load_state(repo).imported == 3
    assert repo.get_state("history")["imported"] == 3


