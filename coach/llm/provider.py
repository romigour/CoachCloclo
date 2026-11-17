"""Fournisseurs LLM : CLI Claude Code (abonnement) ou API Anthropic."""

import dataclasses
import json
import logging
import shutil
import subprocess
import time
from collections.abc import Callable
from typing import Protocol

from coach import trace

from coach.config import Settings, data_dir
from coach.llm.usage import CallUsage, api_cost_usd
from coach.proc import NO_WINDOW, find_claude


class LLMError(Exception):
    """Erreur générique d'appel au LLM."""


class LLMUnavailable(LLMError):
    """CLI absent ou non connecté, clé API absente ou refusée."""


class LLMUsageLimit(LLMError):
    """Limite d'usage atteinte."""


class LLMTimeout(LLMError):
    """Délai dépassé."""


class LLMInvalidResponse(LLMError):
    """Réponse invalide après nouvelle tentative."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("Réponse invalide de Claude : " + " ; ".join(errors))


class LLMProvider(Protocol):
    def complete(self, system: str, prompt: str) -> str: ...


def _n(value) -> int:
    """Compteur de tokens : absent ou invalide → 0."""
    return value if isinstance(value, int) else 0


def _cli_usage(envelope: dict) -> CallUsage:
    usage = envelope.get("usage") if isinstance(envelope.get("usage"), dict) else {}
    models = envelope.get("modelUsage")
    cost = envelope.get("total_cost_usd")
    return CallUsage(
        mode="cli",
        model=next(iter(models), None) if isinstance(models, dict) else None,
        input_tokens=_n(usage.get("input_tokens")) + _n(usage.get("cache_creation_input_tokens"))
        + _n(usage.get("cache_read_input_tokens")),
        output_tokens=_n(usage.get("output_tokens")),
        cost_usd=float(cost) if isinstance(cost, (int, float)) else None,
        duration_ms=_n(envelope.get("duration_ms")),
    )


_AUTH_WORDS = ("login", "authenticate", "not logged in", "unauthorized", "invalid api key")
_NOT_LOGGED = "CLI claude non connecté : lance `claude` pour te connecter"


def _text(v) -> str:
    """Sortie partielle d'un sous-processus : bytes, texte ou rien."""
    if v is None:
        return ""
    return v.decode("utf-8", errors="replace") if isinstance(v, bytes) else str(v)


def _traced(provider, run: Callable[[str], str]) -> str:
    """Exécute `run(call_id)` en consignant réponse ou erreur dans le journal Claude."""
    call_id = trace.new_call_id()
    try:
        text = run(call_id)
    except Exception as e:
        trace.record("claude", call_id, "erreur", level=logging.ERROR,
                     type=type(e).__name__, message=str(e))
        raise
    usage = provider.last_usage
    trace.record("claude", call_id, "réponse", text=text,
                 usage=dataclasses.asdict(usage) if usage is not None else None)
    return text


def _mentions_auth(*texts: str) -> bool:
    blob = " ".join(texts).lower()
    return any(w in blob for w in _AUTH_WORDS)


class ClaudeCliProvider:
    """Appelle `claude -p` en sous-processus (abonnement de l'utilisateur).

    Drapeaux retenus après `claude --help` (Claude Code 2.1.139) :
    `-p` (non interactif), `--output-format json` (enveloppe unique),
    `--system-prompt <texte>` (remplace le prompt système par défaut),
    `--tools ""` (désactive tous les outils intégrés ; pas besoin de
    `--disallowedTools`) et `--no-session-persistence` (n'écrit pas dans
    l'historique de sessions). Le prompt passe par stdin.

    Isolation : `--strict-mcp-config` sans `--mcp-config` (aucun serveur MCP),
    `--disable-slash-commands` (aucune skill) et exécution dans un dossier
    neutre vide (`<données>/claude-cwd`) pour qu'aucun CLAUDE.md, .mcp.json
    ou hook de projet ne s'applique. `--bare` est écarté (il n'accepte pas
    l'OAuth de l'abonnement) ; `--setting-sources` n'est pas utilisé (impact
    sur l'authentification non vérifiable). Pas de `--system-prompt-file` dans
    l'aide : le prompt système passe en argument (limite ~32 k caractères sous
    Windows).
    """

    def __init__(self, executable: str = "claude", timeout_s: int = 180,
                 runner=subprocess.run, which=shutil.which, cwd=None):
        self.executable = executable
        self.timeout_s = timeout_s
        self.runner = runner
        self.which = which
        self.cwd = cwd
        self.last_usage: CallUsage | None = None

    def complete(self, system: str, prompt: str) -> str:
        return _traced(self, lambda cid: self._run(system, prompt, cid))

    def _run(self, system: str, prompt: str, call_id: str) -> str:
        self.last_usage = None
        exe = find_claude(self.which)
        if exe is None:
            raise LLMUnavailable("CLI claude introuvable")
        args = [exe, "-p", "--output-format", "json", "--system-prompt", system,
                "--tools", "", "--no-session-persistence",
                "--strict-mcp-config", "--disable-slash-commands"]
        cwd = self.cwd if self.cwd is not None else data_dir() / "claude-cwd"
        cwd.mkdir(parents=True, exist_ok=True)
        shown = list(args)
        shown[shown.index("--system-prompt") + 1] = "<prompt système ci-dessous>"
        trace.record("claude", call_id, "requête", mode="cli", args=shown, timeout_s=self.timeout_s,
                     system=system, prompt=prompt)
        started = time.monotonic()
        try:
            proc = self.runner(args, input=prompt, encoding="utf-8", capture_output=True,
                               timeout=self.timeout_s, cwd=cwd, creationflags=NO_WINDOW)
        except FileNotFoundError as e:
            raise LLMUnavailable("CLI claude introuvable") from e
        except subprocess.TimeoutExpired as e:
            trace.record("claude", call_id, "délai dépassé", level=logging.WARNING,
                         duration_ms=int((time.monotonic() - started) * 1000),
                         stdout=_text(e.stdout), stderr=_text(e.stderr))
            raise LLMTimeout(f"Claude n'a pas répondu en {self.timeout_s} s") from e
        stdout, stderr = proc.stdout or "", proc.stderr or ""
        trace.record("claude", call_id, "sortie", returncode=proc.returncode, stdout=stdout, stderr=stderr,
                     duration_ms=int((time.monotonic() - started) * 1000))
        try:
            envelope = json.loads(stdout)
            if not isinstance(envelope, dict):
                raise ValueError("enveloppe inattendue")
        except ValueError:
            if _mentions_auth(stdout, stderr):
                raise LLMUnavailable(_NOT_LOGGED) from None
            detail = (stderr.strip() or stdout.strip())[:500]
            raise LLMError(f"Réponse illisible du CLI claude (code {proc.returncode}) : {detail}") from None
        self.last_usage = _cli_usage(envelope)
        result = envelope.get("result")
        text = "" if result is None else str(result)
        if envelope.get("is_error"):
            if "limit" in text.lower():
                raise LLMUsageLimit(text)
            if _mentions_auth(text):
                raise LLMUnavailable(_NOT_LOGGED)
            raise LLMError(f"Erreur du CLI claude : {text[:500]}")
        if result is None:
            raise LLMError(f"Réponse Claude vide (subtype {envelope.get('subtype')})")
        return text


MAX_TOKENS = 32000


class AnthropicApiProvider:
    """Appelle l'API Anthropic (clé API de l'utilisateur)."""

    def __init__(self, api_key: str, model: str, client=None):
        import anthropic

        self._anthropic = anthropic
        self.model = model
        self.client = client if client is not None else anthropic.Anthropic(api_key=api_key, timeout=180)
        self.last_usage: CallUsage | None = None

    def complete(self, system: str, prompt: str) -> str:
        return _traced(self, lambda cid: self._run(system, prompt, cid))

    def _run(self, system: str, prompt: str, call_id: str) -> str:
        a = self._anthropic
        self.last_usage = None
        trace.record("claude", call_id, "requête", mode="api", model=self.model, max_tokens=MAX_TOKENS,
                     system=system, prompt=prompt)
        started = time.monotonic()
        try:
            msg = self.client.messages.create(
                model=self.model, max_tokens=MAX_TOKENS, system=system,
                messages=[{"role": "user", "content": prompt}],
            )
        except a.RateLimitError as e:
            raise LLMUsageLimit("Limite d'usage de l'API atteinte") from e
        except a.AuthenticationError as e:
            raise LLMUnavailable("Clé API Anthropic refusée") from e
        except a.APITimeoutError as e:
            raise LLMTimeout("Délai dépassé pour l'API Anthropic") from e
        except a.APIError as e:
            raise LLMError(f"Erreur de l'API Anthropic : {e}") from e
        self.last_usage = self._usage(msg, int((time.monotonic() - started) * 1000))
        return "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")


    def _usage(self, msg, duration_ms: int) -> CallUsage:
        u = getattr(msg, "usage", None)
        fresh, out = _n(getattr(u, "input_tokens", None)), _n(getattr(u, "output_tokens", None))
        write = _n(getattr(u, "cache_creation_input_tokens", None))
        read = _n(getattr(u, "cache_read_input_tokens", None))
        return CallUsage(mode="api", model=self.model, input_tokens=fresh + write + read, output_tokens=out,
                         cost_usd=api_cost_usd(self.model, fresh, out, write, read), duration_ms=duration_ms)


class FakeLLMProvider:
    """Fournisseur de test : renvoie les réponses dans l'ordre."""

    def __init__(self, responses: list[str], usage: CallUsage | None = None):
        self._responses = list(responses)
        self.calls: list[str] = []
        self.usage = usage
        self.last_usage: CallUsage | None = None

    def complete(self, system: str, prompt: str) -> str:
        self.calls.append(prompt)
        self.last_usage = self.usage
        if not self._responses:
            raise LLMError("FakeLLMProvider: plus de réponse prévue")
        return self._responses.pop(0)


def provider_from_settings(s: Settings) -> LLMProvider:
    if s.llm_mode == "api":
        if not s.anthropic_api_key:
            raise LLMUnavailable("Clé API Anthropic manquante")
        return AnthropicApiProvider(s.anthropic_api_key, s.anthropic_model)
    return ClaudeCliProvider()
