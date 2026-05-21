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


def test_row_to_input_preserves_nan_intake():
    """NaN intake_kcal must propagate so model.step's skip guard fires.

    Regression for the bug where _row_to_input coerced NaN -> 0.0, making
    model.step treat unlogged days as 0-kcal days under full expenditure.
    """
    row = pd.Series(
        {
            "intake_kcal": np.nan,
            "protein_g": np.nan,
            "carb_g": np.nan,
            "fat_g": np.nan,
            "sodium_mg": np.nan,
            "ee_hr_keytel_kcal": 600.0,
            "workout_kcal": 0.0,
            "vigorous_min": 0,
            "intake_logged": False,
            "hr_coverage_pct": 100.0,
            "steps": 8000,
        }
    )
    inputs = validation._row_to_input(row)
    assert np.isnan(inputs["intake_kcal"]), (
        f"intake_kcal NaN was coerced to {inputs['intake_kcal']!r}; "
        "model.step's skip-on-NaN guard will not fire on unlogged days"
    )


def test_forward_walk_does_not_invent_deficits_on_nan_intake_days():
    """13 unlogged days following one logged maintenance day should not
    produce phantom weight loss. Without the fix, expenditure runs against
    intake=0 and the trajectory crashes downward."""
    n_days = 14
    idx = pd.date_range(start="2026-05-01", periods=n_days, freq="D")
    intake = np.full(n_days, np.nan)
    intake[0] = 2400.0  # one logged day to seed/anchor
    logged = np.isfinite(intake)
    df = pd.DataFrame(
        {
            "intake_kcal": intake,
            "protein_g": np.where(logged, 120.0, np.nan),
            "carb_g": np.where(logged, 280.0, np.nan),
            "fat_g": np.where(logged, 75.0, np.nan),
            "sodium_mg": np.where(logged, 2300.0, np.nan),
            "ee_hr_keytel_kcal": 600.0,
            "workout_kcal": 0.0,
            "vigorous_min": 0,
            "intake_logged": logged,
            "hr_coverage_pct": 100.0,
            "steps": 8000,
            "weight_kg": np.where(np.arange(n_days) == 0, 80.0, np.nan),
            "bf_pct": np.nan,
            "reference_weight_kg": 80.0,
        },
        index=idx,
    )
    out = validation.forward_walk(
        df, step_days=7, profile=DEFAULT_PROFILE, sample_n=10, seed=0
    )
    # State (fat+lean) should not collapse on NaN-intake days. The bug made
    # the trajectory shed ~5 kg over 13 phantom-deficit days.
    final_fat = out[out["date"] == idx[-1]]["fat_mass_kg"].median()
    final_lean = out[out["date"] == idx[-1]]["lean_mass_kg"].median()
    final_total = final_fat + final_lean
    assert abs(final_total - 80.0) < 1.5, (
        f"NaN-intake days advanced state to {final_total:.2f} kg from 80.0 kg; "
        "skip-on-NaN contract was bypassed"
    )
