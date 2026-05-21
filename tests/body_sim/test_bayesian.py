"""Parameter-recovery + smoke tests for the Phase-2 PyMC model.

Generates synthetic weigh-in data from known sigma_glycogen / sigma_obs
values, fits the model, and checks the posterior recovers those values
within HDI tolerance.

Skipped if pymc is not installed (Phase 1 / pre-foodlog-adu environments).
"""

import numpy as np
import pandas as pd
import pytest

pymc = pytest.importorskip("pymc")
import arviz as az

from body_sim import bayesian
from body_sim.config import DEFAULT_PROFILE


def _synthetic_data(seed: int = 0, n_days: int = 30):
    """n maintenance-ish days with known generative parameters.

    Returns ``(df, truth)`` where ``df`` is a daily-rollup-shaped DataFrame
    and ``truth`` holds the ground-truth latent + obs SDs the model should
    recover.
    """
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-05-01", periods=n_days, freq="D")
    intake = rng.normal(2400, 80, n_days)
    carbs = rng.normal(280, 30, n_days)
    sodium = rng.normal(2300, 200, n_days)

    true_sigma_glycogen = 0.35
    true_sigma_obs = 0.30

    # Synthesize observations: hall baseline + cumulative latent + iid noise
    glycogen_innovations = rng.normal(0, true_sigma_glycogen, n_days).cumsum()
    baseline_weight = 80.0
    obs_noise = rng.normal(0, true_sigma_obs, n_days)
    weights = baseline_weight + glycogen_innovations + obs_noise

    df = pd.DataFrame({
        "intake_kcal": intake,
        "protein_g": 120.0,
        "carb_g": carbs,
        "fat_g": 75.0,
        "sodium_mg": sodium,
        "ee_hr_keytel_kcal": 600.0,
        "workout_kcal": 0.0,
        "vigorous_min": 0,
        "intake_logged": True,
        "hr_coverage_pct": 100.0,
        "steps": 8000,
        "weight_kg": weights,
        "bf_pct": np.nan,
        "reference_weight_kg": baseline_weight,
        "weigh_in_protocol_controlled": True,
    }, index=idx)
    truth = {
        "sigma_glycogen": true_sigma_glycogen,
        "sigma_obs_controlled": true_sigma_obs,
    }
    return df, truth


def test_build_model_returns_pymc_model():
    df, _ = _synthetic_data(n_days=5)
    m = bayesian.build_model(df, profile=DEFAULT_PROFILE)
    assert isinstance(m, pymc.Model)
    rv_names = {rv.name for rv in m.free_RVs}
    expected = {"sigma_glycogen", "sigma_obs_controlled", "sigma_obs_uncontrolled", "g"}
    assert expected.issubset(rv_names), (
        f"missing free RVs: expected {expected}, got {rv_names}"
    )


def test_build_model_handles_no_observations():
    """If df has no observed weigh-ins, model still builds (prior-only fit)."""
    df, _ = _synthetic_data(n_days=5)
    df["weight_kg"] = np.nan
    m = bayesian.build_model(df, profile=DEFAULT_PROFILE)
    rv_names = {rv.name for rv in m.free_RVs}
    assert "g" in rv_names
    # No weight_obs likelihood when no observations
    obs_rvs = [rv.name for rv in m.observed_RVs]
    assert "weight_obs" not in obs_rvs


def _hdi_bounds(idata, var_name: str, prob: float = 0.94) -> tuple[float, float]:
    """Pluck the lower/upper HDI bounds for a scalar variable.

    ArviZ 1.x emits an HDI Dataset with a ``ci_bound`` dimension instead of
    the older ``hdi`` dimension. Values come back as length-2 arrays
    ``[lo, hi]``.
    """
    hdi = az.hdi(idata, prob=prob)
    arr = np.asarray(hdi[var_name].values).ravel()
    assert arr.size == 2, f"unexpected HDI shape for {var_name}: {arr}"
    return float(arr[0]), float(arr[1])


@pytest.mark.slow
def test_parameter_recovery_sigma_obs():
    """Posterior 94% HDI for sigma_obs_controlled must contain the true value."""
    df, truth = _synthetic_data(seed=0, n_days=30)
    idata = bayesian.fit(df, profile=DEFAULT_PROFILE, draws=500, tune=500, seed=0)
    lo, hi = _hdi_bounds(idata, "sigma_obs_controlled")
    assert lo <= truth["sigma_obs_controlled"] <= hi, (
        f"sigma_obs_controlled HDI [{lo:.3f}, {hi:.3f}] does not contain "
        f"true {truth['sigma_obs_controlled']:.3f}"
    )


@pytest.mark.slow
def test_parameter_recovery_sigma_glycogen():
    """Posterior 94% HDI for sigma_glycogen must contain the true value."""
    df, truth = _synthetic_data(seed=0, n_days=30)
    idata = bayesian.fit(df, profile=DEFAULT_PROFILE, draws=500, tune=500, seed=0)
    lo, hi = _hdi_bounds(idata, "sigma_glycogen")
    assert lo <= truth["sigma_glycogen"] <= hi, (
        f"sigma_glycogen HDI [{lo:.3f}, {hi:.3f}] does not contain "
        f"true {truth['sigma_glycogen']:.3f}"
    )
