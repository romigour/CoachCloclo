"""Appel structuré : JSON strict validé par pydantic, une seule nouvelle tentative."""

import re
from collections.abc import Callable
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from coach.llm.provider import LLMInvalidResponse, LLMProvider

T = TypeVar("T", bound=BaseModel)

_FENCE = re.compile(r"```json\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def _balanced_object(text: str) -> str | None:
    start = text.find("{")
    if start < 0:
        return None
    depth, in_str, escaped = 0, False, False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if escaped:
                escaped = False
            elif c == "\\":
                escaped = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def extract_json(text: str) -> str | None:
    """Premier bloc ```json, sinon premier objet {...} équilibré."""
    m = _FENCE.search(text)
    if m:
        return m.group(1).strip()
    return _balanced_object(text)


def _format_errors(e: ValidationError) -> list[str]:
    out = []
    for err in e.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "(racine)"
        out.append(f"{loc} : {err['msg']}")
    return out


def _attempt(text: str, model: type[T], validate: Callable[[T], list[str]]) -> tuple[T | None, list[str]]:
    raw = extract_json(text)
    if raw is None:
        return None, ["aucun objet JSON trouvé dans la réponse"]
    try:
        obj = model.model_validate_json(raw)
    except ValidationError as e:
        return None, _format_errors(e)
    errors = validate(obj)
    return (obj, []) if not errors else (None, list(errors))


def ask_structured(provider: LLMProvider, system: str, prompt: str, model: type[T],
                   validate: Callable[[T], list[str]] = lambda _: []) -> T:
    """Appelle le LLM, valide ; une seule nouvelle tentative en cas d'échec."""
    obj, errors = _attempt(provider.complete(system, prompt), model, validate)
    if obj is not None:
        return obj
    retry = (f"{prompt}\n\nTa réponse précédente est invalide : {' ; '.join(errors)}. "
             "Renvoie uniquement le JSON corrigé.")
    obj, errors = _attempt(provider.complete(system, retry), model, validate)
    if obj is not None:
        return obj
    raise LLMInvalidResponse(errors)
