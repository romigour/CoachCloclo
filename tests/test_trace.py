from datetime import date
from logging.handlers import RotatingFileHandler

from coach.config import Settings, save_settings
from coach.trace import logs_dir, new_call_id, record, redact, truncate


def read(cat):
    return (logs_dir() / f"{cat}.log").read_text(encoding="utf-8")


def test_disabled_by_default_writes_nothing(coach_home):
    record("claude", "abc", "requête", prompt="x")
    assert not (logs_dir() / "claude.log").exists()


def test_enabled_writes_header_and_json(coach_home):
    save_settings(Settings(trace_claude=True))
    record("claude", "abc12345", "requête", prompt="Bonjour é")
    text = read("claude")
    assert "[abc12345] requête" in text
    assert '"prompt": "Bonjour é"' in text
    assert not (logs_dir() / "garmin.log").exists()


def test_toggle_takes_effect_without_restart(coach_home):
    save_settings(Settings(trace_garmin=True))
    record("garmin", "1", "a")
    save_settings(Settings(trace_garmin=False))
    record("garmin", "2", "b")
    text = read("garmin")
    assert "[1] a" in text and "[2] b" not in text


def test_redact_keys_and_literal_secrets():
    out = redact(
        {"password": "p", "nested": [{"oauth2_token": "t", "ok": 1}],
         "Authorization": "Bearer z", "text": "clé sk-ant-123 ici"},
        ["sk-ant-123"],
    )
    assert out == {"password": "***", "nested": [{"oauth2_token": "***", "ok": 1}],
                   "Authorization": "***", "text": "clé *** ici"}


def test_record_masks_settings_secrets(coach_home):
    save_settings(Settings(trace_claude=True, anthropic_api_key="sk-ant-SECRET", turso_token="tt-SECRET"))
    record("claude", "1", "requête", prompt="sk-ant-SECRET et tt-SECRET")
    assert "SECRET" not in read("claude")


def test_unserializable_values_are_stringified(coach_home):
    save_settings(Settings(trace_garmin=True))
    record("garmin", "1", "appel", d=date(2026, 11, 17), b=b"\xff", o=object())
    assert '"2026-11-17"' in read("garmin")


def test_write_failure_is_swallowed(coach_home, monkeypatch):
    save_settings(Settings(trace_claude=True))

    def boom(*a):
        raise OSError("disque plein")

    monkeypatch.setattr(RotatingFileHandler, "emit", boom)
    record("claude", "1", "requête")  # ne lève pas


def test_follows_coach_home_change(tmp_path, monkeypatch):
    for name in ("a", "b"):
        monkeypatch.setenv("COACH_HOME", str(tmp_path / name))
        save_settings(Settings(trace_claude=True))
        record("claude", name, "e")
    assert "[b] e" in (tmp_path / "b" / "logs" / "claude.log").read_text(encoding="utf-8")
    assert "[b] e" not in (tmp_path / "a" / "logs" / "claude.log").read_text(encoding="utf-8")


def test_truncate():
    assert truncate("abcdef", 3) == "abc… [tronqué, 6 caractères au total]"
    assert truncate("abc", 3) == "abc"


def test_new_call_id_is_8_hex():
    cid = new_call_id()
    assert len(cid) == 8 and int(cid, 16) >= 0
