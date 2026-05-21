import numpy as np
import pandas as pd
import pytest

pymc = pytest.importorskip("pymc")

from body_sim import bayesian, bayesian_predict
from body_sim.config import DEFAULT_PROFILE
from tests.body_sim.test_bayesian import _synthetic_data


def test_posterior_predictive_band_shapes():
    df, _ = _synthetic_data(seed=0, n_days=10)
    idata = bayesian.fit(df, profile=DEFAULT_PROFILE, draws=100, tune=100, seed=0)
    band = bayesian_predict.posterior_predictive_band(idata, df, profile=DEFAULT_PROFILE)
    assert set(band.keys()) == {"lo", "median", "hi"}
    assert all(arr.shape == (10,) for arr in band.values())
    # Lower bound must be below median which is below upper bound
    assert np.all(band["lo"] <= band["median"])
    assert np.all(band["median"] <= band["hi"])


@pytest.mark.slow
def test_posterior_predictive_band_calibrates():
    """On synthetic data where the model is correctly specified, the 95%
    posterior predictive band must contain ~90%+ of held-out observations."""
    df, _ = _synthetic_data(seed=0, n_days=30)
    holdout = np.arange(len(df)) % 3 == 0
    fit_df = df.copy()
    fit_df.loc[df.index[holdout], "weight_kg"] = np.nan
    idata = bayesian.fit(fit_df, profile=DEFAULT_PROFILE, draws=500, tune=500, seed=0)

    band = bayesian_predict.posterior_predictive_band(
        idata, fit_df, profile=DEFAULT_PROFILE
    )
    holdout_obs = df["weight_kg"].values[holdout]
    holdout_lo = band["lo"][holdout]
    holdout_hi = band["hi"][holdout]
    inside = (holdout_obs >= holdout_lo) & (holdout_obs <= holdout_hi)
    coverage = float(inside.mean())
    assert coverage >= 0.80, (
        f"posterior-predictive coverage on held-out obs = {coverage:.2f}; "
        "model is under-dispersed"
    )
