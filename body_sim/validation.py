"""Forward-walking validation harness.

Walks through the daily-rollup DataFrame in `step_days`-sized chunks. For each
chunk: seed initial state from the most recent observed weight (or carry forward
the simulated state if no recent weigh-in), simulate forward N days drawing
parameter samples from the prior, record (date, sample, predicted, observed)
tuples for later evaluation and plotting.
"""

import numpy as np
import pandas as pd

from body_sim import model, simulate
from body_sim.config import DEFAULT_PROFILE, UserProfile


INPUT_COLUMNS = [
    "intake_kcal", "protein_g", "carb_g", "fat_g", "sodium_mg",
    "ee_hr_keytel_kcal", "workout_kcal", "vigorous_min", "intake_logged",
    "hr_coverage_pct", "steps",
]


def _seed_state(reference_weight: float, target_bf_pct: float = 22.0) -> model.BodyState:
    """Seed initial body composition from a weight observation.

    At Phase 1 we use a fixed bf% prior; future phases personalize this from
    the user's own observed bf%.
    """
    fat = reference_weight * (target_bf_pct / 100.0)
    lean = reference_weight - fat
    return model.BodyState(fat_mass_kg=fat, lean_mass_kg=lean)


def _row_to_input(row: pd.Series) -> dict:
    inputs = {col: row[col] for col in INPUT_COLUMNS}
    # Coerce types
    for k in ("intake_kcal", "protein_g", "carb_g", "fat_g", "sodium_mg",
              "ee_hr_keytel_kcal", "workout_kcal", "hr_coverage_pct"):
        v = inputs[k]
        inputs[k] = 0.0 if pd.isna(v) else float(v)
    inputs["vigorous_min"] = 0 if pd.isna(inputs["vigorous_min"]) else int(inputs["vigorous_min"])
    inputs["steps"] = 0 if pd.isna(inputs["steps"]) else int(inputs["steps"])
    inputs["intake_logged"] = bool(inputs["intake_logged"])
    return inputs


def forward_walk(
    df: pd.DataFrame,
    step_days: int,
    profile: UserProfile,
    sample_n: int,
    seed: int | None = None,
) -> pd.DataFrame:
    """Forward-walking validation over the rollup DataFrame.

    Args:
        df: daily-rollup DataFrame (output of pipeline.build_daily_rollup)
        step_days: chunk size for the walk
        profile: user profile
        sample_n: number of parameter samples per chunk
        seed: RNG seed

    Returns:
        Long-form DataFrame with columns date, sample, predicted_weight_kg,
        observed_weight_kg, fat_mass_kg, lean_mass_kg.
    """
    if df.empty:
        return pd.DataFrame()

    samples = simulate.sample_parameters(n=sample_n, seed=seed)
    records: list[dict] = []

    # First observation (or fallback) seeds the initial state
    first_observed_idx = df["weight_kg"].first_valid_index()
    if first_observed_idx is None:
        seed_weight = float(df["reference_weight_kg"].iloc[0])
    else:
        seed_weight = float(df.loc[first_observed_idx, "weight_kg"])
    initial = _seed_state(seed_weight)

    cur_idx = df.index[0] if first_observed_idx is None else first_observed_idx
    while cur_idx < df.index[-1]:
        end_idx_pos = min(
            len(df) - 1,
            df.index.get_loc(cur_idx) + step_days,
        )
        end_idx = df.index[end_idx_pos]
        chunk = df.loc[cur_idx:end_idx]
        inputs_per_day = [_row_to_input(row) for _, row in chunk.iterrows()]
        result = simulate.simulate_forward(
            initial_state=initial,
            inputs_per_day=inputs_per_day,
            profile=profile,
            parameter_samples=samples,
        )
        for s in range(sample_n):
            for d_offset, ts in enumerate(chunk.index):
                records.append(
                    {
                        "date": ts,
                        "sample": s,
                        "predicted_weight_kg": float(result.predicted_weight_kg[s, d_offset]),
                        "observed_weight_kg": (
                            float(chunk.iloc[d_offset]["weight_kg"])
                            if pd.notna(chunk.iloc[d_offset]["weight_kg"])
                            else np.nan
                        ),
                        "fat_mass_kg": float(result.fat_mass_kg[s, d_offset]),
                        "lean_mass_kg": float(result.lean_mass_kg[s, d_offset]),
                        "body_fat_pct": float(result.body_fat_pct[s, d_offset]),
                    }
                )
        # Next chunk: re-seed from the most recent observed weight in this chunk if any
        weighed = chunk["weight_kg"].dropna()
        if not weighed.empty:
            initial = _seed_state(float(weighed.iloc[-1]))
        cur_idx = end_idx + pd.Timedelta(days=1)

    return pd.DataFrame(records)
