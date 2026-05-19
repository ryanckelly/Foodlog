import pytest

from body_sim import glycogen


def test_initial_glycogen_default():
    assert glycogen.INITIAL_GLYCOGEN_G == pytest.approx(400.0, abs=50.0)


def test_water_from_glycogen():
    # 400g glycogen → 1.4 kg water
    assert glycogen.water_kg_from_glycogen(400) == pytest.approx(1.4, abs=0.01)


def test_water_from_zero_glycogen():
    assert glycogen.water_kg_from_glycogen(0) == 0.0


def test_glycogen_update_high_carb_increases():
    # High carb intake, low starting glycogen → glycogen rises
    new = glycogen.update(current_glycogen_g=200, carb_g=400)
    assert new > 200


def test_glycogen_update_low_carb_decreases():
    # Low carb intake, high starting glycogen → glycogen falls
    new = glycogen.update(current_glycogen_g=500, carb_g=50)
    assert new < 500


def test_glycogen_capped_at_max():
    # Massive carb intake doesn't push glycogen past physiological cap
    new = glycogen.update(current_glycogen_g=450, carb_g=2000)
    assert new <= glycogen.MAX_GLYCOGEN_G


def test_glycogen_floored_at_zero():
    # Extended fast can't drive glycogen negative
    new = glycogen.update(current_glycogen_g=10, carb_g=0)
    assert new >= 0


def test_glycogen_steady_state():
    # At alpha*carb = beta*glycogen, glycogen is at equilibrium
    # equilibrium_glycogen = alpha * carb / beta = 0.3 * 200 / 0.4 = 150
    new = glycogen.update(current_glycogen_g=150, carb_g=200)
    assert new == pytest.approx(150, abs=1.0)
