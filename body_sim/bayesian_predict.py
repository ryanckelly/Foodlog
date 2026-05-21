"""Posterior-predictive band that includes Hall trajectory + glycogen latent + obs noise.

Consumes the ``arviz.InferenceData`` from ``bayesian.fit``. For each posterior
draw, takes the deterministic Hall trajectory and adds that draw's latent
``g`` plus a sample from the per-protocol observation noise. Quantiles
across draws form the 95% predictive band.

This is the posterior-track companion to the prior-track band emitted by
``validation.forward_walk`` in its default ``mode="prior"`` path.
"""

import numpy as np
import pandas as pd

from body_sim import bayesian
from body_sim.config import UserProfile


def posterior_predictive_band(
    idata, df: pd.DataFrame, profile: UserProfile,
    lo: float = 0.025, hi: float = 0.975,
    include_obs_noise: bool = True,
    seed: int | None = 0,
) -> dict[str, np.ndarray]:
    """Per-day quantile band across the posterior draws.

    Args:
        idata: arviz.InferenceData from bayesian.fit.
        df: same daily-rollup the fit was conditioned on.
        profile: user profile.
        include_obs_noise: if True, add a per-protocol obs-noise draw to each
            per-day predictive sample before quantiling — this is the band you
            compare against an actual weigh-in. If False, return the band on
            the latent-state mean (hall + g), which is what you'd compare
            against a noise-free "true mass" if such a thing existed.
        seed: RNG for the obs-noise sampling.

    Returns:
        Dict with keys ``'lo'``, ``'median'``, ``'hi'``, each shape (n_days,).
    """
    posterior = idata.posterior
    g_draws = posterior.g.values.reshape(-1, posterior.g.shape[-1])
    sigma_c = posterior.sigma_obs_controlled.values.flatten()
    sigma_u = posterior.sigma_obs_uncontrolled.values.flatten()
    n_draws = g_draws.shape[0]
    n_days = len(df)

    hall_path = bayesian._hall_trajectory(df, profile)
    hall_path = pd.Series(hall_path).ffill().bfill().fillna(80.0).values

    # Per-day protocol mask
    if "weigh_in_protocol_controlled" in df.columns:
        is_controlled = df["weigh_in_protocol_controlled"].astype(bool).values
    else:
        is_controlled = np.zeros(n_days, dtype=bool)

    rng = np.random.default_rng(seed)
    trajectories = np.full((n_draws, n_days), np.nan)
    for i in range(n_draws):
        traj = hall_path + g_draws[i, :]
        if include_obs_noise:
            sigma_per_day = np.where(is_controlled, sigma_c[i], sigma_u[i])
            traj = traj + rng.normal(0.0, sigma_per_day)
        trajectories[i, :] = traj

    return {
        "lo": np.nanquantile(trajectories, lo, axis=0),
        "median": np.nanquantile(trajectories, 0.5, axis=0),
        "hi": np.nanquantile(trajectories, hi, axis=0),
    }
