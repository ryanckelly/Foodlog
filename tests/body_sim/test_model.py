import pytest

from body_sim import model
from body_sim.config import DEFAULT_PARAMETERS, DEFAULT_PROFILE


@pytest.fixture
def initial_state():
    return model.BodyState(
        fat_mass_kg=20.0,
        lean_mass_kg=60.0,
        glycogen_g=400.0,
    )


@pytest.fixture
def maintenance_inputs():
    # Roughly maintenance for an 80kg, 40yr male:
    # RMR ~ 1700, activity ~ 600, TEF ~ 200 → ~2500 kcal
    return {
        "intake_kcal": 2500.0,
        "protein_g": 120.0,
        "carb_g": 300.0,
        "fat_g": 75.0,
        "sodium_mg": 2300.0,
        "ee_hr_keytel_kcal": 600.0,
        "workout_kcal": 0.0,
        "vigorous_min": 0,
        "intake_logged": True,
        "hr_coverage_pct": 100.0,
    }


def test_state_predicted_weight_includes_water(initial_state):
    predicted = initial_state.predicted_weight_kg(sodium_mg=2300.0)
    # fat + lean + glycogen-water + sodium-water (at baseline = 0)
    assert predicted == pytest.approx(20 + 60 + 1.4, abs=0.05)


def test_one_day_step_returns_new_state(initial_state, maintenance_inputs):
    new_state, diagnostics = model.step(
        state=initial_state,
        inputs=maintenance_inputs,
        profile=DEFAULT_PROFILE,
        parameters=DEFAULT_PARAMETERS,
    )
    assert isinstance(new_state, model.BodyState)
    assert "expenditure_kcal" in diagnostics
    assert "tef_kcal" in diagnostics
    assert "delta_e_kcal" in diagnostics
    assert "partition_p" in diagnostics


def test_surplus_increases_total_mass(initial_state):
    # Big surplus: fat + lean should grow
    inputs = {
        "intake_kcal": 4000.0,
        "protein_g": 150.0,
        "carb_g": 500.0,
        "fat_g": 100.0,
        "sodium_mg": 2300.0,
        "ee_hr_keytel_kcal": 500.0,
        "workout_kcal": 0.0,
        "vigorous_min": 0,
        "intake_logged": True,
        "hr_coverage_pct": 100.0,
    }
    new_state, _ = model.step(
        state=initial_state, inputs=inputs, profile=DEFAULT_PROFILE, parameters=DEFAULT_PARAMETERS
    )
    initial_mass = initial_state.fat_mass_kg + initial_state.lean_mass_kg
    new_mass = new_state.fat_mass_kg + new_state.lean_mass_kg
    assert new_mass > initial_mass


def test_deficit_decreases_total_mass(initial_state):
    inputs = {
        "intake_kcal": 1500.0,
        "protein_g": 100.0,
        "carb_g": 150.0,
        "fat_g": 50.0,
        "sodium_mg": 2300.0,
        "ee_hr_keytel_kcal": 700.0,
        "workout_kcal": 0.0,
        "vigorous_min": 0,
        "intake_logged": True,
        "hr_coverage_pct": 100.0,
    }
    new_state, _ = model.step(
        state=initial_state, inputs=inputs, profile=DEFAULT_PROFILE, parameters=DEFAULT_PARAMETERS
    )
    initial_mass = initial_state.fat_mass_kg + initial_state.lean_mass_kg
    new_mass = new_state.fat_mass_kg + new_state.lean_mass_kg
    assert new_mass < initial_mass


def test_intake_bias_applied(initial_state, maintenance_inputs):
    # intake_bias < 1 means we trust the log less (assume actually ate more)
    params = {**DEFAULT_PARAMETERS, "intake_bias": 0.7}
    new_state, diag = model.step(
        state=initial_state, inputs=maintenance_inputs, profile=DEFAULT_PROFILE, parameters=params
    )
    # intake_bias=0.7 with intake=2500 effectively means model assumes true intake is 2500/0.7 = ~3571
    # That's a surplus; mass should grow
    assert diag["effective_intake_kcal"] == pytest.approx(2500.0 / 0.7, abs=1.0)


def test_activity_fallback_when_hr_coverage_low(initial_state):
    # Low HR coverage → don't use Keytel; use workout_kcal + steps-derived estimate
    inputs = {
        "intake_kcal": 2500.0,
        "protein_g": 120.0,
        "carb_g": 300.0,
        "fat_g": 75.0,
        "sodium_mg": 2300.0,
        "ee_hr_keytel_kcal": 0.0,            # no HR data
        "workout_kcal": 200.0,
        "vigorous_min": 30,
        "intake_logged": True,
        "hr_coverage_pct": 10.0,             # below threshold
        "steps": 8000,                       # fallback signal
    }
    new_state, diag = model.step(
        state=initial_state, inputs=inputs, profile=DEFAULT_PROFILE, parameters=DEFAULT_PARAMETERS
    )
    assert diag["activity_source"] == "fallback"
    assert diag["activity_kcal"] > 0
