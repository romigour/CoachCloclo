import json
import subprocess
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


def fake_run(stdout="", stderr="", returncode=0, raises=None):
    def run(args, **kwargs):
        run.args, run.kwargs = args, kwargs
        if raises:
            raise raises
        return subprocess.CompletedProcess(args, returncode, stdout, stderr)

    return run


def which_ok(name):
    return "C:/bin/claude.exe"


def cli(run, which=which_ok):
    return ClaudeCliProvider(runner=run, which=which)


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
        return SimpleNamespace(content=self.blocks)


def test_api_provider_concatenates_text_blocks():
    blocks = [SimpleNamespace(type="text", text="ab"), SimpleNamespace(type="thinking"), SimpleNamespace(type="text", text="cd")]
    client = FakeClient(blocks)
    p = AnthropicApiProvider("k", "m", client=client)
    assert p.complete("sys", "hi") == "abcd"
    assert client.kwargs == {
        "model": "m",
        "max_tokens": 16000,
        "system": "sys",
        "messages": [{"role": "user", "content": "hi"}],
    }


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
