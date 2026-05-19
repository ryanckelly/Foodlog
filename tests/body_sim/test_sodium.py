import pytest

from body_sim import sodium


def test_sodium_water_at_baseline_is_zero():
    # At 2300mg/day (baseline), no extra retention
    assert sodium.water_kg(sodium_mg=2300) == 0.0


def test_sodium_water_below_baseline_is_zero():
    # Below baseline doesn't produce negative water
    assert sodium.water_kg(sodium_mg=1500) == 0.0


def test_sodium_water_high_intake():
    # 5300mg = 3000 above baseline; ~0.3 kg extra water
    result = sodium.water_kg(sodium_mg=5300)
    assert 0.1 < result < 1.0


def test_sodium_water_monotonic():
    # More sodium → more water
    a = sodium.water_kg(sodium_mg=3000)
    b = sodium.water_kg(sodium_mg=5000)
    assert b > a
