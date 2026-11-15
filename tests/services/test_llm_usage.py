import datetime as dt

import pytest

from coach.llm.provider import LLMInvalidResponse, LLMUnavailable
from coach.llm.usage import CallUsage
from coach.plan.models import LlmUsage
from coach.services.llm_usage import tracked, usage_summary

U = CallUsage(mode="cli", model="m", input_tokens=100, output_tokens=10, cost_usd=0.5, duration_ms=1000)
NOW = dt.datetime(2026, 11, 15, 12, 0, tzinfo=dt.timezone.utc)


def _row(repo, when, kind="generation", status="ok", cost=0.5):
    repo.add(LlmUsage(created_at=when, kind=kind, mode="cli", model="m", attempts=1, input_tokens=100,
                      output_tokens=10, cost_usd=cost, duration_ms=1000, status=status))


def test_tracked_writes_ok_row(repo):
    with tracked(repo, "generation") as m:
        m.add(U)
    [row] = repo.llm_usages()
    assert (row.kind, row.status, row.attempts, row.cost_usd, row.mode, row.model) == (
        "generation", "ok", 1, 0.5, "cli", "m")
    assert (row.input_tokens, row.output_tokens, row.duration_ms) == (100, 10, 1000)


def test_tracked_writes_failed_row_and_reraises(repo):
    with pytest.raises(LLMInvalidResponse):
        with tracked(repo, "generation") as m:
            m.add(U)
            m.add(U)
            raise LLMInvalidResponse(["x"])
    [row] = repo.llm_usages()
    assert (row.status, row.attempts, row.cost_usd) == ("failed", 2, 1.0)


def test_tracked_no_row_without_attempt(repo):
    with pytest.raises(LLMUnavailable):
        with tracked(repo, "generation"):
            raise LLMUnavailable("CLI claude introuvable")
    assert repo.llm_usages() == []


def test_summary_month_and_average(repo):
    this_month = NOW - dt.timedelta(days=2)
    _row(repo, this_month, cost=0.40)
    _row(repo, this_month, cost=0.60)
    _row(repo, this_month, status="failed", cost=0.20)
    _row(repo, this_month, kind="adjustment", cost=0.10)
    _row(repo, NOW - dt.timedelta(days=30), cost=1.00)
    _row(repo, this_month, cost=None)
    s = usage_summary(repo, NOW)
    assert s["month"]["generations"] == 4 and s["month"]["adjustments"] == 1
    assert s["month"]["cost_eur"] == pytest.approx(1.30 * 0.92)
    assert s["avg_generation_eur"] == pytest.approx((0.40 + 0.60 + 1.00) / 3 * 0.92, abs=1e-4)
    assert len(s["recent"]) == 6
    first = s["recent"][0]
    assert first["created_at"].endswith("+00:00")
    assert set(first) == {"created_at", "kind", "status", "attempts", "cost_eur", "input_tokens",
                          "output_tokens", "duration_ms", "mode", "model"}


def test_summary_recent_newest_first_and_ten_max(repo):
    for i in range(12):
        _row(repo, NOW - dt.timedelta(hours=i), cost=float(i))
    recent = usage_summary(repo, NOW)["recent"]
    assert len(recent) == 10 and recent[0]["cost_eur"] == 0.0 and recent[1]["cost_eur"] == pytest.approx(0.92)


def test_summary_empty(repo):
    assert usage_summary(repo, NOW) == {
        "month": {"generations": 0, "adjustments": 0, "cost_eur": 0.0},
        "avg_generation_eur": None,
        "recent": [],
    }
