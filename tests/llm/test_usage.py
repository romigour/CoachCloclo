import pytest

from coach.llm.usage import api_cost_usd, to_eur


def test_api_cost_sonnet():
    assert api_cost_usd("claude-sonnet-5-5", 1_000_000, 100_000) == pytest.approx(3.0)


def test_api_cost_with_cache():
    assert api_cost_usd("claude-opus-5-5", 0, 0, cache_write=1_000_000, cache_read=1_000_000) == pytest.approx(5.2)


def test_api_cost_unknown_model_is_none():
    assert api_cost_usd("modele-perso", 1000, 1000) is None


def test_to_eur():
    assert to_eur(1.0) == pytest.approx(0.92)
    assert to_eur(None) is None
