import pytest

from coach.analysis.zones import compute_zones


def test_pace_zones_from_threshold():
    z = compute_zones(threshold_pace_s_km=240, pred_10k_s=None, garmin_hr_zones=[100, 120, 140, 160, 175], hr_max=190, hr_rest=50)
    assert z.pace["seuil"] == (235, 247)
    assert z.pace["EF"] == (288, 317)
    assert z.hr["Z2"] == (120, 140) and z.hr["Z5"] == (175, 190)
    assert z.source == ["lactate_threshold", "garmin_hr_zones"]


def test_fallback_threshold_from_10k_prediction():
    z = compute_zones(threshold_pace_s_km=None, pred_10k_s=2400, garmin_hr_zones=None, hr_max=190, hr_rest=50)
    assert z.pace["seuil"] == (245, 258)  # T = 250, round(257.5) = 258
    assert z.hr["Z2"] == (134, 148)  # Karvonen
    assert z.source == ["race_prediction_10k", "karvonen"]


def test_no_pace_data_gives_none():
    z = compute_zones(threshold_pace_s_km=None, pred_10k_s=None, garmin_hr_zones=None, hr_max=190, hr_rest=50)
    assert z.pace is None


def test_missing_hr_max_raises():
    with pytest.raises(ValueError, match="FC max inconnue"):
        compute_zones(threshold_pace_s_km=240, pred_10k_s=None, garmin_hr_zones=None, hr_max=None, hr_rest=50)


def test_garmin_zones_without_hr_max_raises():
    with pytest.raises(ValueError, match="FC max inconnue"):
        compute_zones(threshold_pace_s_km=240, pred_10k_s=None, garmin_hr_zones=[100, 120, 140, 160, 175], hr_max=None, hr_rest=50)
