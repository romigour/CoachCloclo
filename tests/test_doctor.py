import socket
import subprocess
import sys
from datetime import date

from coach.doctor import Check, fix, run_checks
from coach.garmin.port import FakeGarminClient, GarminAuthRequired
from coach.llm.provider import FakeLLMProvider, LLMUnavailable, LLMUsageLimit


class FailingLLM:
    def __init__(self, exc):
        self.exc = exc

    def complete(self, system, prompt):
        raise self.exc


class AuthFailGarmin:
    def today(self):
        raise GarminAuthRequired("expiré")

    def metrics(self):
        raise GarminAuthRequired("expiré")


def by_name(checks, name):
    return next(c for c in checks if c.name == name)


def test_check_order_and_names(coach_home):
    names = [c.name for c in run_checks(live=False, which=lambda n: "/x")]
    assert names == ["python", "garminconnect", "claude_cli", "claude_auth",
                     "garmin_tokens", "data_dir", "port"]


def test_missing_claude_cli_reported(coach_home):
    checks = run_checks(live=False, which=lambda n: None if n == "claude" else "/x")
    c = by_name(checks, "claude_cli")
    assert not c.ok and c.fixable


def test_claude_cli_check_finds_local_bin(coach_home, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    name = "claude.exe" if sys.platform == "win32" else "claude"
    exe = tmp_path / ".local" / "bin" / name
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    c = by_name(run_checks(live=False, which=lambda n: None if n == "claude" else "/x"), "claude_cli")
    assert c.ok and str(exe) in c.detail


def test_usage_limit_reported_on_auth_check(coach_home):
    c = by_name(run_checks(llm_factory=lambda: FailingLLM(LLMUsageLimit()),
                           garmin_factory=lambda: FakeGarminClient(), which=lambda n: "/x"),
                "claude_auth")
    assert not c.ok and "limite" in c.detail


def test_expired_login_reported_on_auth_check(coach_home):
    c = by_name(run_checks(llm_factory=lambda: FailingLLM(LLMUnavailable("x")),
                           garmin_factory=lambda: FakeGarminClient(), which=lambda n: "/x"),
                "claude_auth")
    assert not c.ok and "non connecté" in c.detail
    assert "claude" in c.fix_hint and c.fixable


def test_claude_auth_ok(coach_home):
    c = by_name(run_checks(llm_factory=lambda: FakeLLMProvider(['{"ok":true}']),
                           garmin_factory=lambda: FakeGarminClient(), which=lambda n: "/x"),
                "claude_auth")
    assert c.ok


def test_garmin_auth_required_reported(coach_home):
    c = by_name(run_checks(garmin_factory=lambda: AuthFailGarmin(),
                           llm_factory=lambda: FakeLLMProvider(['{"ok":true}']),
                           which=lambda n: "/x"), "garmin_tokens")
    assert not c.ok and c.fixable and "login-garmin" in c.fix_hint


def test_garmin_ok(coach_home):
    c = by_name(run_checks(garmin_factory=lambda: FakeGarminClient(today=date(2026, 11, 4)),
                           llm_factory=lambda: FakeLLMProvider(['{"ok":true}']),
                           which=lambda n: "/x"), "garmin_tokens")
    assert c.ok


def test_offline_skips_network_checks(coach_home):
    def boom(*a, **k):
        raise AssertionError("appel réseau en mode hors ligne")

    checks = run_checks(live=False, offline=True, which=boom, runner=boom,
                        garmin_factory=boom, llm_factory=boom)
    for name in ("claude_cli", "claude_auth", "garmin_tokens"):
        c = by_name(checks, name)
        assert c.ok and c.detail == "non vérifié (hors ligne)"


def test_port_busy_reported(coach_home):
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen()
    try:
        c = by_name(run_checks(live=False, which=lambda n: "/x", port=s.getsockname()[1]), "port")
        assert not c.ok
    finally:
        s.close()


def test_fix_data_dir_creates_folder(tmp_path):
    target = tmp_path / "a" / "b"
    c = Check(name="data_dir", ok=False, detail="", fix_hint=None, fixable=True)
    assert fix(c, data_path=target) is True
    assert target.is_dir()


def test_fix_claude_cli_runs_installer():
    calls, kws = [], []

    def runner(args, **kw):
        calls.append(args)
        kws.append(kw)
        return subprocess.CompletedProcess(args, 0)

    c = Check(name="claude_cli", ok=False, detail="", fix_hint=None, fixable=True)
    assert fix(c, runner=runner) is True
    assert "claude.ai/install" in " ".join(calls[0])
    # chemin terminal (coach doctor --fix) : la progression doit rester visible
    assert kws[0] == {}


def test_auth_reports_cli_absent_when_cli_check_failed(coach_home):
    def boom():
        raise AssertionError("pas d'appel Claude sans CLI")

    c = by_name(run_checks(llm_factory=boom, garmin_factory=lambda: FakeGarminClient(),
                           which=lambda n: None if n == "claude" else "/x"), "claude_auth")
    assert not c.ok and c.detail == "CLI absent" and "non connecté" not in c.detail
    assert c.fixable  # corrigé après l'installation du CLI, dans la même passe de --fix


def test_api_mode_auth_failure_not_fixable_by_claude_login(coach_home):
    from coach.config import load_settings, save_settings

    save_settings(load_settings().model_copy(update={"llm_mode": "api"}))
    c = by_name(run_checks(llm_factory=lambda: FailingLLM(LLMUnavailable("clé refusée")),
                           garmin_factory=lambda: FakeGarminClient(), which=lambda n: "/x"),
                "claude_auth")
    assert not c.ok and not c.fixable


def test_fix_claude_auth_runs_claude_interactively():
    calls, said = [], []

    def runner(args, **kw):
        calls.append((args, kw))
        return subprocess.CompletedProcess(args, 0)

    c = Check(name="claude_auth", ok=False, detail="", fix_hint="x", fixable=True)
    assert fix(c, runner=runner, which=lambda n: "/bin/claude", echo=said.append) is True
    assert calls == [(["/bin/claude"], {})]  # stdin/stdout hérités : session interactive
    assert said == ["Connecte-toi dans Claude puis tape /exit pour revenir"]


def test_fix_claude_auth_without_cli_fails():
    def runner(args, **kw):
        raise AssertionError("ne doit pas être lancé")

    c = Check(name="claude_auth", ok=False, detail="CLI absent", fix_hint="x", fixable=True)
    assert fix(c, runner=runner, which=lambda n: None, echo=lambda m: None) is False


def test_fix_claude_auth_not_fixable():
    c = Check(name="claude_auth", ok=False, detail="", fix_hint="x", fixable=False)
    assert fix(c) is False


def _turso(coach_home):
    from coach.config import load_settings, save_settings

    s = load_settings()
    s.storage_mode, s.turso_url, s.turso_token = "turso", "libsql://x.turso.io", "t"
    save_settings(s)


def test_doctor_checks_cloud_when_enabled(coach_home, monkeypatch):
    from coach.storage.cloud_errors import CloudUnreachable

    _turso(coach_home)

    def boom(source):
        raise CloudUnreachable("Base cloud injoignable")

    monkeypatch.setattr("coach.doctor.probe", boom)
    checks = run_checks(live=False, which=lambda n: "/x")
    c = by_name(checks, "cloud_db")
    assert not c.ok and "injoignable" in c.detail


def test_doctor_cloud_ok_when_probe_succeeds(coach_home, monkeypatch):
    from unittest.mock import MagicMock

    _turso(coach_home)
    monkeypatch.setattr("coach.doctor.probe", lambda source: MagicMock())
    assert by_name(run_checks(live=False, which=lambda n: "/x"), "cloud_db").ok


def test_doctor_no_cloud_check_in_local_mode(coach_home):
    assert "cloud_db" not in [c.name for c in run_checks(live=False, which=lambda n: "/x")]


def test_doctor_cloud_check_skipped_offline(coach_home, monkeypatch):
    _turso(coach_home)

    def boom(source):
        raise AssertionError("pas d'appel réseau hors ligne")

    monkeypatch.setattr("coach.doctor.probe", boom)
    c = by_name(run_checks(live=False, offline=True, which=lambda n: "/x"), "cloud_db")
    assert c.ok and c.detail == "non vérifié (hors ligne)"
