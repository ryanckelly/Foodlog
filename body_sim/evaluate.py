"""Evaluation metrics for body-composition forecasts.

All functions accept a long-form DataFrame as produced by
`validation.forward_walk` and return scalar metrics.
"""

import numpy as np
import pandas as pd
from scipy import stats


def _aggregate_to_per_day(walk_df: pd.DataFrame) -> pd.DataFrame:
    """Compute per-day median prediction + 95% band + observed."""
    grouped = walk_df.groupby("date")
    return pd.DataFrame(
        {
            "predicted_median": grouped["predicted_weight_kg"].median(),
            "predicted_lo": grouped["predicted_weight_kg"].quantile(0.025),
            "predicted_hi": grouped["predicted_weight_kg"].quantile(0.975),
            "observed": grouped["observed_weight_kg"].first(),
        }
    ).reset_index()


def mae(walk_df: pd.DataFrame) -> float:
    """Mean absolute error between median prediction and observed weight."""
    per_day = _aggregate_to_per_day(walk_df).dropna(subset=["observed"])
    if per_day.empty:
        return float("nan")
    return float(np.mean(np.abs(per_day["predicted_median"] - per_day["observed"])))


def calibration_coverage(walk_df: pd.DataFrame) -> float:
    """Fraction of observed values inside the 95% predictive band."""
    per_day = _aggregate_to_per_day(walk_df).dropna(subset=["observed"])
    if per_day.empty:
        return float("nan")
    inside = (per_day["observed"] >= per_day["predicted_lo"]) & (
        per_day["observed"] <= per_day["predicted_hi"]
    )
    return float(inside.mean())


def residual_drift_p_value(walk_df: pd.DataFrame) -> float:
    """Kendall's tau p-value testing for monotonic residual drift over time."""
    per_day = _aggregate_to_per_day(walk_df).dropna(subset=["observed"])
    if len(per_day) < 5:
        return float("nan")
    residuals = per_day["observed"] - per_day["predicted_median"]
    day_index = np.arange(len(residuals))
    tau, p = stats.kendalltau(day_index, residuals.values)
    return float(p)


def summary_report(walk_df: pd.DataFrame) -> dict[str, float | int]:
    """Combined metrics dict for use in notebook output."""
    per_day = _aggregate_to_per_day(walk_df).dropna(subset=["observed"])
    return {
        "mae": mae(walk_df),
        "calibration_coverage": calibration_coverage(walk_df),
        "residual_drift_p": residual_drift_p_value(walk_df),
        "n_observations": int(len(per_day)),
    }
