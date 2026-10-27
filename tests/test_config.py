from coach.config import (
    data_dir,
    db_path,
    load_settings,
    save_settings,
    tokenstore_dir,
)


def test_data_dir_uses_coach_home(coach_home):
    assert data_dir() == coach_home
    assert tokenstore_dir() == coach_home / "garmin"
    assert db_path() == coach_home / "coach.db"


def test_settings_roundtrip(coach_home):
    s = load_settings()
    assert s.llm_mode == "cli"
    s.llm_mode = "api"
    save_settings(s)
    assert load_settings().llm_mode == "api"
