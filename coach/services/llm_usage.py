"""Suivi de la consommation Claude : enregistrement par action et résumé pour les Paramètres."""

import datetime as dt
from collections.abc import Iterator
from contextlib import contextmanager

from coach.llm.usage import UsageMeter, to_eur
from coach.plan.models import LlmUsage
from coach.plan.repo import Repo

RECENT_COUNT = 10


@contextmanager
def tracked(repo: Repo, kind: str) -> Iterator[UsageMeter]:
    """Enregistre une ligne `LlmUsage` à la sortie, si au moins un appel a abouti.

    Statut `ok` en sortie normale, `failed` si une exception remonte (elle est relancée telle quelle).
    """
    meter = UsageMeter()
    status = "failed"
    try:
        yield meter
        status = "ok"
    finally:
        if meter.attempts:
            repo.add(LlmUsage(kind=kind, mode=meter.mode, model=meter.model, attempts=meter.attempts,
                              input_tokens=meter.input_tokens, output_tokens=meter.output_tokens,
                              cost_usd=meter.cost_usd, duration_ms=meter.duration_ms, status=status))


def _utc(value: dt.datetime) -> dt.datetime:
    """SQLite relit les dates sans fuseau : elles sont en UTC."""
    return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)


def _row(u: LlmUsage) -> dict:
    return {
        "created_at": _utc(u.created_at).isoformat(),
        "kind": u.kind,
        "status": u.status,
        "attempts": u.attempts,
        "cost_eur": to_eur(u.cost_usd),
        "input_tokens": u.input_tokens,
        "output_tokens": u.output_tokens,
        "duration_ms": u.duration_ms,
        "mode": u.mode,
        "model": u.model,
    }


def usage_summary(repo: Repo, now: dt.datetime) -> dict:
    """Total du mois (calendaire, heure locale), coût moyen d'une génération réussie, dernières actions."""
    rows = repo.llm_usages()
    local_now = now.astimezone()
    month_start = local_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month = [u for u in rows if _utc(u.created_at) >= month_start]
    ok_costs = [u.cost_usd for u in rows if u.kind == "generation" and u.status == "ok" and u.cost_usd is not None]
    return {
        "month": {
            "generations": sum(u.kind == "generation" for u in month),
            "adjustments": sum(u.kind == "adjustment" for u in month),
            "cost_eur": to_eur(sum(u.cost_usd for u in month if u.cost_usd is not None)),
        },
        "avg_generation_eur": to_eur(sum(ok_costs) / len(ok_costs)) if ok_costs else None,
        "recent": [_row(u) for u in rows[:RECENT_COUNT]],
    }
