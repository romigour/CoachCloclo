from datetime import date

from coach.analysis.long_history import kept_records, monthly_volume, past_races
from coach.plan.models import PersonalRecord, Race
from tests.plan.factories import make_activity

TODAY = date(2026, 11, 22)


def test_monthly_volume_twelve_months_most_recent_first():
    m = monthly_volume([], TODAY)
    assert [x.month for x in m][:2] == [date(2026, 11, 1), date(2026, 10, 1)]
    assert len(m) == 12 and m[-1].month == date(2025, 12, 1)
    assert all(x.runs == 0 and x.other_s == 0 for x in m)


def test_monthly_volume_sums_running_and_other_sports():
    acts = [
        make_activity(garmin_activity_id=1, date=date(2026, 11, 3), type_key="running",
                      duration_s=3600, distance_m=10000, d_plus_m=100),
        make_activity(garmin_activity_id=2, date=date(2026, 11, 9), type_key="trail_running",
                      duration_s=7200, distance_m=20000, d_plus_m=900),
        make_activity(garmin_activity_id=3, date=date(2026, 11, 10), type_key="cycling",
                      duration_s=5400, distance_m=40000),
    ]
    nov = monthly_volume(acts, TODAY)[0]
    assert (nov.runs, nov.run_km, nov.run_s, nov.d_plus_m, nov.longest_km, nov.other_s) == (
        2, 30.0, 10800, 1000, 20.0, 5400,
    )


def test_monthly_volume_missing_values_count_as_zero():
    nov = monthly_volume([make_activity(date=date(2026, 11, 3), distance_m=None, duration_s=None)], TODAY)[0]
    assert (nov.runs, nov.run_km, nov.run_s) == (1, 0.0, 0)


def test_monthly_volume_ignores_out_of_window():
    acts = [
        make_activity(garmin_activity_id=1, date=date(2025, 11, 30)),
        make_activity(garmin_activity_id=2, date=date(2026, 11, 23)),
    ]
    assert all(x.runs == 0 for x in monthly_volume(acts, TODAY))


def test_monthly_volume_crosses_year():
    m = monthly_volume([], date(2027, 1, 15))
    assert m[0].month == date(2027, 1, 1)
    assert m[1].month == date(2026, 12, 1)
    assert m[-1].month == date(2026, 2, 1)


def test_past_races_order_limit_and_fallbacks():
    acts = {
        i: make_activity(id=i, garmin_activity_id=i, date=date(2025, 1, 1 + i), duration_s=3000 + i)
        for i in range(1, 21)
    }
    acts[3] = make_activity(id=3, garmin_activity_id=3, date=date(2025, 1, 4), distance_m=None)
    acts[30] = make_activity(id=30, garmin_activity_id=30, date=date(2026, 6, 1))  # exclue
    races = [Race(activity_id=i, name=f"Course {i}") for i in range(1, 21)]
    races[19] = Race(activity_id=20, name="Course 20", official_time_s=2900, overall_rank=5, overall_total=80)
    races += [Race(activity_id=30, excluded=True), Race(activity_id=99, name="Sans activité")]

    out = past_races(races, acts)

    assert len(out) == 15
    assert [r.date for r in out] == sorted((r.date for r in out), reverse=True)
    assert out[0].name == "Course 20" and out[0].time_s == 2900
    assert (out[0].overall_rank, out[0].overall_total) == (5, 80)
    assert out[1].time_s == 3019  # durée de l'activité, faute de temps officiel
    assert all(r.name not in ("Sans activité", None) for r in out)
    assert all(r.date != date(2026, 6, 1) for r in out)
    assert past_races(races, acts, limit=30)[-3].distance_km is None  # course 3, sans distance


def test_kept_records_order_and_filter():
    recs = [
        PersonalRecord(kind=k, value=v)
        for k, v in [("longest_run", 32400), ("1k", 200), ("10k", 2535), ("5k", 0), ("marathon", 11000)]
    ]
    assert [r.kind for r in kept_records(recs)] == ["10k", "marathon", "longest_run"]
