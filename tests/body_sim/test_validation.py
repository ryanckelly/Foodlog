import datetime

import numpy as np
import pandas as pd
import pytest

from body_sim import validation
from body_sim.config import DEFAULT_PROFILE


def _synthetic_rollup(n_days: int, base_weight: float = 80.0) -> pd.DataFrame:
    """Synthetic daily rollup with maintenance-ish inputs."""
    idx = pd.date_range(start="2026-05-01", periods=n_days, freq="D")
    weights = base_weight + np.linspace(0, -0.5, n_days)  # tiny linear loss
    return pd.DataFrame(
        {
            "intake_kcal": 2400.0,
            "protein_g": 120.0,
            "carb_g": 280.0,
            "fat_g": 75.0,
            "sodium_mg": 2300.0,
            "ee_hr_keytel_kcal": 600.0,
            "workout_kcal": 0.0,
            "vigorous_min": 0,
            "intake_logged": True,
            "hr_coverage_pct": 100.0,
            "steps": 8000,
            "weight_kg": np.where(np.arange(n_days) % 2 == 0, weights, np.nan),
            "bf_pct": np.nan,
            "reference_weight_kg": base_weight,
        },
        index=idx,
    )


def test_forward_walk_returns_long_dataframe():
    df = _synthetic_rollup(n_days=14)
    out = validation.forward_walk(
        df, step_days=7, profile=DEFAULT_PROFILE, sample_n=10, seed=0
    )
    assert "predicted_weight_kg" in out.columns
    assert "observed_weight_kg" in out.columns
    assert "sample" in out.columns
    assert "date" in out.columns
    assert len(out) > 0


def test_forward_walk_covers_all_dates_after_seed():
    df = _synthetic_rollup(n_days=21)
    out = validation.forward_walk(
        df, step_days=7, profile=DEFAULT_PROFILE, sample_n=5, seed=0
    )
    # We seed initial state from the first observed weight, then walk forward.
    unique_dates = out["date"].unique()
    assert len(unique_dates) >= 7  # at least one full chunk worth of predictions


def test_forward_walk_observed_aligned():
    df = _synthetic_rollup(n_days=14)
    out = validation.forward_walk(
        df, step_days=7, profile=DEFAULT_PROFILE, sample_n=2, seed=0
    )
    # Observed weights should match the source DataFrame for the dates where we have them
    for _, row in out.iterrows():
        d = row["date"]
        if pd.notna(row["observed_weight_kg"]):
            assert row["observed_weight_kg"] == pytest.approx(df.loc[d, "weight_kg"])
