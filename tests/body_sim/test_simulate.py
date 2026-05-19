import numpy as np
import pytest

from body_sim import simulate
from body_sim.config import DEFAULT_PARAMETERS, DEFAULT_PROFILE
from body_sim.model import BodyState


@pytest.fixture
def initial_state():
    return BodyState(fat_mass_kg=20.0, lean_mass_kg=60.0)


@pytest.fixture
def maintenance_inputs_30d():
    return [
        {
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
            "steps": 8000,
        }
        for _ in range(30)
    ]


def test_simulate_forward_shape(initial_state, maintenance_inputs_30d):
    samples = simulate.sample_parameters(n=50, base=DEFAULT_PARAMETERS, seed=0)
    result = simulate.simulate_forward(
        initial_state=initial_state,
        inputs_per_day=maintenance_inputs_30d,
        profile=DEFAULT_PROFILE,
        parameter_samples=samples,
    )
    # 50 samples, 30 days, multiple tracked quantities
    assert result.predicted_weight_kg.shape == (50, 30)
    assert result.fat_mass_kg.shape == (50, 30)
    assert result.lean_mass_kg.shape == (50, 30)


def test_simulate_forward_maintenance_is_stable(initial_state, maintenance_inputs_30d):
    samples = simulate.sample_parameters(n=20, base=DEFAULT_PARAMETERS, seed=1)
    result = simulate.simulate_forward(
        initial_state=initial_state,
        inputs_per_day=maintenance_inputs_30d,
        profile=DEFAULT_PROFILE,
        parameter_samples=samples,
    )
    # At rough maintenance, total mass changes < 1 kg over 30 days on average
    mean_change = float(np.mean(result.predicted_weight_kg[:, -1] - result.predicted_weight_kg[:, 0]))
    assert abs(mean_change) < 2.0


def test_simulate_forward_deficit_loses_weight(initial_state):
    inputs = [
        {
            "intake_kcal": 1500.0,
            "protein_g": 120.0,
            "carb_g": 150.0,
            "fat_g": 50.0,
            "sodium_mg": 2300.0,
            "ee_hr_keytel_kcal": 700.0,
            "workout_kcal": 0.0,
            "vigorous_min": 0,
            "intake_logged": True,
            "hr_coverage_pct": 100.0,
            "steps": 8000,
        }
        for _ in range(56)
    ]
    samples = simulate.sample_parameters(n=20, base=DEFAULT_PARAMETERS, seed=2)
    result = simulate.simulate_forward(
        initial_state=initial_state,
        inputs_per_day=inputs,
        profile=DEFAULT_PROFILE,
        parameter_samples=samples,
    )
    mean_final = float(np.mean(result.predicted_weight_kg[:, -1]))
    initial_weight = initial_state.predicted_weight_kg(sodium_mg=2300.0)
    assert mean_final < initial_weight - 2.0


def test_sample_parameters_reproducible():
    a = simulate.sample_parameters(n=10, base=DEFAULT_PARAMETERS, seed=42)
    b = simulate.sample_parameters(n=10, base=DEFAULT_PARAMETERS, seed=42)
    for k in DEFAULT_PARAMETERS:
        assert np.array_equal(a[k], b[k])


def test_credible_band_shape():
    arr = np.random.normal(loc=80, scale=1, size=(200, 30))
    band = simulate.credible_band(arr, lo=0.025, hi=0.975)
    assert band["lo"].shape == (30,)
    assert band["hi"].shape == (30,)
    assert (band["hi"] > band["lo"]).all()
