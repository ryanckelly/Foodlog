"""Phase-2 PyMC fit: glycogen-water latent state with per-protocol observation noise.

The model:

    sigma_glycogen          ~ HalfNormal(0.4)       # kg/day glycogen-water innovation
    sigma_obs_controlled    ~ HalfNormal(0.3)       # kg, controlled morning weigh-ins
    sigma_obs_uncontrolled  ~ HalfNormal(0.8)       # kg, uncontrolled weigh-ins
    g_0                     ~ Normal(0, 1.0)        # initial glycogen-water dev
    g_t                     = g_{t-1} + eps_t,  eps_t ~ N(0, sigma_glycogen)
    weight_obs_t            ~ Normal(hall_trajectory_t + g_t, sigma_obs_t)

The Hall trajectory ``hall_trajectory_t`` is precomputed deterministically
outside the PyMC graph at population-default parameters
(``DEFAULT_PARAMETERS``). PyMC sees it as a fixed array. The latent
``g_t`` is what absorbs the day-to-day glycogen-water variance the
deterministic model can't observe — that's the core foodlog-adu fix.

Scope choice (intentional for Phase 2 v1):
- ``intake_bias`` and ``RMR_scale`` are NOT fit here. The Hall trajectory uses
  population defaults. The glycogen latent absorbs any systematic offset
  this introduces, which is acceptable as a Phase-2 first pass.
- A future Phase-2.1 bead can extend this to jointly fit
  ``intake_bias`` / ``RMR_scale`` by either (a) wrapping ``_hall_trajectory``
  in ``pytensor.compile.ops.as_op`` (NUTS no longer applies — use slice or
  Metropolis), or (b) precomputing a grid of trajectories and interpolating
  in pytensor (NUTS-compatible).
"""

import numpy as np
import pandas as pd
import pymc as pm

from body_sim import model, validation
from body_sim.config import DEFAULT_PARAMETERS, UserProfile


def _hall_trajectory(
    df: pd.DataFrame, profile: UserProfile,
    intake_bias: float = None, rmr_scale: float = None,
) -> np.ndarray:
    """Deterministic Hall trajectory through the daily-rollup DataFrame.

    Seeds from the first observed weight (or first reference_weight_kg if no
    observations). Returns a length-n array of predicted_weight_kg, with NaN
    on days where ``model.step`` skipped due to non-finite intake.
    """
    params = dict(DEFAULT_PARAMETERS)
    if intake_bias is not None:
        params["intake_bias"] = intake_bias
    if rmr_scale is not None:
        params["RMR_scale"] = rmr_scale

    first_obs_idx = df["weight_kg"].first_valid_index() if "weight_kg" in df.columns else None
    if first_obs_idx is not None:
        seed_weight = float(df.loc[first_obs_idx, "weight_kg"])
    else:
        seed_weight = float(df["reference_weight_kg"].iloc[0])
    state = model.BodyState(
        fat_mass_kg=seed_weight * 0.22,
        lean_mass_kg=seed_weight * 0.78,
    )
    out = np.full(len(df), np.nan)
    for i, (_, row) in enumerate(df.iterrows()):
        inputs = validation._row_to_input(row)
        state, diag = model.step(state, inputs, profile, params)
        if not diag.get("skipped"):
            out[i] = diag["predicted_weight_kg"]
        else:
            # On skipped days, fall back to current predicted_weight_kg from state
            # so the trajectory doesn't have NaN holes that the latent state
            # would have to bridge through.
            out[i] = state.predicted_weight_kg(0.0)
    return out


def build_model(df: pd.DataFrame, profile: UserProfile) -> pm.Model:
    """Construct the PyMC model conditioned on the daily-rollup DataFrame.

    Args:
        df: daily-rollup DataFrame with at least ``weight_kg`` and
            optionally ``weigh_in_protocol_controlled`` columns.
        profile: user profile (age, sex, height_cm).

    Returns:
        A PyMC Model with named RVs: sigma_glycogen, sigma_obs_controlled,
        sigma_obs_uncontrolled, g (length-n latent), weight_obs (likelihood).
    """
    n = len(df)
    hall_path = _hall_trajectory(df, profile)
    # Replace any NaN in the precomputed trajectory with the previous valid value
    # so PyMC doesn't see NaN in its observed input.
    hall_path = pd.Series(hall_path).ffill().bfill().fillna(80.0).values

    has_weight = df["weight_kg"].notna().values if "weight_kg" in df.columns else np.zeros(n, dtype=bool)
    observed_idx = np.where(has_weight)[0]
    observed_weights = df["weight_kg"].values[observed_idx] if observed_idx.size else np.array([])
    if "weigh_in_protocol_controlled" in df.columns:
        is_controlled = df["weigh_in_protocol_controlled"].astype(bool).values[observed_idx]
    else:
        is_controlled = np.zeros(len(observed_idx), dtype=bool)

    with pm.Model() as m:
        sigma_glycogen = pm.HalfNormal("sigma_glycogen", sigma=0.4)
        sigma_obs_controlled = pm.HalfNormal("sigma_obs_controlled", sigma=0.3)
        sigma_obs_uncontrolled = pm.HalfNormal("sigma_obs_uncontrolled", sigma=0.8)

        # Glycogen-water deviation as a GaussianRandomWalk
        g = pm.GaussianRandomWalk(
            "g",
            mu=0.0,
            sigma=sigma_glycogen,
            init_dist=pm.Normal.dist(mu=0.0, sigma=1.0),
            shape=n,
        )

        # Fixed Hall trajectory as a deterministic data variable
        hall = pm.Data("hall_trajectory", hall_path)

        if observed_idx.size > 0:
            sigma_per_obs = pm.math.where(
                is_controlled, sigma_obs_controlled, sigma_obs_uncontrolled
            )
            mu_obs = hall[observed_idx] + g[observed_idx]
            pm.Normal(
                "weight_obs",
                mu=mu_obs,
                sigma=sigma_per_obs,
                observed=observed_weights,
            )

    return m


def fit(
    df: pd.DataFrame, profile: UserProfile,
    draws: int = 1000, tune: int = 1000, chains: int = 2, seed: int = 0,
    progressbar: bool = False,
):
    """Build and sample the model. Returns an arviz.InferenceData."""
    m = build_model(df, profile)
    with m:
        idata = pm.sample(
            draws=draws, tune=tune, chains=chains, random_seed=seed,
            progressbar=progressbar,
        )
    return idata
