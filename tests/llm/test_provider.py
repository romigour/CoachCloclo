import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

from coach.config import Settings
from coach.llm.provider import (
    AnthropicApiProvider,
    ClaudeCliProvider,
    FakeLLMProvider,
    LLMError,
    LLMTimeout,
    LLMUnavailable,
    LLMUsageLimit,
    provider_from_settings,
)

from coach.llm.usage import CallUsage
from coach.proc import NO_WINDOW


@pytest.fixture(autouse=True)
def _isolated_home(coach_home):
    return coach_home


def fake_run(stdout="", stderr="", returncode=0, raises=None):
    def run(args, **kwargs):
        run.args, run.kwargs = args, kwargs
        if raises:
            raise raises
        return subprocess.CompletedProcess(args, returncode, stdout, stderr)

    return run


def which_ok(name):
    return "C:/bin/claude.exe"


def cli(run, which=which_ok, cwd=None):
    return ClaudeCliProvider(runner=run, which=which, cwd=cwd)


def test_cli_provider_parses_envelope():
    run = fake_run(stdout=json.dumps({"type": "result", "is_error": False, "result": '{"a":1}'}))
    assert cli(run).complete("sys", "p") == '{"a":1}'
    assert run.kwargs["input"] == "p" and "--output-format" in run.args
    assert run.args[0] == "C:/bin/claude.exe"
    assert run.args[run.args.index("--system-prompt") + 1] == "sys"
    assert run.args[run.args.index("--tools") + 1] == ""
    assert "--no-session-persistence" in run.args
    assert run.kwargs["encoding"] == "utf-8" and run.kwargs["timeout"] == 180


def test_cli_usage_limit():
    run = fake_run(stdout=json.dumps({"is_error": True, "result": "Claude usage limit reached"}))
    with pytest.raises(LLMUsageLimit):
        cli(run).complete("s", "p")


def test_cli_is_error_other():
    run = fake_run(stdout=json.dumps({"is_error": True, "result": "boom"}))
    with pytest.raises(LLMError):
        cli(run).complete("s", "p")


def test_cli_missing_and_timeout():
    with pytest.raises(LLMUnavailable):
        cli(fake_run(raises=FileNotFoundError())).complete("s", "p")
    with pytest.raises(LLMUnavailable, match="introuvable"):
        cli(fake_run(), which=lambda _: None).complete("s", "p")
    with pytest.raises(LLMTimeout):
        cli(fake_run(raises=subprocess.TimeoutExpired("claude", 1))).complete("s", "p")


def test_cli_not_logged_in():
    run = fake_run(stdout="", stderr="Please run /login to authenticate", returncode=1)
    with pytest.raises(LLMUnavailable, match="non connecté"):
        cli(run).complete("s", "p")


def test_cli_nonzero_exit_non_json():
    run = fake_run(stdout="", stderr="kaboom", returncode=2)
    with pytest.raises(LLMError, match="kaboom") as ei:
        cli(run).complete("s", "p")
    assert not isinstance(ei.value, LLMUnavailable)


def test_fake_provider_records_calls():
    f = FakeLLMProvider(["a", "b"])
    assert f.complete("s", "p1") == "a" and f.complete("s", "p2") == "b"
    assert f.calls == ["p1", "p2"]


class FakeClient:
    def __init__(self, blocks=None, exc=None):
        self.kwargs = None
        self.exc = exc
        self.blocks = blocks or []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.kwargs = kwargs
        if self.exc:
            raise self.exc
        return SimpleNamespace(content=self.blocks, usage=getattr(self, "usage", None))


def test_api_provider_concatenates_text_blocks():
    blocks = [SimpleNamespace(type="text", text="ab"), SimpleNamespace(type="thinking"), SimpleNamespace(type="text", text="cd")]
    client = FakeClient(blocks)
    p = AnthropicApiProvider("k", "m", client=client)
    assert p.complete("sys", "hi") == "abcd"
    assert client.kwargs == {
        "model": "m",
        "max_tokens": 32000,
        "system": "sys",
        "messages": [{"role": "user", "content": "hi"}],
    }


def test_api_provider_client_timeout_180s(monkeypatch):
    import anthropic

    seen = {}
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: seen.update(kw) or object())
    AnthropicApiProvider("k", "m")
    assert seen == {"api_key": "k", "timeout": 180}


def test_api_provider_maps_errors():
    import anthropic
    import httpx

    req = httpx.Request("POST", "https://x")
    resp = lambda code: httpx.Response(code, request=req)  # noqa: E731
    cases = [
        (anthropic.RateLimitError("r", response=resp(429), body=None), LLMUsageLimit),
        (anthropic.AuthenticationError("a", response=resp(401), body=None), LLMUnavailable),
        (anthropic.APITimeoutError(request=req), LLMTimeout),
    ]
    for exc, expected in cases:
        with pytest.raises(expected):
            AnthropicApiProvider("k", "m", client=FakeClient(exc=exc)).complete("s", "p")


def test_provider_from_settings():
    assert isinstance(provider_from_settings(Settings()), ClaudeCliProvider)
    with pytest.raises(LLMUnavailable, match="Clé API"):
        provider_from_settings(Settings(llm_mode="api"))
    p = provider_from_settings(Settings(llm_mode="api", anthropic_api_key="k"))
    assert isinstance(p, AnthropicApiProvider)


def test_cli_isolation_flags_and_cwd(tmp_path):
    run = fake_run(stdout=json.dumps({"is_error": False, "result": "x"}))
    neutral = tmp_path / "neutral"
    cli(run, cwd=neutral).complete("s", "p")
    assert "--strict-mcp-config" in run.args and "--mcp-config" not in run.args
    assert "--disable-slash-commands" in run.args
    assert run.kwargs["cwd"] == neutral and neutral.is_dir()


def test_cli_default_cwd_is_neutral_dir_in_data_dir(coach_home):
    run = fake_run(stdout=json.dumps({"is_error": False, "result": "x"}))
    cli(run).complete("s", "p")
    assert run.kwargs["cwd"] == coach_home / "claude-cwd"


def test_cli_empty_result_is_error(tmp_path):
    for env in ({"is_error": False, "subtype": "success"}, {"is_error": False, "result": None}):
        with pytest.raises(LLMError, match="vide"):
            cli(fake_run(stdout=json.dumps(env)), cwd=tmp_path).complete("s", "p")


OK_ENVELOPE = json.dumps({"type": "result", "is_error": False, "result": "ok"})


def test_cli_runs_without_window():
    run = fake_run(stdout=OK_ENVELOPE)
    cli(run).complete("s", "p")
    assert run.kwargs["creationflags"] == NO_WINDOW


def test_cli_found_in_local_bin_when_not_on_path(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    name = "claude.exe" if sys.platform == "win32" else "claude"
    exe = tmp_path / ".local" / "bin" / name
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    run = fake_run(stdout=OK_ENVELOPE)
    cli(run, which=lambda n: None).complete("s", "p")
    assert run.args[0] == str(exe)


ENVELOPE = {
    "type": "result", "is_error": False, "result": "{}", "duration_ms": 3132, "total_cost_usd": 0.0102,
    "usage": {"input_tokens": 2, "cache_creation_input_tokens": 4864, "cache_read_input_tokens": 649,
              "output_tokens": 77},
    "modelUsage": {"claude-sonnet-5-5": {}},
}


def test_cli_records_usage(tmp_path):
    p = cli(fake_run(stdout=json.dumps(ENVELOPE)), cwd=tmp_path)
    p.complete("s", "p")
    assert p.last_usage == CallUsage(mode="cli", model="claude-sonnet-5-5", input_tokens=5515,
                                     output_tokens=77, cost_usd=0.0102, duration_ms=3132)


def test_cli_usage_kept_when_envelope_is_error(tmp_path):
    env = {**ENVELOPE, "is_error": True, "result": "usage limit reached"}
    p = cli(fake_run(stdout=json.dumps(env)), cwd=tmp_path)
    with pytest.raises(LLMUsageLimit):
        p.complete("s", "p")
    assert p.last_usage.cost_usd == 0.0102


def test_cli_usage_tolerates_missing_fields(tmp_path):
    p = cli(fake_run(stdout=json.dumps({"result": "{}"})), cwd=tmp_path)
    p.complete("s", "p")
    assert p.last_usage == CallUsage(mode="cli", model=None, input_tokens=0, output_tokens=0,
                                     cost_usd=None, duration_ms=0)


def test_cli_usage_reset_when_cli_missing(tmp_path):
    p = cli(fake_run(stdout=json.dumps(ENVELOPE)), cwd=tmp_path)
    p.complete("s", "p")
    p.which = lambda name: None
    with pytest.raises(LLMUnavailable):
        p.complete("s", "p")
    assert p.last_usage is None


def test_api_records_usage():
    client = FakeClient([SimpleNamespace(type="text", text="ok")])
    client.usage = SimpleNamespace(input_tokens=1000, output_tokens=500,
                                   cache_creation_input_tokens=None, cache_read_input_tokens=None)
    p = AnthropicApiProvider("k", "claude-sonnet-5-5", client=client)
    p.complete("s", "p")
    u = p.last_usage
    assert (u.mode, u.model, u.input_tokens, u.output_tokens) == ("api", "claude-sonnet-5-5", 1000, 500)
    assert u.cost_usd == pytest.approx(0.007)
    assert u.duration_ms >= 0


def test_fake_provider_exposes_usage():
    u = CallUsage(mode="cli", model="m", input_tokens=1, output_tokens=1, cost_usd=0.1, duration_ms=1)
    p = FakeLLMProvider(["a"], usage=u)
    p.complete("s", "p")
    assert p.last_usage == u


# --- journal de diagnostic --------------------------------------------------------------


def claude_log(home):
    return (home / "logs" / "claude.log").read_text(encoding="utf-8")


def test_cli_traces_request_output_and_response(coach_home):
    import re

    from coach.config import save_settings

    save_settings(Settings(trace_claude=True))
    env = {"result": "ok", "usage": {"input_tokens": 1, "output_tokens": 2}, "duration_ms": 5}
    cli(fake_run(stdout=json.dumps(env))).complete("SYS-PROMPT", "USER-PROMPT")
    log = claude_log(coach_home)
    assert log.index("requête") < log.index("sortie") < log.index("réponse")
    assert "SYS-PROMPT" in log and "USER-PROMPT" in log and '"text": "ok"' in log
    assert len(set(re.findall(r"\[([0-9a-f]{8})\]", log))) == 1


def test_cli_timeout_traces_partial_output(coach_home):
    from coach.config import save_settings

    save_settings(Settings(trace_claude=True))
    exc = subprocess.TimeoutExpired(["claude"], 180, output=b"partiel", stderr=None)
    with pytest.raises(LLMTimeout):
        cli(fake_run(raises=exc)).complete("s", "p")
    log = claude_log(coach_home)
    assert "requête" in log and "délai dépassé" in log and "partiel" in log


def test_cli_error_traced_and_reraised(coach_home):
    from coach.config import save_settings

    save_settings(Settings(trace_claude=True))
    with pytest.raises(LLMError):
        cli(fake_run(stdout="pas du json", returncode=1)).complete("s", "p")
    assert "erreur" in claude_log(coach_home)


def test_api_traces_request_and_response_without_key(coach_home):
    from coach.config import save_settings

    save_settings(Settings(trace_claude=True, anthropic_api_key="sk-ant-SECRET"))
    client = FakeClient([SimpleNamespace(type="text", text="ok")])
    AnthropicApiProvider("sk-ant-SECRET", "m1", client=client).complete("SYS", "USR")
    log = claude_log(coach_home)
    assert '"model": "m1"' in log and '"text": "ok"' in log and "SECRET" not in log


def test_no_trace_when_disabled(coach_home):
    cli(fake_run(stdout=json.dumps({"result": "ok"}))).complete("s", "p")
    assert not (coach_home / "logs" / "claude.log").exists()
