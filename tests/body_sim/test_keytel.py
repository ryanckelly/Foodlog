import numpy as np
import pytest

from body_sim import keytel


def test_keytel_per_minute_male_known_value():
    # HR=120, weight=80kg, age=40, male
    # raw = -55.0969 + 0.6309*120 + 0.1988*80 + 0.2017*40
    #     = -55.0969 + 75.708 + 15.904 + 8.068 = 44.5831
    # kcal/min = 44.5831 / 4.184 ≈ 10.66
    result = keytel.kcal_per_min(hr=120, weight_kg=80, age=40, sex="male")
    assert result == pytest.approx(10.66, abs=0.05)


def test_keytel_per_minute_female_known_value():
    # HR=120, weight=70kg, age=40, female
    # raw = -20.4022 + 0.4472*120 - 0.1263*70 + 0.074*40
    #     = -20.4022 + 53.664 - 8.841 + 2.96 = 27.3808
    # kcal/min = 27.3808 / 4.184 ≈ 6.54
    result = keytel.kcal_per_min(hr=120, weight_kg=70, age=40, sex="female")
    assert result == pytest.approx(6.54, abs=0.05)


def test_keytel_per_minute_clips_negative():
    # At very low HR the formula goes negative; should clip to 0
    result = keytel.kcal_per_min(hr=40, weight_kg=80, age=40, sex="male")
    assert result >= 0


def test_keytel_per_minute_rejects_invalid_sex():
    with pytest.raises(ValueError):
        keytel.kcal_per_min(hr=120, weight_kg=80, age=40, sex="other")


def test_keytel_daily_integral_constant_hr():
    # 1440 minutes at HR=120 should produce 1440 * per-minute value
    hrs = np.full(1440, 120, dtype=float)
    total = keytel.daily_integral(hrs, weight_kg=80, age=40, sex="male")
    expected = 1440 * keytel.kcal_per_min(120, 80, 40, "male")
    assert total == pytest.approx(expected, abs=1.0)


def test_keytel_daily_integral_handles_nan():
    # Partial-coverage day: some minutes have NaN HR
    hrs = np.full(1440, 120, dtype=float)
    hrs[:720] = np.nan  # first half missing
    total = keytel.daily_integral(hrs, weight_kg=80, age=40, sex="male")
    # Should integrate only over the 720 non-NaN minutes
    expected = 720 * keytel.kcal_per_min(120, 80, 40, "male")
    assert total == pytest.approx(expected, abs=1.0)


def test_keytel_coverage_pct():
    hrs = np.full(1440, 120, dtype=float)
    hrs[:720] = np.nan
    assert keytel.coverage_pct(hrs) == pytest.approx(50.0, abs=0.1)
