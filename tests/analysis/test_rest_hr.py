from datetime import date, timedelta

from coach.analysis.rest_hr import NightRecord, RestHr, choose_rest_hr, nights_average

T = date(2026, 11, 23)


def n(days_ago, hr, slept=True):
    return NightRecord(day=T - timedelta(days=days_ago), hr_rest=hr, slept=slept)


def test_average_of_worn_nights_only():
    assert nights_average([n(0, 46), n(1, 48), n(2, 47), n(3, 60, slept=False)], T) == (47, 3)


def test_below_min_nights():
    assert nights_average([n(0, 46), n(1, 48)], T) is None


def test_window_is_14_days():
    assert nights_average([n(0, 46), n(1, 48), n(14, 40)], T) is None  # J-14 hors fenêtre
    assert nights_average([n(0, 46), n(1, 48), n(13, 40)], T) == (45, 3)


def test_night_without_hr_ignored():
    assert nights_average([n(0, 46), n(1, None), n(2, 48)], T) is None


def test_priority():
    assert choose_rest_hr(manual=44, nights=(47, 9), last_nights_value=48, garmin_value=55) == RestHr(value=44, source="manual")
    assert choose_rest_hr(manual=None, nights=(47, 9), last_nights_value=48, garmin_value=55) == RestHr(value=47, source="nights", nights=9)
    assert choose_rest_hr(manual=None, nights=None, last_nights_value=48, garmin_value=55) == RestHr(value=48, source="last_good")
    assert choose_rest_hr(manual=None, nights=None, last_nights_value=None, garmin_value=55) == RestHr(value=55, source="garmin")
    assert choose_rest_hr(manual=None, nights=None, last_nights_value=None, garmin_value=None) == RestHr(value=None, source="garmin")
