"""Import de tout l'historique Garmin en arrière-plan, avec état persistant."""

import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel

from coach.config import data_dir
from coach.garmin.port import (
    GarminAuthRequired,
    GarminPort,
    GarminRateLimited,
    GarminUnavailable,
)
from coach.plan.models import PersonalRecord
from coach.plan.repo import Repo
from coach.services.activities import store_summaries

PAGE_SIZE = 100
PAGE_PAUSE_S = 1.0
AUTH_MESSAGE = "Connexion Garmin expirée : reconnecte-toi dans les Réglages"


class HistoryState(BaseModel):
    status: Literal["idle", "running", "done", "error"] = "idle"
    imported: int = 0
    error: str | None = None
    finished_at: datetime | None = None


def _state_path():
    # Fichier dédié : la synchro réécrit settings.json en entier et l'écraserait.
    return data_dir() / "history.json"


def load_state() -> HistoryState:
    try:
        return HistoryState.model_validate_json(_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return HistoryState()


def save_state(s: HistoryState) -> None:
    _state_path().write_text(s.model_dump_json(), encoding="utf-8")


def recover_orphan() -> None:
    """Un import « en cours » trouvé au démarrage a été interrompu : on le marque en erreur."""
    state = load_state()
    if state.status == "running":
        state.status = "error"
        state.error = "Import interrompu"
        save_state(state)


def refresh_records(repo: Repo, garmin: GarminPort) -> bool:
    """Remplace les records personnels ; en cas d'échec Garmin, ne touche à rien."""
    try:
        summaries = garmin.personal_records()
    except (GarminUnavailable, GarminRateLimited, GarminAuthRequired):
        return False
    repo.replace_records(
        [
            PersonalRecord(kind=r.kind, value=r.value, garmin_activity_id=r.garmin_activity_id, date=r.date)
            for r in summaries
        ]
    )
    return True


def _error_message(exc: Exception) -> str:
    return AUTH_MESSAGE if isinstance(exc, GarminAuthRequired) else str(exc)


def import_history(
    repo: Repo, garmin: GarminPort, *, sleep: Callable[[float], None] = time.sleep
) -> int:
    """Importe toutes les activités page par page ; retourne le nombre ajouté.

    Reprenable : les activités déjà en base sont ignorées. En cas d'erreur, ce qui a été
    importé est conservé et l'état passe à `error` avant de relever l'exception.
    """
    state = HistoryState(status="running")
    save_state(state)
    total = 0
    try:
        offset = 0
        while True:
            page = garmin.activities_page(offset, PAGE_SIZE)
            total += store_summaries(repo, page)
            state.imported = total
            save_state(state)
            if len(page) < PAGE_SIZE:
                break
            offset += PAGE_SIZE
            sleep(PAGE_PAUSE_S)
        refresh_records(repo, garmin)
    except Exception as exc:
        state.status = "error"
        state.error = _error_message(exc)
        save_state(state)
        raise
    state.status = "done"
    state.finished_at = datetime.now(timezone.utc)
    save_state(state)
    return total


class HistoryRunner:
    """Lance l'import dans un thread démon, un seul à la fois."""

    def __init__(self, repo: Repo, garmin_factory: Callable[[], GarminPort]):
        self._repo = repo
        self._factory = garmin_factory
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._lock.locked()

    def start(self) -> bool:
        if not self._lock.acquire(blocking=False):
            return False
        try:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        except BaseException:
            self._lock.release()
            raise
        return True

    def _run(self) -> None:
        try:
            try:
                garmin = self._factory()
            except Exception as exc:
                save_state(HistoryState(status="error", error=_error_message(exc)))
                return
            try:
                import_history(self._repo, garmin)
            except Exception:
                pass  # déjà enregistrée dans l'état par import_history
        finally:
            self._lock.release()

    def join(self, timeout: float | None = None) -> None:
        thread = self._thread
        if thread is not None:
            thread.join(timeout)
