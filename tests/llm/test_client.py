import pytest

from coach.llm.client import ask_structured, extract_json
from coach.llm.provider import FakeLLMProvider, LLMInvalidResponse, LLMUsageLimit
from coach.llm.usage import CallUsage, UsageMeter
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


VALID = '{"analysis":"ok","changes":[]}'
U = CallUsage(mode="cli", model="m", input_tokens=100, output_tokens=10, cost_usd=0.5, duration_ms=1000)


def test_meter_sums_two_attempts():
    meter = UsageMeter()
    ask_structured(FakeLLMProvider(["pas du json", VALID], usage=U), "s", "p", AdjustmentResponse, meter=meter)
    assert (meter.attempts, meter.input_tokens, meter.output_tokens, meter.cost_usd, meter.duration_ms) == (
        2, 200, 20, 1.0, 2000)
    assert (meter.mode, meter.model) == ("cli", "m")


def test_meter_filled_on_final_failure():
    meter = UsageMeter()
    with pytest.raises(LLMInvalidResponse):
        ask_structured(FakeLLMProvider(["x", "y"], usage=U), "s", "p", AdjustmentResponse, meter=meter)
    assert meter.attempts == 2


class RaisingProvider:
    def __init__(self, usage):
        self.usage = usage
        self.last_usage = None

    def complete(self, system, prompt):
        self.last_usage = self.usage
        raise LLMUsageLimit("limit")


def test_meter_counts_call_that_raised():
    meter = UsageMeter()
    with pytest.raises(LLMUsageLimit):
        ask_structured(RaisingProvider(U), "s", "p", AdjustmentResponse, meter=meter)
    assert meter.attempts == 1 and meter.cost_usd == 0.5


def test_meter_ignores_call_without_usage():
    meter = UsageMeter()
    with pytest.raises(LLMUsageLimit):
        ask_structured(RaisingProvider(None), "s", "p", AdjustmentResponse, meter=meter)
    assert meter.attempts == 0 and meter.cost_usd is None


def test_meter_cost_none_if_one_attempt_unknown():
    meter = UsageMeter()
    meter.add(U)
    meter.add(CallUsage(mode="api", model="x", input_tokens=1, output_tokens=1, cost_usd=None, duration_ms=1))
    assert meter.cost_usd is None and meter.mode == "api"
