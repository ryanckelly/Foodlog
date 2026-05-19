"""Forward simulation of body-composition trajectories.

Repeatedly applies `model.step` to roll the state forward N days under a given
input series, once per parameter sample. Returns arrays of shape (n_samples,
n_days) for each tracked quantity, plus helpers to compute credible bands.

Assumption: inputs_per_day entries must have finite `intake_kcal`. If a day's
input has NaN/None intake, `model.step` returns the state unchanged with
``{"skipped": True}`` and the diagnostics dict will not contain
``predicted_weight_kg`` / ``delta_e_kcal`` / ``expenditure_kcal``. In that
case the simulation fills the corresponding output slot with NaN. Phase 1 tests
always supply clean finite inputs, so this path is not exercised in tests —
it is documented here for Phase 2+ callers that may pass real pipeline rows.
"""

from dataclasses import dataclass

import numpy as np

from body_sim import model
from body_sim.config import DEFAULT_PARAMETERS, UserProfile


# Width of Gaussian prior around each population-default parameter
PRIOR_SDS = {
    "intake_bias": 0.10,
    "RMR_scale": 0.05,
    "NEAT_response": 0.10,
    "protein_protection": 0.20,
    "activity_bias": 0.10,
    "water_noise_sd": 0.2,
}


def sample_parameters(
    n: int, base: dict | None = None, seed: int | None = None
) -> dict[str, np.ndarray]:
    """Draw `n` independent samples from each parameter's population prior.

    Returns a dict mapping parameter name to a length-n NumPy array.
    Uses ``np.random.default_rng`` so results are fully reproducible given the
    same ``seed`` regardless of global NumPy random state.
    """
    if base is None:
        base = DEFAULT_PARAMETERS
    rng = np.random.default_rng(seed)
    return {
        name: rng.normal(loc=base[name], scale=PRIOR_SDS[name], size=n)
        for name in PRIOR_SDS
    }


@dataclass
class SimulationResult:
    predicted_weight_kg: np.ndarray   # shape (n_samples, n_days)
    fat_mass_kg: np.ndarray
    lean_mass_kg: np.ndarray
    body_fat_pct: np.ndarray
    delta_e_kcal: np.ndarray
    expenditure_kcal: np.ndarray


def simulate_forward(
    initial_state: model.BodyState,
    inputs_per_day: list[dict],
    profile: UserProfile,
    parameter_samples: dict[str, np.ndarray],
) -> SimulationResult:
    """Roll the model forward over the input series, once per parameter sample.

    Each sample draws one scalar per parameter from ``parameter_samples`` and
    runs an independent trajectory starting from a fresh copy of
    ``initial_state``. The BodyState is copied at the start of each sample loop
    so samples are fully independent.

    Args:
        initial_state: Starting BodyState (fat_mass_kg, lean_mass_kg, etc.).
        inputs_per_day: List of daily input dicts, one per simulation day.
        profile: User demographic profile (age, sex, height_cm).
        parameter_samples: Dict of parameter name -> length-n array of draws.

    Returns:
        SimulationResult with six arrays of shape (n_samples, n_days).
        Skipped days (non-finite intake) produce NaN in all output arrays for
        that (sample, day) slot.
    """
    n_samples = next(iter(parameter_samples.values())).shape[0]
    n_days = len(inputs_per_day)

    predicted = np.full((n_samples, n_days), np.nan)
    fat = np.full((n_samples, n_days), np.nan)
    lean = np.full((n_samples, n_days), np.nan)
    bf_pct = np.full((n_samples, n_days), np.nan)
    de = np.full((n_samples, n_days), np.nan)
    ee = np.full((n_samples, n_days), np.nan)

    for s in range(n_samples):
        params = {name: float(parameter_samples[name][s]) for name in parameter_samples}
        # Fresh independent copy of state for each sample trajectory
        state = model.BodyState(
            fat_mass_kg=initial_state.fat_mass_kg,
            lean_mass_kg=initial_state.lean_mass_kg,
            glycogen_g=initial_state.glycogen_g,
        )
        for d, inputs in enumerate(inputs_per_day):
            state, diag = model.step(state=state, inputs=inputs, profile=profile, parameters=params)
            if diag.get("skipped"):
                # Non-finite intake: state unchanged, fill with NaN for this day
                fat[s, d] = state.fat_mass_kg
                lean[s, d] = state.lean_mass_kg
                bf_pct[s, d] = state.body_fat_pct  # property, no parens
                # predicted_weight_kg, delta_e_kcal, expenditure_kcal stay NaN
            else:
                predicted[s, d] = diag["predicted_weight_kg"]
                fat[s, d] = state.fat_mass_kg
                lean[s, d] = state.lean_mass_kg
                bf_pct[s, d] = state.body_fat_pct  # property, no parens
                de[s, d] = diag["delta_e_kcal"]
                ee[s, d] = diag["expenditure_kcal"]

    return SimulationResult(
        predicted_weight_kg=predicted,
        fat_mass_kg=fat,
        lean_mass_kg=lean,
        body_fat_pct=bf_pct,
        delta_e_kcal=de,
        expenditure_kcal=ee,
    )


def credible_band(
    arr: np.ndarray, lo: float = 0.025, hi: float = 0.975
) -> dict[str, np.ndarray]:
    """Per-day quantile band across the sample axis (axis=0).

    Args:
        arr: Array of shape (n_samples, n_days).
        lo: Lower quantile (default 2.5%).
        hi: Upper quantile (default 97.5%).

    Returns:
        Dict with keys ``"lo"``, ``"median"``, ``"hi"``, each shape (n_days,).
    """
    return {
        "lo": np.quantile(arr, lo, axis=0),
        "median": np.quantile(arr, 0.5, axis=0),
        "hi": np.quantile(arr, hi, axis=0),
    }
