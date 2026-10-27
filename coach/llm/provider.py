"""Fournisseurs LLM : CLI Claude Code (abonnement) ou API Anthropic."""

import json
import shutil
import subprocess
from typing import Protocol

from coach.config import Settings


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


_AUTH_WORDS = ("login", "authenticate", "not logged in", "unauthorized", "invalid api key")
_NOT_LOGGED = "CLI claude non connecté : lance `claude` pour te connecter"


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
    """

    def __init__(self, executable: str = "claude", timeout_s: int = 180,
                 runner=subprocess.run, which=shutil.which):
        self.executable = executable
        self.timeout_s = timeout_s
        self.runner = runner
        self.which = which

    def complete(self, system: str, prompt: str) -> str:
        exe = self.which(self.executable)
        if exe is None:
            raise LLMUnavailable("CLI claude introuvable")
        args = [exe, "-p", "--output-format", "json", "--system-prompt", system,
                "--tools", "", "--no-session-persistence"]
        try:
            proc = self.runner(args, input=prompt, encoding="utf-8", capture_output=True,
                               timeout=self.timeout_s)
        except FileNotFoundError as e:
            raise LLMUnavailable("CLI claude introuvable") from e
        except subprocess.TimeoutExpired as e:
            raise LLMTimeout(f"Claude n'a pas répondu en {self.timeout_s} s") from e
        stdout, stderr = proc.stdout or "", proc.stderr or ""
        try:
            envelope = json.loads(stdout)
            if not isinstance(envelope, dict):
                raise ValueError("enveloppe inattendue")
        except ValueError:
            if _mentions_auth(stdout, stderr):
                raise LLMUnavailable(_NOT_LOGGED) from None
            detail = (stderr.strip() or stdout.strip())[:500]
            raise LLMError(f"Réponse illisible du CLI claude (code {proc.returncode}) : {detail}") from None
        text = str(envelope.get("result", ""))
        if envelope.get("is_error"):
            if "limit" in text.lower():
                raise LLMUsageLimit(text)
            if _mentions_auth(text):
                raise LLMUnavailable(_NOT_LOGGED)
            raise LLMError(f"Erreur du CLI claude : {text[:500]}")
        return text


class AnthropicApiProvider:
    """Appelle l'API Anthropic (clé API de l'utilisateur)."""

    def __init__(self, api_key: str, model: str, client=None):
        import anthropic

        self._anthropic = anthropic
        self.model = model
        self.client = client if client is not None else anthropic.Anthropic(api_key=api_key)

    def complete(self, system: str, prompt: str) -> str:
        a = self._anthropic
        try:
            msg = self.client.messages.create(
                model=self.model, max_tokens=16000, system=system,
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
        return "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")


class FakeLLMProvider:
    """Fournisseur de test : renvoie les réponses dans l'ordre."""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls: list[str] = []

    def complete(self, system: str, prompt: str) -> str:
        self.calls.append(prompt)
        if not self._responses:
            raise LLMError("FakeLLMProvider: plus de réponse prévue")
        return self._responses.pop(0)


def provider_from_settings(s: Settings) -> LLMProvider:
    if s.llm_mode == "api":
        if not s.anthropic_api_key:
            raise LLMUnavailable("Clé API Anthropic manquante")
        return AnthropicApiProvider(s.anthropic_api_key, s.anthropic_model)
    return ClaudeCliProvider()
