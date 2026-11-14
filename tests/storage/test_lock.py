"""Verrou Garmin partagé entre PC : acquisition atomique, réentrance, enveloppe des écritures."""

import re
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine

import coach.storage.libsql_dialect  # noqa: F401  (enregistre le dialecte)
from coach.garmin.port import FakeGarminClient, GarminUnavailable
from coach.plan.models import GarminLock
from coach.plan.repo import Repo, prepare_engine
from coach.storage.lock import (
    LOCK_MSG,
    WRITE_TTL,
    GarminLocked,
    LockedGarmin,
    garmin_lock,
    held_elsewhere,
    machine_id,
    release,
    try_acquire,
)

T0 = datetime(2026, 11, 14, 10, 0, tzinfo=timezone.utc)
TTL = timedelta(minutes=2)


@pytest.fixture(params=["sqlite", "libsql"])
def any_repo(request, repo, tmp_path):
    """Même comportement attendu sur SQLite et sur le pilote libsql (fichier local)."""
    if request.param == "sqlite":
        return repo
    return Repo(prepare_engine(create_engine(f"sqlite+libsql:///{tmp_path / 'l.db'}")))


def test_lock_free_then_held(any_repo):
    assert try_acquire(any_repo, "A", TTL, T0) is True
    assert try_acquire(any_repo, "B", TTL, T0 + timedelta(minutes=1)) is False
    assert held_elsewhere(any_repo, "B", T0 + timedelta(minutes=1)) is True
    assert held_elsewhere(any_repo, "A", T0 + timedelta(minutes=1)) is False
    # expiré : B l'obtient
    assert try_acquire(any_repo, "B", TTL, T0 + timedelta(minutes=3)) is True
    assert held_elsewhere(any_repo, "A", T0 + timedelta(minutes=3)) is True
    with any_repo.transaction() as db:
        row = db.get(GarminLock, 1)
    assert row.holder == "B"


def test_lock_reentrant_and_release_by_owner_only(any_repo):
    assert try_acquire(any_repo, "A", TTL, T0)
    assert try_acquire(any_repo, "A", TTL, T0 + timedelta(minutes=1))  # réentrant, prolongé
    assert try_acquire(any_repo, "B", TTL, T0 + timedelta(minutes=2, seconds=30)) is False  # prolongation effective
    release(any_repo, "B")  # sans effet : B ne détient pas le verrou
    assert held_elsewhere(any_repo, "B", T0 + timedelta(minutes=2))
    release(any_repo, "A")
    assert not held_elsewhere(any_repo, "B", T0 + timedelta(minutes=2))
    assert try_acquire(any_repo, "B", TTL, T0 + timedelta(minutes=2))


def test_short_ttl_never_shortens_own_lock(any_repo):
    assert try_acquire(any_repo, "A", timedelta(minutes=15), T0)
    assert try_acquire(any_repo, "A", TTL, T0 + timedelta(minutes=1))
    assert held_elsewhere(any_repo, "B", T0 + timedelta(minutes=10))


def test_naive_datetimes_are_utc(any_repo):
    assert try_acquire(any_repo, "A", TTL, T0)
    assert held_elsewhere(any_repo, "B", T0.replace(tzinfo=None) + timedelta(minutes=1))
    paris = timezone(timedelta(hours=1))
    assert held_elsewhere(any_repo, "B", (T0 + timedelta(minutes=1)).astimezone(paris))


def test_garmin_lock_context(repo):
    try_acquire(repo, "autre-pc", TTL, datetime.now(timezone.utc))
    with pytest.raises(GarminLocked) as exc:
        with garmin_lock(repo, "moi", timedelta(minutes=15)):
            pass
    assert str(exc.value) == LOCK_MSG and isinstance(exc.value, GarminUnavailable)
    release(repo, "autre-pc")
    with garmin_lock(repo, "moi", timedelta(minutes=15)):
        assert held_elsewhere(repo, "autre-pc", datetime.now(timezone.utc))
    assert not held_elsewhere(repo, "autre-pc", datetime.now(timezone.utc))


def test_locked_garmin_write_raises_when_held_elsewhere(repo):
    inner = FakeGarminClient()
    garmin = LockedGarmin(inner, lambda: repo, "moi")
    wid = garmin.upload_workout({"x": 1})  # verrou libre : passe et le prend
    assert held_elsewhere(repo, "autre-pc", datetime.now(timezone.utc))
    release(repo, "moi")
    try_acquire(repo, "autre-pc", timedelta(minutes=15), datetime.now(timezone.utc))
    for call in (
        lambda: garmin.upload_workout({}),
        lambda: garmin.schedule(wid, date(2026, 11, 20)),
        lambda: garmin.reschedule(1, date(2026, 11, 20)),
        lambda: garmin.unschedule(1),
        lambda: garmin.delete_workout(wid),
    ):
        with pytest.raises(GarminLocked):
            call()
    assert inner.calls == ["upload_workout"]
    # lectures déléguées sans verrou
    assert garmin.today() == inner.today()
    assert garmin.metrics() == inner.metrics()
    assert garmin.activities_page(0, 10) == []


def test_locked_garmin_follows_repo_getter(repo, tmp_path):
    from coach.plan.repo import make_engine

    other = Repo(make_engine(tmp_path / "autre.db"))
    current = {"repo": repo}
    garmin = LockedGarmin(FakeGarminClient(), lambda: current["repo"], "moi")
    try_acquire(other, "autre-pc", WRITE_TTL, datetime.now(timezone.utc))
    garmin.upload_workout({})
    current["repo"] = other
    with pytest.raises(GarminLocked):
        garmin.upload_workout({})


def test_machine_id_created_once(coach_home):
    mid = machine_id()
    assert re.fullmatch(r".+-[0-9a-f]{8}", mid)
    assert (coach_home / "machine_id").read_text(encoding="utf-8").strip() == mid
    assert machine_id() == mid
