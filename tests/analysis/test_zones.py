import pytest

from coach.analysis.zones import compute_zones


def test_pace_zones_from_threshold():
    z = compute_zones(threshold_pace_s_km=240, pred_10k_s=None, hr_max=190, hr_rest=50)
    assert z.pace["seuil"] == (235, 247)
    assert z.pace["EF"] == (288, 317)


def test_hr_zones_are_karvonen():
    z = compute_zones(threshold_pace_s_km=240, pred_10k_s=None, hr_max=190, hr_rest=50)
    assert z.hr == {"Z1": (120, 134), "Z2": (134, 148), "Z3": (148, 162), "Z4": (162, 176), "Z5": (176, 190)}
    assert z.source == ["lactate_threshold", "karvonen"]


def test_realistic_running_z1():
    # cas réel : FC max 182, repos 49 → Z1 plus à 91–109
    z = compute_zones(threshold_pace_s_km=None, pred_10k_s=None, hr_max=182, hr_rest=49)
    assert z.hr["Z1"] == (116, 129) and z.hr["Z2"] == (129, 142)


def test_fallback_threshold_from_10k_prediction():
    z = compute_zones(threshold_pace_s_km=None, pred_10k_s=2400, hr_max=190, hr_rest=50)
    assert z.pace["seuil"] == (245, 258)  # T = 250, round(257.5) = 258
    assert z.hr["Z2"] == (134, 148)  # Karvonen
    assert z.source == ["race_prediction_10k", "karvonen"]


def test_no_pace_data_gives_none():
    z = compute_zones(threshold_pace_s_km=None, pred_10k_s=None, hr_max=190, hr_rest=50)
    assert z.pace is None


def test_missing_hr_max_raises():
    with pytest.raises(ValueError, match="FC max inconnue"):
        compute_zones(threshold_pace_s_km=240, pred_10k_s=None, hr_max=None, hr_rest=50)


def test_missing_hr_rest_raises():
    with pytest.raises(ValueError, match="FC repos inconnue"):
        compute_zones(threshold_pace_s_km=240, pred_10k_s=None, hr_max=190, hr_rest=None)
