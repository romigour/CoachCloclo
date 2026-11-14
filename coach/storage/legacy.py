"""Reprise des fichiers locaux d'une installation existante vers la base.

`history.json`, `last_sync_at` / `proposal_due` de `settings.json` et `gpx/<id>.gpx` vivaient hors base.
Chaque élément n'est repris qu'une fois : s'il est déjà en base, on n'y touche plus.
"""

import json
import logging
from pathlib import Path

from sqlmodel import select

from coach.plan.models import Goal
from coach.plan.repo import Repo
from coach.services.history import STATE_KEY as HISTORY_KEY, HistoryState
from coach.services.sync import SYNC_KEY, SyncState

log = logging.getLogger(__name__)


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def import_legacy_files(repo: Repo, home: Path) -> None:
    if repo.get_state(HISTORY_KEY) is None:
        raw = _read_json(home / "history.json")
        if raw is not None:
            try:
                repo.set_state(HISTORY_KEY, HistoryState.model_validate(raw).model_dump(mode="json"))
            except ValueError:
                log.warning("history.json illisible : ignoré")

    if repo.get_state(SYNC_KEY) is None:
        raw = _read_json(home / "settings.json")
        if raw is not None and ("last_sync_at" in raw or "proposal_due" in raw):
            try:
                state = SyncState.model_validate(
                    {k: raw[k] for k in ("last_sync_at", "proposal_due") if k in raw}
                )
            except ValueError:
                log.warning("settings.json : état de synchro illisible, ignoré")
            else:
                repo.set_state(SYNC_KEY, state.model_dump(mode="json"))

    with repo.transaction() as db:
        goals = [(g.id, g.gpx_path) for g in db.exec(select(Goal).where(Goal.gpx_path != None)).all()]  # noqa: E711
    for goal_id, gpx_path in goals:
        if repo.gpx(goal_id) is not None:
            continue
        try:
            data = Path(gpx_path).read_bytes()
        except OSError:
            continue  # fichier perdu : la vue stratégie affichera l'avertissement habituel
        with repo.transaction() as db:
            repo.save_gpx(db, goal_id, data)
