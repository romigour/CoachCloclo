"""Chemins de données et réglages persistants de Coach."""

import os
from datetime import datetime
from pathlib import Path
from typing import Literal

from platformdirs import user_data_dir
from pydantic import BaseModel


def data_dir() -> Path:
    """Dossier de données ; surchargé par COACH_HOME. Créé à la demande."""
    override = os.environ.get("COACH_HOME")
    path = Path(override) if override else Path(user_data_dir("coach"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def tokenstore_dir() -> Path:
    return data_dir() / "garmin"


def db_path() -> Path:
    return data_dir() / "coach.db"


def _settings_path() -> Path:
    return data_dir() / "settings.json"


class Settings(BaseModel):
    llm_mode: Literal["cli", "api"] = "cli"
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-5-5"
    pin_hash: str | None = None
    last_sync_at: datetime | None = None
    proposal_due: bool = False


def load_settings() -> Settings:
    path = _settings_path()
    if not path.exists():
        return Settings()
    return Settings.model_validate_json(path.read_text(encoding="utf-8"))


def save_settings(s: Settings) -> None:
    path = _settings_path()
    path.write_text(s.model_dump_json(indent=2), encoding="utf-8")
    if os.name == "posix":
        path.chmod(0o600)
