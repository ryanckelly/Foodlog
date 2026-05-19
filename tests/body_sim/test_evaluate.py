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
