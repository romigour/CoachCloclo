from datetime import date

from coach.garmin.port import ActivitySummary
from coach.plan.repo import Repo
from coach.services.activities import store_summaries


def _summaries():
    return [
        ActivitySummary(
            garmin_id=i,
            date=date(2026, 1, i),
            type_key="running",
            duration_s=3000,
            distance_m=10000,
            raw={"id": i},
        )
        for i in (1, 2)
    ]


def test_store_summaries_skips_existing(repo):
    assert store_summaries(repo, _summaries()) == 2
    assert store_summaries(repo, _summaries()) == 0
    assert len(repo.all_activities()) == 2
    assert repo.all_activities()[0].avg_pace_s_km == 300


def test_store_summaries_survives_concurrent_insert(repo, monkeypatch):
    store_summaries(repo, _summaries()[:1])
    monkeypatch.setattr(Repo, "activity_by_garmin_id", lambda self, gid: None)
    assert store_summaries(repo, _summaries()[:1]) == 0
    assert len(repo.all_activities()) == 1
