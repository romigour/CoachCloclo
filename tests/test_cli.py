import pytest
from typer.testing import CliRunner

import coach.cli as cli
from coach.config import load_settings
from coach.doctor import Check

runner = CliRunner()


def test_doctor_exit_code(monkeypatch):
    bad = [Check(name="python", ok=True, detail="3.12", fix_hint=None, fixable=False),
           Check(name="port", ok=False, detail="occupé", fix_hint="libère 8765", fixable=False)]
    monkeypatch.setattr(cli, "run_checks", lambda **kw: bad)
    r = runner.invoke(cli.app, ["doctor"])
    assert r.exit_code == 1
    assert "✓" in r.output and "✗" in r.output and "libère 8765" in r.output


def test_doctor_all_ok_exit_zero(monkeypatch):
    ok = [Check(name="python", ok=True, detail="3.12", fix_hint=None, fixable=False)]
    monkeypatch.setattr(cli, "run_checks", lambda **kw: ok)
    assert runner.invoke(cli.app, ["doctor"]).exit_code == 0


def test_doctor_offline_passes_flags(monkeypatch):
    seen = {}

    def fake(**kw):
        seen.update(kw)
        return []

    monkeypatch.setattr(cli, "run_checks", fake)
    runner.invoke(cli.app, ["doctor", "--offline"])
    assert seen["offline"] is True and seen["live"] is False


def test_start_lan_prompts_pin(coach_home, monkeypatch):
    got = {}

    def fake_create(**kw):
        got["kw"] = kw
        return "app"

    monkeypatch.setattr(cli, "create_app", fake_create)
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **kw: got.update(run=kw))
    r = runner.invoke(cli.app, ["start", "--lan", "--no-browser"], input="1234\n1234\n")
    assert r.exit_code == 0, r.output
    assert load_settings().pin_hash and "1234" not in load_settings().pin_hash
    assert got["kw"]["lan"] is True
    assert got["run"]["host"] == "0.0.0.0" and got["run"]["port"] == 8765


def test_start_local_no_pin(coach_home, monkeypatch):
    got = {}
    monkeypatch.setattr(cli, "create_app", lambda **kw: "app")
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **kw: got.update(kw))
    r = runner.invoke(cli.app, ["start", "--no-browser", "--port", "9000"])
    assert r.exit_code == 0, r.output
    assert got == {"host": "127.0.0.1", "port": 9000}
    assert load_settings().pin_hash is None


def test_login_garmin_with_mfa(coach_home, monkeypatch):
    calls = []

    class FakeClient:
        @classmethod
        def start_login(cls, email, password, tokenstore):
            calls.append((email, password))
            return "needs_mfa", {"s": 1}

        @classmethod
        def finish_login(cls, state, code, tokenstore):
            calls.append(("mfa", code))

    monkeypatch.setattr(cli, "GarminClient", FakeClient)
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": "secret")
    r = runner.invoke(cli.app, ["login-garmin"], input="me@x.fr\n123456\n")
    assert r.exit_code == 0, r.output
    assert calls == [("me@x.fr", "secret"), ("mfa", "123456")]
    assert "secret" not in r.output


def test_update_without_uv(monkeypatch):
    monkeypatch.setattr(cli.shutil, "which", lambda n: None)
    r = runner.invoke(cli.app, ["update"])
    assert r.exit_code == 1 and "uv" in r.output


def test_update_runs_uv(monkeypatch):
    seen = []
    monkeypatch.setattr(cli.sys, "platform", "linux")
    monkeypatch.setattr(cli.shutil, "which", lambda n: "/uv")
    monkeypatch.setattr(cli, "latest_wheel_url", lambda: "https://x/coachcloclo-0.1.0-py3-none-any.whl")
    monkeypatch.setattr(cli.subprocess, "run",
                        lambda args, **kw: seen.append(args) or type("R", (), {"returncode": 0})())
    assert runner.invoke(cli.app, ["update"]).exit_code == 0
    assert seen == [["/uv", "tool", "install", "--force", "--python", "3.12",
                     "https://x/coachcloclo-0.1.0-py3-none-any.whl"]]


def test_update_windows_hands_off_after_exit(monkeypatch):
    seen = []
    monkeypatch.setattr(cli.sys, "platform", "win32")
    monkeypatch.setattr(cli.shutil, "which", lambda n: "/uv")
    monkeypatch.setattr(cli, "latest_wheel_url", lambda: "https://x/c.whl")
    monkeypatch.setattr(cli, "running_coach_processes", lambda: [])
    monkeypatch.setattr(cli, "update_after_exit", seen.append)
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **kw: pytest.fail("uv lancé depuis le venv"))
    r = runner.invoke(cli.app, ["update"])
    assert r.exit_code == 0, r.output
    assert seen == [["/uv", "tool", "install", "--force", "--python", "3.12", "https://x/c.whl"]]
    assert "nouvelle fenêtre" in r.output


def test_update_windows_refuses_while_coach_runs(monkeypatch):
    monkeypatch.setattr(cli.sys, "platform", "win32")
    monkeypatch.setattr(cli.shutil, "which", lambda n: "/uv")
    monkeypatch.setattr(cli, "latest_wheel_url", lambda: "https://x/c.whl")
    monkeypatch.setattr(cli, "running_coach_processes", lambda: [(11824, "coach.exe start")])
    monkeypatch.setattr(cli, "update_after_exit", lambda install: pytest.fail("mise à jour lancée"))
    r = runner.invoke(cli.app, ["update"])
    assert r.exit_code == 1 and "11824" in r.output and "coach.exe start" in r.output


def test_running_coach_processes_excludes_self(monkeypatch):
    out = (f"{cli.os.getpid()}\tcoach.exe update\n{cli.os.getppid()}\tcoach.exe update\n"
           "11824\tcoach.exe start\n")
    monkeypatch.setattr(cli.subprocess, "run",
                        lambda *a, **kw: type("R", (), {"stdout": out})())
    assert cli.running_coach_processes() == [(11824, "coach.exe start")]


def test_update_without_release(monkeypatch):
    monkeypatch.setattr(cli.shutil, "which", lambda n: "/uv")

    def no_release():
        raise RuntimeError("Aucune wheel")
    monkeypatch.setattr(cli, "latest_wheel_url", no_release)
    r = runner.invoke(cli.app, ["update"])
    assert r.exit_code == 1 and "Aucune wheel" in r.output


def test_latest_wheel_url_picks_wheel(monkeypatch):
    import io
    body = {"assets": [{"name": "notes.txt", "browser_download_url": "https://x/notes.txt"},
                       {"name": "coachcloclo-0.1.0-py3-none-any.whl",
                        "browser_download_url": "https://x/coachcloclo-0.1.0-py3-none-any.whl"}]}

    class Resp(io.StringIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(cli.urllib.request, "urlopen", lambda url, timeout: Resp(__import__("json").dumps(body)))
    assert cli.latest_wheel_url() == "https://x/coachcloclo-0.1.0-py3-none-any.whl"
