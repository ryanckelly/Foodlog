import numpy as np
import pandas as pd
import pytest

from body_sim import evaluate


def _walk_df(predicted_means, observed):
    """Synthetic walk DataFrame: 10 samples per date, all at the mean."""
    rows = []
    for d, (pm, obs) in enumerate(zip(predicted_means, observed)):
        for s in range(10):
            rows.append(
                {
                    "date": pd.Timestamp("2026-05-01") + pd.Timedelta(days=d),
                    "sample": s,
                    "predicted_weight_kg": pm + np.random.normal(0, 0.3),
                    "observed_weight_kg": obs,
                }
            )
    return pd.DataFrame(rows)


def test_mae_on_perfect_predictions():
    df = _walk_df([80.0, 80.0, 80.0], [80.0, 80.0, 80.0])
    assert evaluate.mae(df) < 0.5  # noise from synthetic samples


def test_mae_on_off_predictions():
    df = _walk_df([80.0, 80.0, 80.0], [82.0, 82.0, 82.0])
    assert evaluate.mae(df) > 1.5


def test_calibration_coverage_high_when_predictions_good():
    df = _walk_df([80.0] * 30, [80.0 + np.random.normal(0, 0.2) for _ in range(30)])
    cov = evaluate.calibration_coverage(df)
    assert cov >= 0.8


def test_calibration_coverage_low_when_systematically_off():
    df = _walk_df([80.0] * 30, [85.0] * 30)
    cov = evaluate.calibration_coverage(df)
    assert cov < 0.2


def test_residual_drift_p_value():
    # No drift: residuals stationary around 0
    df = _walk_df([80.0] * 20, [80.0 + np.random.normal(0, 0.3) for _ in range(20)])
    p = evaluate.residual_drift_p_value(df)
    assert p > 0.05


def test_residual_drift_detects_monotonic():
    # Strong drift: predictions stay flat, observations rise linearly
    df = _walk_df([80.0] * 20, list(80.0 + np.linspace(0, 4, 20)))
    p = evaluate.residual_drift_p_value(df)
    assert p < 0.05


def test_summary_report_includes_all_metrics():
    df = _walk_df([80.0] * 10, [80.5] * 10)
    rep = evaluate.summary_report(df)
    for key in ("mae", "calibration_coverage", "residual_drift_p", "n_observations"):
        assert key in rep


def test_aggregate_to_per_period_window_1_matches_per_day():
    """window_days=1 must reproduce the pre-refactor _aggregate_to_per_day output."""
    df = _walk_df([80.0, 80.5, 81.0], [80.2, 80.4, 81.1])
    legacy = evaluate._aggregate_to_per_day(df).sort_values("date").reset_index(drop=True)
    new = evaluate._aggregate_to_per_period(df, window_days=1).sort_values("date").reset_index(drop=True)
    pd.testing.assert_frame_equal(legacy, new)


def test_mae_window_7_smooths_noise():
    """Weekly MAE on a flat-prediction series with high-frequency observation
    noise should be smaller than daily MAE — the rolling mean cancels noise."""
    rng = np.random.default_rng(0)
    predicted = [80.0] * 21
    observed = [80.0 + rng.normal(0, 1.0) for _ in range(21)]
    df = _walk_df(predicted, observed)
    daily_mae = evaluate.mae(df, window_days=1)
    weekly_mae = evaluate.mae(df, window_days=7)
    assert weekly_mae < daily_mae, (
        f"weekly_mae={weekly_mae:.3f} >= daily_mae={daily_mae:.3f}; "
        "smoothing did not reduce error against noisy observations"
    )


def test_summary_report_weekly_returns_same_keys():
    df = _walk_df([80.0] * 14, [80.5] * 14)
    daily = evaluate.summary_report(df)
    weekly = evaluate.summary_report_weekly(df)
    assert set(daily.keys()) == set(weekly.keys())
