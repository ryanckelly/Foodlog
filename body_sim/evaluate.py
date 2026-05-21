"""Evaluation metrics for body-composition forecasts.

All functions accept a long-form DataFrame as produced by
`validation.forward_walk` and return scalar metrics.
"""

import numpy as np
import pandas as pd
from scipy import stats


def _aggregate_to_per_period(walk_df: pd.DataFrame, window_days: int = 1) -> pd.DataFrame:
    """Compute per-day median prediction + 95% band + observed, optionally
    smoothed by a trailing rolling mean of `window_days`.

    window_days=1 reproduces the pre-window behavior (no smoothing).
    window_days=7 produces a 7-day trailing rolling mean of every column,
    which averages out short-timescale water/glycogen noise on both sides of
    the comparison.
    """
    grouped = walk_df.groupby("date")
    per_day = pd.DataFrame(
        {
            "predicted_median": grouped["predicted_weight_kg"].median(),
            "predicted_lo": grouped["predicted_weight_kg"].quantile(0.025),
            "predicted_hi": grouped["predicted_weight_kg"].quantile(0.975),
            "observed": grouped["observed_weight_kg"].first(),
        }
    )
    if window_days > 1:
        per_day = per_day.rolling(window=window_days, min_periods=1).mean()
    return per_day.reset_index()


def _aggregate_to_per_day(walk_df: pd.DataFrame) -> pd.DataFrame:
    """Back-compat alias: window_days=1."""
    return _aggregate_to_per_period(walk_df, window_days=1)


def mae(walk_df: pd.DataFrame, window_days: int = 1) -> float:
    """Mean absolute error between median prediction and observed weight.

    window_days > 1 applies a trailing rolling mean to predictions and
    observations before computing residuals — appropriate when the
    biological observation noise (glycogen-water, gut contents, sodium ECF)
    is large relative to the model's parameter-uncertainty band.
    """
    per_day = _aggregate_to_per_period(walk_df, window_days).dropna(subset=["observed"])
    if per_day.empty:
        return float("nan")
    return float(np.mean(np.abs(per_day["predicted_median"] - per_day["observed"])))


def calibration_coverage(walk_df: pd.DataFrame, window_days: int = 1) -> float:
    """Fraction of observed values inside the 95% predictive band."""
    per_day = _aggregate_to_per_period(walk_df, window_days).dropna(subset=["observed"])
    if per_day.empty:
        return float("nan")
    inside = (per_day["observed"] >= per_day["predicted_lo"]) & (
        per_day["observed"] <= per_day["predicted_hi"]
    )
    return float(inside.mean())


def residual_drift_p_value(walk_df: pd.DataFrame, window_days: int = 1) -> float:
    """Kendall's tau p-value testing for monotonic residual drift over time."""
    per_day = _aggregate_to_per_period(walk_df, window_days).dropna(subset=["observed"])
    if len(per_day) < 5:
        return float("nan")
    residuals = per_day["observed"] - per_day["predicted_median"]
    day_index = np.arange(len(residuals))
    tau, p = stats.kendalltau(day_index, residuals.values)
    return float(p)


def summary_report(walk_df: pd.DataFrame, window_days: int = 1) -> dict[str, float | int]:
    """Combined metrics dict for notebook output."""
    per_day = _aggregate_to_per_period(walk_df, window_days).dropna(subset=["observed"])
    return {
        "mae": mae(walk_df, window_days),
        "calibration_coverage": calibration_coverage(walk_df, window_days),
        "residual_drift_p": residual_drift_p_value(walk_df, window_days),
        "n_observations": int(len(per_day)),
    }


def summary_report_weekly(walk_df: pd.DataFrame) -> dict[str, float | int]:
    """Convenience wrapper: 7-day trailing rolling-mean metrics.

    For Phase-1 daily-band failures driven by unmodeled latent-state noise
    (glycogen-water, gut contents, sodium ECF), the weekly track is where the
    population-default Hall model has real predictive power. Once Phase 2's
    glycogen-water latent state (foodlog-adu) lands the daily band should
    legitimately calibrate, and this helper can stay as a sanity check at a
    coarser timescale.
    """
    return summary_report(walk_df, window_days=7)
