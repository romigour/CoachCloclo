import pytest

from coach.llm.client import ask_structured, extract_json
from coach.llm.provider import FakeLLMProvider, LLMInvalidResponse
from coach.llm.schemas import AdjustmentResponse


def test_ask_structured_retries_once_with_errors():
    fake = FakeLLMProvider(["pas du json", '```json\n{"analysis":"ok","changes":[]}\n```'])
    out = ask_structured(fake, "s", "p", AdjustmentResponse)
    assert out.analysis == "ok" and "invalide" in fake.calls[1]
    assert fake.calls[1].startswith("p")


def test_ask_structured_gives_up_after_second_failure():
    fake = FakeLLMProvider(["x", "y"])
    with pytest.raises(LLMInvalidResponse):
        ask_structured(fake, "s", "p", AdjustmentResponse)
    assert len(fake.calls) == 2


def test_business_validation_triggers_retry():
    fake = FakeLLMProvider(['{"analysis":"a","changes":[]}', '{"analysis":"b","changes":[]}'])
    calls = iter([["erreur"], []])
    out = ask_structured(fake, "s", "p", AdjustmentResponse, validate=lambda _: next(calls))
    assert out.analysis == "b" and "erreur" in fake.calls[1]


def test_pydantic_errors_are_readable_french():
    fake = FakeLLMProvider(['{"changes":[]}', '{"analysis":"ok","changes":[]}'])
    ask_structured(fake, "s", "p", AdjustmentResponse)
    assert "analysis" in fake.calls[1]


def test_extract_json_variants():
    assert extract_json('blabla {"a": "}{", "b": {"c": 1}} fin {"z":1}') == '{"a": "}{", "b": {"c": 1}}'
    assert extract_json('```json\n{"a":1}\n```') == '{"a":1}'
    assert extract_json('x {"a":"q\\"}"} y') == '{"a":"q\\"}"}'
    assert extract_json("rien") is None
    assert extract_json("{ jamais fermé") is None
