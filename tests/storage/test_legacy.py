"""Reprise des fichiers locaux d'une installation existante (history.json, settings.json, gpx/)."""

import json
from datetime import datetime

from coach.plan.models import Goal
from coach.storage.legacy import import_legacy_files
from tests.plan.factories import make_goal


def _legacy_home(home, *, goal_id: int | None = 7, with_gpx_file: bool = True):
    (home / "history.json").write_text(
        json.dumps({"status": "done", "imported": 12, "error": None, "finished_at": None}), encoding="utf-8"
    )
    (home / "settings.json").write_text(
        json.dumps({"llm_mode": "cli", "last_sync_at": "2026-11-03T08:00:00", "proposal_due": True}),
        encoding="utf-8",
    )
    gpx = home / "gpx" / "7.gpx"
    if with_gpx_file:
        gpx.parent.mkdir()
        gpx.write_bytes(b"<gpx>1</gpx>")
    return gpx


def _goal_7(repo, gpx_path):
    repo.add(make_goal(id=7, gpx_path=str(gpx_path)))


def test_import_legacy_files(repo, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    gpx = _legacy_home(home)
    _goal_7(repo, gpx)
    import_legacy_files(repo, home)
    assert repo.get_state("history")["status"] == "done"
    assert repo.get_state("history")["imported"] == 12
    sync_state = repo.get_state("sync")
    assert datetime.fromisoformat(sync_state["last_sync_at"]) == datetime(2026, 11, 3, 8, 0)
    assert sync_state["proposal_due"] is True
    assert repo.gpx(7) == b"<gpx>1</gpx>"

    # 2e appel : rien ne change, même si les fichiers ont bougé
    (home / "history.json").write_text(json.dumps({"status": "error"}), encoding="utf-8")
    (home / "settings.json").write_text(json.dumps({"proposal_due": False}), encoding="utf-8")
    gpx.write_bytes(b"<gpx>2</gpx>")
    import_legacy_files(repo, home)
    assert repo.get_state("history")["status"] == "done"
    assert repo.get_state("sync")["proposal_due"] is True
    assert repo.gpx(7) == b"<gpx>1</gpx>"


def test_import_legacy_ignores_missing_gpx_file(repo, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    gpx = _legacy_home(home, with_gpx_file=False)
    _goal_7(repo, gpx)
    import_legacy_files(repo, home)
    assert repo.gpx(7) is None


def test_import_legacy_without_files_writes_nothing(repo, tmp_path):
    import_legacy_files(repo, tmp_path)
    assert repo.get_state("history") is None and repo.get_state("sync") is None
