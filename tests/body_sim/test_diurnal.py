import pytest

from body_sim import diurnal


def test_food_in_transit_kg_zero_intake_returns_zero():
    assert diurnal.food_in_transit_kg(0.0) == 0.0


def test_food_in_transit_kg_scales_with_intake_mass():
    """~50% of today's intake remains in transit by evening; 2000 kcal ~666g food
    at 3 kcal/g -> ~0.333 kg in transit."""
    val = diurnal.food_in_transit_kg(2000.0)
    assert 0.25 < val < 0.45


def test_sweat_kg_zero_activity_returns_zero():
    assert diurnal.sweat_kg(workout_min=0, vigorous_min=0) == 0.0


def test_sweat_kg_scales_with_vigorous_min():
    """Vigorous minutes dominate sweat loss; default 0.5 kg/hour vigorous,
    wash-out factor 0.7 applied -> 60 min ~0.35 kg."""
    val = diurnal.sweat_kg(workout_min=0, vigorous_min=60)
    assert 0.2 < val < 0.6


def test_sodium_pm_water_kg_clipped_at_zero():
    assert diurnal.sodium_pm_water_kg(1000.0) == 0.0


def test_predicted_diurnal_delta_kg_typical_day():
    """A 2400-kcal, moderate-sodium, 30-min cardio day produces a positive
    AM->PM delta of ~0.3-1.2 kg."""
    delta = diurnal.predicted_diurnal_delta_kg(
        intake_kcal=2400, sodium_mg=2800, workout_min=30, vigorous_min=10,
    )
    assert 0.3 < delta < 1.2
