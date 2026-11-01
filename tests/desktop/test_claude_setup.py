import subprocess
from types import SimpleNamespace

from coach.desktop.claude_setup import INSTALL_CMD, ClaudeSetup
from coach.proc import NO_WINDOW

EXE = "C:/claude.exe"
CONSOLE = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)


def _runner(stdout="", returncode=0, calls=None):
    def run(args, **kwargs):
        if calls is not None:
            calls.append((args, kwargs))
        return SimpleNamespace(stdout=stdout, stderr="", returncode=returncode)

    return run


class FakeProc:
    def __init__(self, code=None):
        self.code = code
        self.killed = False

    def poll(self):
        return self.code

    def kill(self):
        self.killed = True


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def _setup(stdout='{"loggedIn": false}', procs=None, clock=None, **kw):
    popen_calls = []

    def popen(args, **kwargs):
        proc = procs[len(popen_calls)] if procs else FakeProc()
        popen_calls.append((args, kwargs, proc))
        return proc

    s = ClaudeSetup(
        runner=kw.pop("runner", _runner(stdout)),
        popen=popen,
        find=lambda: EXE,
        clock=clock or Clock(),
        **kw,
    )
    return s, popen_calls


def test_status_cli_absent():
    st = ClaudeSetup(find=lambda: None).status()
    assert st["claude_cli"] is False
    assert st["claude_auth"] is False
    assert st["claude_step"] == "idle"


def test_status_logged_in():
    s, _ = _setup('{"loggedIn": true}')
    st = s.status()
    assert st["claude_cli"] is True and st["claude_auth"] is True


def test_status_logged_out():
    s, _ = _setup('{"loggedIn": false}')
    assert s.status()["claude_auth"] is False


def test_status_invalid_json():
    s, _ = _setup("oops")
    assert s.status()["claude_auth"] is False


def test_status_runner_error():
    def boom(*a, **k):
        raise OSError("x")

    s, _ = _setup(runner=boom)
    assert s.status()["claude_auth"] is False


def test_status_runs_without_window():
    calls = []
    s, _ = _setup(runner=_runner('{"loggedIn": true}', calls=calls))
    s.status()
    args, kwargs = calls[0]
    assert args == [EXE, "auth", "status", "--json"]
    assert kwargs["creationflags"] == NO_WINDOW
    assert kwargs["timeout"] == 15


def test_install_success():
    calls = []
    s, _ = _setup(runner=_runner(calls=calls))
    s.start_install()
    s._thread.join(5)
    assert calls[0][0] == INSTALL_CMD
    assert calls[0][1]["creationflags"] == NO_WINDOW
    assert s.status()["claude_step"] == "idle"


def test_install_failure():
    s, _ = _setup(runner=_runner(returncode=1))
    s.start_install()
    s._thread.join(5)
    st = s.status()
    assert st["claude_step"] == "failed" and st["claude_error"]


def test_install_oserror():
    def boom(*a, **k):
        raise OSError("pas de powershell")

    s, _ = _setup(runner=boom)
    s.start_install()
    s._thread.join(5)
    assert s.status()["claude_step"] == "failed"


def test_login_spawns_without_console():
    s, popen_calls = _setup()
    s.start_login()
    args, kwargs, _ = popen_calls[0]
    assert args == [EXE, "auth", "login", "--claudeai"]
    assert kwargs["creationflags"] == NO_WINDOW
    assert kwargs["stdin"] == subprocess.DEVNULL
    assert s.status()["claude_step"] == "logging_in"


def test_login_console_fallback():
    s, popen_calls = _setup(needs_console=True)
    s.start_login()
    _, kwargs, _ = popen_calls[0]
    assert kwargs["creationflags"] == CONSOLE
    assert "stdin" not in kwargs and "stdout" not in kwargs


def test_login_cli_absent():
    s = ClaudeSetup(find=lambda: None, popen=lambda *a, **k: 1 / 0)
    s.start_login()
    st = s.status()
    assert st["claude_step"] == "failed" and st["claude_error"]


def test_login_completes():
    out = ['{"loggedIn": false}']
    s, _ = _setup(runner=lambda *a, **k: SimpleNamespace(stdout=out[0], returncode=0))
    s.start_login()
    assert s.status()["claude_step"] == "logging_in"
    out[0] = '{"loggedIn": true}'
    st = s.status()
    assert st["claude_step"] == "idle" and st["claude_auth"] is True


def test_login_times_out():
    clock = Clock()
    proc = FakeProc()
    s, _ = _setup(procs=[proc], clock=clock)
    s.start_login()
    clock.t = 301
    st = s.status()
    assert proc.killed is True
    assert st["claude_step"] == "failed"
    assert "expiré" in st["claude_error"]


def test_login_process_exits_nonzero():
    s, _ = _setup(procs=[FakeProc(code=1)])
    s.start_login()
    st = s.status()
    assert st["claude_step"] == "failed"
    assert "échoué" in st["claude_error"]


def test_login_not_restarted_while_running():
    s, popen_calls = _setup()
    s.start_login()
    s.start_login()
    assert len(popen_calls) == 1
