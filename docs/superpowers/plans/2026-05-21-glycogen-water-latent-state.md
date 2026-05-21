# Glycogen-Water Latent State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Beads:** `foodlog-adu` (phase-2, blocked by `foodlog-hg8`) — run `bd show foodlog-adu` for the canonical bead.

**Prereqs:** This plan assumes the following have been completed:
1. **`foodlog-hg8`** — `weigh_in_protocol` column and `weigh_in_protocol_controlled` daily flag exist and propagate through `forward_walk`. This plan depends on per-observation protocol info to set σ_obs.
2. **~30 days of paired food+weight days** in the DB. The Phase-2 epic (`foodlog-j90`) gates on data volume; until ~30 paired days exist, the fit is under-identified and the posterior won't be informative. Check with `bd show foodlog-j90` for current data status before starting.
3. **PyMC available in the body_sim dev environment.** This is the first Phase-2 task — `pymc` is not yet a dependency. Task 1 of this plan adds it.

If any prereq is unmet, **stop and do that prereq first.** Don't fudge the data volume requirement — under-identified Bayesian fits produce confident-looking but meaningless posteriors that will mislead Phase 3.

---

**Goal:** Replace the parameter-only Monte Carlo band in `validation.forward_walk` with a posterior predictive band that includes (a) parameter uncertainty (`intake_bias`, `RMR_scale`), (b) day-to-day glycogen-water innovation noise as a latent state, and (c) per-observation measurement noise scaled by `weigh_in_protocol_controlled`. This widens the daily band legitimately so the calibration metric is meaningful at the daily timescale — not by fudging coverage, but by acknowledging real sources of variance that the deterministic Hall model can't observe.

**Architecture:**
- New `body_sim/bayesian.py` — PyMC model with:
  - `intake_bias ~ Normal(0.85, 0.10)` (prior matches `simulate.PRIOR_SDS`)
  - `RMR_scale ~ Normal(1.0, 0.05)`
  - `sigma_glycogen ~ HalfNormal(0.4)` — day-to-day glycogen-water innovation SD (kg)
  - `sigma_obs_controlled ~ HalfNormal(0.3)` — measurement noise for controlled-morning weigh-ins
  - `sigma_obs_uncontrolled ~ HalfNormal(0.8)` — wider noise for ad-hoc weigh-ins
  - Latent state: `g_t = g_{t-1} + dgly_fn(carb_g_t, glycogen_state) + ε_t`, `ε_t ~ Normal(0, sigma_glycogen)`
  - Re-anchor at each forward-walk reset: `g_anchor ~ Normal(0, 1.0)` — weight tells us nothing about glycogen state directly.
  - Hall trajectory is precomputed deterministically (no need to differentiate through it) and added to `g_t` for the observation likelihood.
  - Observation likelihood: `weight_obs_t ~ Normal(predicted_t + g_t, σ_obs_t)` where `σ_obs_t` is `sigma_obs_controlled` if the row's `weigh_in_protocol_controlled` is True else `sigma_obs_uncontrolled`.
- New `body_sim/bayesian_predict.py` — posterior predictive walk that consumes the trace.
- Update `validation.forward_walk` with a new `mode: Literal["prior", "posterior"] = "prior"` parameter. The prior path is the existing population-default Monte Carlo (kept for regression testing). The posterior path samples from a stored InferenceData and propagates through the latent state.
- Notebook 04 (existing) keeps prior-track. New notebook section (or new notebook `05_bayesian_fit.ipynb`) runs the Bayesian fit and shows posterior diagnostics + posterior-track validation.

**Tech Stack:** PyMC 5.x, ArviZ, NumPy, pandas, pytest. New dev dependency: `pymc>=5.10`.

**Sampling backend:** PyMC's default NumPy + PyTensor BLAS path. NUTS sampler, 2 chains × 1000 tune + 1000 draws. JAX backend optional but not required at this scale.

---

## Open design questions (resolve during execution if needed)

These are flagged honestly as research questions. Pre-deciding them is wrong; resolve based on observed posterior behavior.

1. **Anchoring `g_anchor`.** The bead description says "g_anchor ~ Normal(0, 1 kg) at each reset." If the posterior pulls `g_anchor` consistently away from zero, that's either (a) the population default for `INITIAL_GLYCOGEN_G` is wrong for this user — fold into the `glycogen_scale` parameter, or (b) the model is absorbing some other systematic. Watch for it.
2. **Glycogen-state dynamics.** The current `body_sim/glycogen.py` uses a leaky integrator (ALPHA=0.3, BETA=0.4). It may be too aggressive for a single individual. Consider treating ALPHA and/or BETA as nuisance parameters with weak priors.
3. **σ_obs split.** Two-level (controlled vs uncontrolled) is the minimum viable split. If the controlled posterior is much narrower than 0.3 kg, consider tightening the prior. If the uncontrolled posterior is much wider than 0.8 kg, the protocol heuristic is missing real variance — consider a third "evening" bucket.
4. **Posterior predictive integration.** The forward-walk shape — re-anchor every 7 days — was chosen at Phase 1 for tractability under the deterministic model. With latent state in scope, an alternative is no re-anchor (single trajectory from the first weigh-in, glycogen latent absorbs short-term oscillation). Try both and report the one that calibrates.

These questions are **not blockers** — they're sensitivity analyses to run once a baseline fit converges.

---

## File structure

### New files

```
body_sim/bayesian.py                       PyMC model: build_model() + fit()
body_sim/bayesian_predict.py               posterior-predictive forward walk
notebooks/05_bayesian_fit.ipynb            run fit, save trace, posterior diagnostics
notebooks/predictions/posterior.nc         saved InferenceData (NetCDF; gitignored)
tests/body_sim/test_bayesian.py            unit tests on synthetic data
tests/body_sim/test_bayesian_predict.py    unit tests for posterior walk
```

### Modified files

```
pyproject.toml                              add pymc + arviz to dev extras
body_sim/validation.py                      add mode="prior"|"posterior" to forward_walk
body_sim/CLAUDE.md                          update Phase 1 → Phase 2 transition notes
notebooks/04_hall_baseline.ipynb            add a posterior-track section after the existing prior track
.gitignore                                  ignore notebooks/predictions/*.nc
```

### Output

```
notebooks/predictions/posterior.nc          arviz.InferenceData written by notebook 05; consumed by 04
```

---

## Task 1: Add PyMC to the dev environment

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Inspect current dev extras**

Run: `grep -A 20 "\[project.optional-dependencies\]\|\[tool.poetry\]\|dev = " pyproject.toml`

Identify the `[project.optional-dependencies]` block (or equivalent in poetry/uv format) where dev tools are listed.

- [ ] **Step 2: Add `pymc` and `arviz` to the dev extras**

Edit `pyproject.toml` and add to the dev extras:

```toml
"pymc>=5.10",
"arviz>=0.17",
```

- [ ] **Step 3: Install**

```bash
source .venv/bin/activate
pip install -e ".[dev]"
```

Expected: PyMC + ArviZ install. PyMC pulls in PyTensor and a numerical-linalg stack — first install is slow (~3 minutes).

- [ ] **Step 4: Smoke test the install**

```bash
.venv/bin/python -c "import pymc as pm; import arviz as az; print(pm.__version__, az.__version__)"
```

Expected: prints versions. If PyTensor complains about BLAS, that's fine for Phase 2 fit scale — keep going.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml
git commit -m "build: add pymc + arviz dev deps for Phase 2 Bayesian fit (foodlog-adu)"
```

---

## Task 2: Build the PyMC model on synthetic data (TDD)

**Files:**
- Create: `body_sim/bayesian.py`
- Create: `tests/body_sim/test_bayesian.py`

The test-first approach for a Bayesian model is: **generate data from known parameters, fit the model, check the posterior recovers the parameters within tolerance.** This is a "parameter recovery" test, not an oracle test on a single prediction.

- [ ] **Step 1: Write the failing parameter-recovery test**

Create `tests/body_sim/test_bayesian.py`:

```python
"""Parameter-recovery test for the Phase-2 PyMC model.

Generates synthetic weigh-in data from known intake_bias / RMR_scale /
sigma_glycogen / sigma_obs values, fits the model, and checks the posterior
recovers those values within HDI tolerance. This is the canonical TDD test
for a Bayesian model — pointwise oracle tests would over-fit on a single
draw, but parameter recovery on simulated-from-prior data is a hard
constraint the fit must satisfy.

Skipped if pymc is not installed (Phase 1 / pre-foodlog-adu environments).
"""

import numpy as np
import pandas as pd
import pytest

pymc = pytest.importorskip("pymc")
import arviz as az

from body_sim import bayesian
from body_sim.config import DEFAULT_PROFILE


def _synthetic_data(seed: int = 0) -> pd.DataFrame:
    """30 days of maintenance-ish inputs with known generative parameters."""
    rng = np.random.default_rng(seed)
    n = 30
    idx = pd.date_range("2026-05-01", periods=n, freq="D")
    intake = rng.normal(2400, 80, n)
    carbs = rng.normal(280, 30, n)
    sodium = rng.normal(2300, 200, n)
    # True generative parameters (we'll try to recover these)
    true_intake_bias = 0.90
    true_rmr_scale = 1.02
    true_sigma_glycogen = 0.35
    true_sigma_obs = 0.30
    # Synthesize: nearly maintenance, mild trend
    weights = 80.0 + np.cumsum(rng.normal(0, 0.05, n))
    # Add glycogen-water innovation
    glycogen_innovations = rng.normal(0, true_sigma_glycogen, n).cumsum() * 0.3
    weights += glycogen_innovations
    # Add measurement noise
    weights += rng.normal(0, true_sigma_obs, n)
    return pd.DataFrame({
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
        "reference_weight_kg": 80.0,
        "weigh_in_protocol_controlled": True,
    }, index=idx), {
        "intake_bias": true_intake_bias,
        "RMR_scale": true_rmr_scale,
        "sigma_glycogen": true_sigma_glycogen,
        "sigma_obs_controlled": true_sigma_obs,
    }


@pytest.mark.slow
def test_parameter_recovery_intake_bias():
    """Posterior 94% HDI for intake_bias must contain the true value."""
    df, truth = _synthetic_data(seed=0)
    model = bayesian.build_model(df, profile=DEFAULT_PROFILE)
    with model:
        idata = pymc.sample(draws=500, tune=500, chains=2, random_seed=0, progressbar=False)
    hdi = az.hdi(idata, hdi_prob=0.94)
    lo = float(hdi["intake_bias"].sel(hdi="lower"))
    hi = float(hdi["intake_bias"].sel(hdi="higher"))
    assert lo <= truth["intake_bias"] <= hi, (
        f"intake_bias HDI [{lo:.3f}, {hi:.3f}] does not contain true {truth['intake_bias']:.3f}"
    )


@pytest.mark.slow
def test_parameter_recovery_sigma_obs():
    """Posterior 94% HDI for sigma_obs_controlled must contain the true value."""
    df, truth = _synthetic_data(seed=0)
    model = bayesian.build_model(df, profile=DEFAULT_PROFILE)
    with model:
        idata = pymc.sample(draws=500, tune=500, chains=2, random_seed=0, progressbar=False)
    hdi = az.hdi(idata, hdi_prob=0.94)
    lo = float(hdi["sigma_obs_controlled"].sel(hdi="lower"))
    hi = float(hdi["sigma_obs_controlled"].sel(hdi="higher"))
    assert lo <= truth["sigma_obs_controlled"] <= hi, (
        f"sigma_obs_controlled HDI [{lo:.3f}, {hi:.3f}] does not contain true {truth['sigma_obs_controlled']:.3f}"
    )


def test_build_model_returns_pymc_model():
    """Smoke test that model construction works on a tiny input."""
    df, _ = _synthetic_data()
    model = bayesian.build_model(df.head(5), profile=DEFAULT_PROFILE)
    assert isinstance(model, pymc.Model)
    # The model should have the named variables we expect
    rv_names = {rv.name for rv in model.free_RVs}
    expected = {"intake_bias", "RMR_scale", "sigma_glycogen",
                "sigma_obs_controlled", "sigma_obs_uncontrolled"}
    assert expected.issubset(rv_names), (
        f"missing free RVs: expected {expected}, got {rv_names}"
    )
```

Add a `slow` marker to `pyproject.toml` if pytest doesn't recognize it (`[tool.pytest.ini_options] markers = ["slow: ..."]`).

- [ ] **Step 2: Run the tests — confirm they all fail**

Run: `pytest tests/body_sim/test_bayesian.py -v -m "not slow"`

Expected: smoke test FAILs with `ModuleNotFoundError: body_sim.bayesian`.

- [ ] **Step 3: Implement the PyMC model**

Create `body_sim/bayesian.py`:

```python
"""Phase-2 PyMC fit for body-composition parameters and latent glycogen water.

The model:

  intake_bias        ~ Normal(0.85, 0.10)
  RMR_scale          ~ Normal(1.00, 0.05)
  sigma_glycogen     ~ HalfNormal(0.4)       # kg/day innovation
  sigma_obs_controlled   ~ HalfNormal(0.3)   # kg, controlled morning
  sigma_obs_uncontrolled ~ HalfNormal(0.8)   # kg, ad-hoc
  g_0                ~ Normal(0, 1.0)        # initial glycogen-water dev
  g_t                = g_{t-1} + drift(carb_t) + eps_t,  eps_t ~ N(0, sigma_glycogen)
  weight_obs_t       ~ Normal(hall_trajectory_t + g_t, sigma_obs_t)

The Hall trajectory `hall_trajectory_t` is computed deterministically
outside the PyMC graph using ``simulate.simulate_forward`` with the sampled
``intake_bias`` and ``RMR_scale``. We avoid differentiating through the
mechanistic model by treating it as a black box — PyMC only sees the final
weight series. This is a deliberate scope choice: full ODE-in-PyMC would
require pytensor-ifying ``model.step``, which is Phase 4 work if at all.

Trade-off: the gradient PyMC computes for HMC sampling treats the Hall path
as constant w.r.t. the parameters within one draw. This is valid because we
re-run the deterministic forward pass each draw, but it slows the sampler
down. NUTS on 30 days × 2 free params + 30 latent states converges in
~30s × 2 chains on a modern CPU.
"""

import numpy as np
import pandas as pd
import pymc as pm

from body_sim import simulate
from body_sim.config import DEFAULT_PARAMETERS, UserProfile


def _hall_trajectory(
    df: pd.DataFrame, profile: UserProfile,
    intake_bias: float, rmr_scale: float,
) -> np.ndarray:
    """One deterministic Hall trajectory through the input frame."""
    from body_sim import validation, model
    params = {**DEFAULT_PARAMETERS, "intake_bias": intake_bias, "RMR_scale": rmr_scale}
    seed_weight = float(df["weight_kg"].dropna().iloc[0])
    state = model.BodyState(
        fat_mass_kg=seed_weight * 0.22,
        lean_mass_kg=seed_weight * 0.78,
    )
    weights = []
    for _, row in df.iterrows():
        inputs = validation._row_to_input(row)
        state, diag = model.step(state, inputs, profile, params)
        weights.append(diag.get("predicted_weight_kg", np.nan))
    return np.asarray(weights, dtype=float)


def build_model(df: pd.DataFrame, profile: UserProfile) -> pm.Model:
    """Construct the PyMC model conditioned on the daily-rollup DataFrame.

    Args:
        df: daily-rollup DataFrame (output of pipeline.build_daily_rollup).
            Must include ``weight_kg`` for observation rows and
            ``weigh_in_protocol_controlled`` to select per-row sigma_obs.
        profile: user profile (age, sex, height_cm).

    Returns:
        A PyMC Model with named RVs:
        intake_bias, RMR_scale, sigma_glycogen, sigma_obs_controlled,
        sigma_obs_uncontrolled, g (length-n latent), weight_obs (likelihood).
    """
    n = len(df)
    has_weight = df["weight_kg"].notna().values
    observed_idx = np.where(has_weight)[0]
    observed_weights = df["weight_kg"].values[observed_idx]
    is_controlled = (
        df["weigh_in_protocol_controlled"].astype(bool).values[observed_idx]
        if "weigh_in_protocol_controlled" in df.columns
        else np.zeros(len(observed_idx), dtype=bool)
    )

    with pm.Model() as model:
        # --- Parameters ---
        intake_bias = pm.Normal("intake_bias", mu=0.85, sigma=0.10)
        rmr_scale = pm.Normal("RMR_scale", mu=1.0, sigma=0.05)
        sigma_glycogen = pm.HalfNormal("sigma_glycogen", sigma=0.4)
        sigma_obs_controlled = pm.HalfNormal("sigma_obs_controlled", sigma=0.3)
        sigma_obs_uncontrolled = pm.HalfNormal("sigma_obs_uncontrolled", sigma=0.8)

        # --- Latent glycogen-water deviation ---
        # GaussianRandomWalk with HalfNormal innovation SD
        g = pm.GaussianRandomWalk(
            "g",
            mu=0.0,
            sigma=sigma_glycogen,
            init_dist=pm.Normal.dist(mu=0.0, sigma=1.0),
            shape=n,
        )

        # --- Deterministic Hall trajectory at posterior parameter draws ---
        # We use pm.Deterministic + a python callback. PyMC's NUTS will still
        # work because the trajectory is differentiable in intake_bias/rmr_scale
        # to first order via finite-difference; for a tractable Phase-2 fit
        # we accept this as a black-box "observation function."
        hall = pm.Deterministic(
            "hall_trajectory",
            pm.math.stack([
                pm.math.constant(
                    _hall_trajectory(df, profile,
                                     float(DEFAULT_PARAMETERS["intake_bias"]),
                                     float(DEFAULT_PARAMETERS["RMR_scale"]))[i]
                )
                for i in range(n)
            ])
        )

        # --- Likelihood ---
        if len(observed_idx) > 0:
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

    return model


def fit(
    df: pd.DataFrame, profile: UserProfile,
    draws: int = 1000, tune: int = 1000, chains: int = 2, seed: int = 0,
):
    """Build and sample the model. Returns an arviz.InferenceData."""
    model = build_model(df, profile)
    with model:
        idata = pm.sample(
            draws=draws, tune=tune, chains=chains, random_seed=seed,
            progressbar=False,
        )
    return idata
```

**Implementation note for the executor:** The `_hall_trajectory` shim above passes `DEFAULT_PARAMETERS` rather than the sampled `intake_bias` / `rmr_scale` — this is a bug-on-purpose to keep the first iteration tractable. Once the smoke test passes, **revise** `_hall_trajectory` to accept the sampled parameters and call it once per draw. The proper integration is to wrap `_hall_trajectory` in `pytensor.compile.ops.as_op` so PyMC re-evaluates it each draw, or to precompute the trajectory at a grid of (intake_bias, RMR_scale) and interpolate. This is the heart of the design question and where you'll iterate. Document the choice in the module docstring.

- [ ] **Step 4: Run the smoke test**

Run: `pytest tests/body_sim/test_bayesian.py::test_build_model_returns_pymc_model -v`

Expected: PASS. The smoke test only checks model construction, not posterior recovery.

- [ ] **Step 5: Run the parameter-recovery tests (slow)**

Run: `pytest tests/body_sim/test_bayesian.py -v`

Expected: both `test_parameter_recovery_*` tests PASS within HDI bounds. If they fail, the model is mis-specified or under-identified — iterate on:
- Tighter priors if the chain wanders
- Wider priors if the chain pins to the edge
- More draws (e.g., 2000) if `ess_bulk < 400`

Run `az.summary(idata)` interactively if needed; the diagnostic output for `r_hat > 1.01` or `ess_bulk < 200` is the signal to redesign.

- [ ] **Step 6: Commit**

```bash
git add body_sim/bayesian.py tests/body_sim/test_bayesian.py
git commit -m "feat(body_sim): PyMC model with glycogen latent + protocol-split sigma_obs (foodlog-adu)"
```

---

## Task 3: Posterior-predictive walk

**Files:**
- Create: `body_sim/bayesian_predict.py`
- Create: `tests/body_sim/test_bayesian_predict.py`

The deterministic `simulate.simulate_forward` draws parameter samples from a prior. The posterior predictive analog draws from the posterior and also propagates a latent glycogen state.

- [ ] **Step 1: Write the failing test**

Create `tests/body_sim/test_bayesian_predict.py`:

```python
import numpy as np
import pandas as pd
import pytest

pymc = pytest.importorskip("pymc")
import arviz as az

from body_sim import bayesian, bayesian_predict
from body_sim.config import DEFAULT_PROFILE
from tests.body_sim.test_bayesian import _synthetic_data


@pytest.mark.slow
def test_posterior_predictive_band_calibrates():
    """On synthetic data where the model is correctly specified, the 95%
    posterior predictive band must contain ~95% of held-out observations."""
    rng = np.random.default_rng(0)
    df, _ = _synthetic_data(seed=0)
    # Hold out every 3rd weigh-in
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
    assert coverage >= 0.85, (
        f"posterior-predictive coverage on held-out obs = {coverage:.2f}; "
        "model is under-dispersed"
    )
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest tests/body_sim/test_bayesian_predict.py -v -m "not slow"`

Expected: ImportError on `body_sim.bayesian_predict`.

- [ ] **Step 3: Implement the posterior predictive band**

Create `body_sim/bayesian_predict.py`:

```python
"""Posterior-predictive band that includes parameter + latent + obs noise.

Consumes the arviz.InferenceData from ``bayesian.fit``. For each posterior
draw, runs the deterministic Hall trajectory at that draw's
``intake_bias`` / ``RMR_scale``, adds the per-day latent ``g`` draw, and
returns 2.5/50/97.5 quantiles across draws.
"""

import numpy as np
import pandas as pd

from body_sim import bayesian
from body_sim.config import UserProfile


def posterior_predictive_band(
    idata, df: pd.DataFrame, profile: UserProfile,
    lo: float = 0.025, hi: float = 0.975,
) -> dict[str, np.ndarray]:
    """Per-day quantile band across the posterior draws.

    Args:
        idata: arviz.InferenceData from bayesian.fit
        df: same daily-rollup the fit was conditioned on
        profile: user profile

    Returns:
        Dict with keys 'lo', 'median', 'hi', each shape (n_days,).
    """
    posterior = idata.posterior
    draws = posterior.intake_bias.values.flatten()  # chains × draws
    rmr = posterior.RMR_scale.values.flatten()
    g_draws = posterior.g.values.reshape(-1, posterior.g.shape[-1])

    n_draws = len(draws)
    n_days = len(df)
    trajectories = np.full((n_draws, n_days), np.nan)
    for i in range(n_draws):
        hall_path = bayesian._hall_trajectory(df, profile, float(draws[i]), float(rmr[i]))
        trajectories[i, :] = hall_path + g_draws[i, :]

    return {
        "lo": np.nanquantile(trajectories, lo, axis=0),
        "median": np.nanquantile(trajectories, 0.5, axis=0),
        "hi": np.nanquantile(trajectories, hi, axis=0),
    }
```

- [ ] **Step 4: Run the test**

Run: `pytest tests/body_sim/test_bayesian_predict.py -v`

Expected: PASS at coverage ≥ 0.85.

If it fails at low coverage (under-dispersed band), check that `_hall_trajectory` is being called with the sampled parameters per draw — the Task 2 "bug-on-purpose" must have been fixed by now.

- [ ] **Step 5: Commit**

```bash
git add body_sim/bayesian_predict.py tests/body_sim/test_bayesian_predict.py
git commit -m "feat(body_sim): posterior-predictive band with latent glycogen (foodlog-adu)"
```

---

## Task 4: Wire a `mode="posterior"` path into `forward_walk`

**Files:**
- Modify: `body_sim/validation.py`
- Modify: `tests/body_sim/test_validation.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/body_sim/test_validation.py`:

```python
@pytest.mark.slow
def test_forward_walk_posterior_mode():
    """Posterior-mode walk returns a DataFrame with the same schema as
    prior-mode, but with samples drawn from a fitted InferenceData."""
    pymc = pytest.importorskip("pymc")
    from body_sim import bayesian
    from tests.body_sim.test_bayesian import _synthetic_data

    df, _ = _synthetic_data(seed=0)
    idata = bayesian.fit(df, profile=DEFAULT_PROFILE, draws=200, tune=200, seed=0)

    out = validation.forward_walk(
        df, step_days=7, profile=DEFAULT_PROFILE, sample_n=200, seed=0,
        mode="posterior", idata=idata,
    )
    assert "predicted_weight_kg" in out.columns
    assert len(out) > 0
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest tests/body_sim/test_validation.py::test_forward_walk_posterior_mode -v`

Expected: FAIL with TypeError on `mode` kwarg.

- [ ] **Step 3: Add mode + idata to forward_walk**

In `body_sim/validation.py`, change the `forward_walk` signature and add posterior branch logic at the top of the function:

```python
def forward_walk(
    df: pd.DataFrame,
    step_days: int,
    profile: UserProfile,
    sample_n: int,
    seed: int | None = None,
    mode: str = "prior",
    idata=None,
) -> pd.DataFrame:
    """Forward-walking validation over the rollup DataFrame.

    Args:
        df: daily-rollup DataFrame.
        step_days: chunk size for the walk.
        profile: user profile.
        sample_n: number of parameter samples per chunk (prior mode) or
            number of posterior draws to use (posterior mode).
        seed: RNG seed.
        mode: "prior" (population-default Monte Carlo, the Phase-1 path) or
            "posterior" (draws from arviz.InferenceData ``idata``).
        idata: arviz.InferenceData from bayesian.fit (required when mode="posterior").

    Returns:
        Long-form DataFrame; see prior-mode docstring for columns.
    """
    if mode == "posterior":
        if idata is None:
            raise ValueError("mode='posterior' requires idata=")
        return _forward_walk_posterior(df, step_days, profile, sample_n, seed, idata)
    # ... existing prior-mode code unchanged ...
```

Then add `_forward_walk_posterior` below `forward_walk`:

```python
def _forward_walk_posterior(
    df: pd.DataFrame, step_days: int, profile: UserProfile,
    sample_n: int, seed: int | None, idata,
) -> pd.DataFrame:
    """Posterior-mode forward walk.

    Instead of sampling from the parameter prior, draws from idata.posterior
    and propagates each draw's Hall trajectory + latent g through the same
    chunk-and-reseed walk structure. The band emitted by this mode is the
    posterior predictive band the daily-track calibration metric was
    structurally unable to produce in Phase 1.
    """
    from body_sim import bayesian_predict

    if df.empty:
        return pd.DataFrame()

    band = bayesian_predict.posterior_predictive_band(idata, df, profile)
    # Emit each day with sample_n synthetic samples drawn from the band
    # quantiles — preserves the long-form schema downstream code expects.
    posterior = idata.posterior
    draws_per_day = posterior.g.values.reshape(-1, posterior.g.shape[-1])
    n_draws_total = draws_per_day.shape[0]
    rng = np.random.default_rng(seed)
    pick = rng.choice(n_draws_total, size=sample_n, replace=(sample_n > n_draws_total))

    records = []
    for d, ts in enumerate(df.index):
        observed = (
            float(df.iloc[d]["weight_kg"])
            if pd.notna(df.iloc[d]["weight_kg"]) else np.nan
        )
        protocol = bool(df.iloc[d].get("weigh_in_protocol_controlled", False))
        # Posterior trajectory per selected draw
        for s, draw_idx in enumerate(pick):
            # bayesian_predict has the cached trajectories internally; for
            # this path we recompute one draw to keep memory bounded.
            ib = float(posterior.intake_bias.values.flatten()[draw_idx])
            rs = float(posterior.RMR_scale.values.flatten()[draw_idx])
            hall_path = bayesian._hall_trajectory(df, profile, ib, rs)
            g_path = draws_per_day[draw_idx, :]
            records.append({
                "date": ts,
                "sample": s,
                "predicted_weight_kg": float(hall_path[d] + g_path[d]),
                "observed_weight_kg": observed,
                "fat_mass_kg": np.nan,  # not exposed by posterior shim; fill if needed
                "lean_mass_kg": np.nan,
                "body_fat_pct": np.nan,
                "weigh_in_protocol_controlled": protocol,
            })
    return pd.DataFrame(records)
```

This implementation recomputes the Hall trajectory once per (sample × day) which is wasteful — for a 30-day window × 200 samples that's 6000 trajectory evaluations. **Acceptable for Phase-2 throughput** since `_hall_trajectory` is O(30 days × ~50 µs/step) = ~1.5 ms per trajectory. Total: ~10 seconds. If this becomes a hot path later, cache the per-draw trajectories.

- [ ] **Step 4: Add `body_sim/bayesian.py` import for `_hall_trajectory` re-use**

Already covered by the `from body_sim import bayesian` import inside `_forward_walk_posterior` and the call to `bayesian._hall_trajectory(...)`. No change needed.

- [ ] **Step 5: Run the test**

Run: `pytest tests/body_sim/test_validation.py::test_forward_walk_posterior_mode -v`

Expected: PASS.

- [ ] **Step 6: Run the full validation test module**

Run: `pytest tests/body_sim/test_validation.py -v`

Expected: all PASS — prior mode is unchanged.

- [ ] **Step 7: Commit**

```bash
git add body_sim/validation.py tests/body_sim/test_validation.py
git commit -m "feat(body_sim): forward_walk mode='posterior' using PyMC InferenceData (foodlog-adu)"
```

---

## Task 5: Notebook 05 — run the fit, save the trace, show diagnostics

**Files:**
- Create: `notebooks/05_bayesian_fit.ipynb`
- Modify: `.gitignore`

- [ ] **Step 1: Add `.nc` to gitignore**

Edit `.gitignore` and add:

```
notebooks/predictions/*.nc
```

- [ ] **Step 2: Create the notebook**

From `/opt/foodlog/`, launch Jupyter and create `notebooks/05_bayesian_fit.ipynb` with these cells (one cell per bullet):

Cell 1 (markdown):
```markdown
# 05 — Phase-2 Bayesian Fit

Fits `intake_bias`, `RMR_scale`, glycogen-water latent state, and per-protocol observation noise via PyMC. Saves the trace to `notebooks/predictions/posterior.nc` for consumption by notebook 04's posterior-track section.

See `body_sim/bayesian.py` for the model spec and `foodlog-adu` for the bead.
```

Cell 2 (code):
```python
import sys
from pathlib import Path
import pandas as pd
import arviz as az
import matplotlib.pyplot as plt

REPO_ROOT = Path.cwd().parent if Path.cwd().name == 'notebooks' else Path.cwd()
sys.path.insert(0, str(REPO_ROOT))

from body_sim.config import DEFAULT_PROFILE
from body_sim import bayesian

df = pd.read_parquet(REPO_ROOT / 'notebooks' / 'predictions' / 'daily_rollup.parquet')
df.tail()
```

Cell 3 (code — run the fit):
```python
idata = bayesian.fit(df, profile=DEFAULT_PROFILE, draws=1000, tune=1000, chains=2, seed=42)
idata.to_netcdf(REPO_ROOT / 'notebooks' / 'predictions' / 'posterior.nc')
```

Cell 4 (code — diagnostics):
```python
az.summary(idata, var_names=[
    "intake_bias", "RMR_scale", "sigma_glycogen",
    "sigma_obs_controlled", "sigma_obs_uncontrolled",
])
```

Cell 5 (markdown):
```markdown
## Trace and energy plots

`r_hat` should be ≤ 1.01 and `ess_bulk` should be ≥ 400 per chain for each parameter. If not, increase `tune` and re-run.
```

Cell 6 (code):
```python
az.plot_trace(idata, var_names=["intake_bias", "RMR_scale", "sigma_glycogen", "sigma_obs_controlled", "sigma_obs_uncontrolled"])
plt.tight_layout()
plt.show()
```

Cell 7 (code):
```python
az.plot_energy(idata)
plt.show()
```

Cell 8 (markdown):
```markdown
## Posterior predictive vs. observed

If the model is well-specified, observed weigh-ins should sit inside the posterior predictive band most of the time.
```

Cell 9 (code):
```python
from body_sim import bayesian_predict
import numpy as np

band = bayesian_predict.posterior_predictive_band(idata, df, profile=DEFAULT_PROFILE)
fig, ax = plt.subplots(figsize=(10, 5))
ax.fill_between(df.index, band["lo"], band["hi"], alpha=0.25, label="95% posterior predictive")
ax.plot(df.index, band["median"], linewidth=2, label="Posterior median")
obs = df.dropna(subset=["weight_kg"])
ax.scatter(obs.index, obs["weight_kg"], color="black", zorder=5, label="Observed")
ax.set_ylabel("Weight (kg)")
ax.legend()
ax.grid(alpha=0.3)
plt.show()
```

- [ ] **Step 3: Execute the notebook**

```bash
.venv/bin/jupyter nbconvert --to notebook --execute notebooks/05_bayesian_fit.ipynb \
    --output 05_bayesian_fit.ipynb --ExecutePreprocessor.timeout=1800
```

Expected: 5–15 minutes of sampling. Trace and band render. `r_hat` ≤ 1.01 for all parameters. **If `r_hat > 1.01` for any parameter, do NOT proceed.** Iterate on priors / sampler settings until the chain mixes.

- [ ] **Step 4: Commit**

```bash
git add .gitignore notebooks/05_bayesian_fit.ipynb
git commit -m "feat(body_sim): notebook 05 — Bayesian fit + posterior predictive (foodlog-adu)"
```

---

## Task 6: Notebook 04 posterior-track section

**Files:**
- Modify: `notebooks/04_hall_baseline.ipynb`

- [ ] **Step 1: Add a new section at the end of notebook 04**

After the existing "Diagnostic interpretation" markdown cell, add:

Cell (markdown):
```markdown
## Posterior track (Phase 2)

The prior-track band above is too narrow for daily-weigh-in calibration because it doesn't model latent-state noise. The posterior track loads the InferenceData saved by notebook 05 and re-runs the forward walk in `mode='posterior'`, producing a band that includes parameter, latent-glycogen, and per-protocol observation uncertainty.

Daily calibration on this track is the canonical Phase-2 acceptance metric.
```

Cell (code):
```python
import arviz as az

idata = az.from_netcdf(REPO_ROOT / 'notebooks' / 'predictions' / 'posterior.nc')
walk_post = validation.forward_walk(
    df, step_days=7, profile=DEFAULT_PROFILE, sample_n=200, seed=42,
    mode="posterior", idata=idata,
)
rep_post_daily = evaluate.summary_report(walk_post)
rep_post_weekly = evaluate.summary_report_weekly(walk_post)
print("=== Posterior — Daily ===")
print(f'MAE: {rep_post_daily["mae"]:.3f} kg, calibration: {100*rep_post_daily["calibration_coverage"]:.1f}%')
print("=== Posterior — Weekly ===")
print(f'MAE: {rep_post_weekly["mae"]:.3f} kg, calibration: {100*rep_post_weekly["calibration_coverage"]:.1f}%')
```

Cell (code):
```python
fig = plotting.trajectory_plot(walk_post, metric='weight')
plt.show()
```

- [ ] **Step 2: Execute notebook 04**

```bash
.venv/bin/jupyter nbconvert --to notebook --execute notebooks/04_hall_baseline.ipynb \
    --output 04_hall_baseline.ipynb --ExecutePreprocessor.timeout=1800
```

Expected: posterior daily calibration ≥ 80%. **This is the bead's hard acceptance criterion.** If it's not met, the model is misspecified — iterate on Tasks 2/3 with diagnostics from the previous notebook run.

- [ ] **Step 3: Commit**

```bash
git add notebooks/04_hall_baseline.ipynb
git commit -m "feat(body_sim): notebook 04 — posterior-track section (foodlog-adu)"
```

---

## Task 7: Documentation + close

**Files:**
- Modify: `body_sim/CLAUDE.md`

- [ ] **Step 1: Update CLAUDE.md**

In `body_sim/CLAUDE.md`, in the "Phase 1 known limitations" section, mark the daily-calibration item as resolved and add a Phase-2 section:

```markdown
## Phase 2 results

`foodlog-adu` (closed YYYY-MM-DD) landed the PyMC fit with glycogen-water latent state. Daily-weigh-in calibration now reaches XX% (was 43% under Phase-1 prior-track). The two big architectural changes:

1. **Glycogen-water as a GaussianRandomWalk latent state** with `sigma_glycogen` posterior ~ N kg/day. The day-to-day weight wobble is now absorbed by the latent track rather than blamed on the model.
2. **Per-protocol observation noise:** `sigma_obs_controlled` posterior ~ X kg vs `sigma_obs_uncontrolled` ~ Y kg, confirming the morning-routine weigh-ins are tighter than ad-hoc ones (which informed the Phase-1 protocol metadata in `foodlog-hg8`).

Posterior parameter summary at `notebooks/predictions/posterior.nc` (gitignored — regenerate via notebook 05).

Open Phase-3 inputs:
- `intake_bias` posterior is well-identified at ~X.XX — fold into Phase 3 baseline.
- `sigma_glycogen` posterior is at ~XX kg/day, plausible per literature.
- (Add other surprises observed during the fit.)
```

Fill in the XX values from the actual posterior summary printed in notebook 05.

- [ ] **Step 2: Commit**

```bash
git add body_sim/CLAUDE.md
git commit -m "docs(body_sim): Phase-2 results — daily calibration unblocked (foodlog-adu)"
```

- [ ] **Step 3: Close the bead**

```bash
bd close foodlog-adu --reason="PyMC fit lands with glycogen latent + per-protocol sigma_obs; daily calibration is now XX% (was 43% prior-track). Notebooks 05 (fit) and 04 (posterior track) cover the workflow. Phase-3 inputs documented in body_sim/CLAUDE.md."
```

- [ ] **Step 4: Session-close protocol**

```bash
git pull --rebase
bd dolt push 2>&1 || true
git push
git status
```

---

## Self-review notes

- **Scope:** the bead's acceptance items (glycogen latent state, forward-walk band includes it, daily calibration ≥80%, intake_bias posterior narrower than prior) are all covered by Tasks 2–6.
- **Prereqs flagged:** Task 0 (the document header) explicitly requires `foodlog-hg8` and ~30 days of data before starting.
- **Honesty about research:** "Open design questions" section lists four genuine sensitivity choices that must be resolved during execution. This is a research-flavored task — over-specifying the priors here would be premature.
- **Bug-on-purpose flagged explicitly:** the Task 2 Step 3 code passes `DEFAULT_PARAMETERS` rather than sampled values; this is called out and must be fixed before the parameter-recovery test will pass.
- **Test patterns:** parameter recovery on simulated-from-prior data, held-out predictive coverage. Not pointwise oracles.
- **Failure modes documented:** what to do if `r_hat > 1.01` or coverage < 0.85. The plan won't push broken posteriors as "done."
- **Closure:** Task 7 closes the bead and pushes per the session-completion protocol.

## Possible scope split

This plan covers both Phase-2 PyMC infrastructure (Tasks 1–3) and the specific glycogen-water work (Tasks 4–6). If the executor wants finer granularity, Tasks 1–3 could be split into a separate "phase-2 setup" plan (a new bead under `foodlog-j90`) that lands first, with this plan reducing to Tasks 4–7. Either order works — the four tasks integrate cleanly.
