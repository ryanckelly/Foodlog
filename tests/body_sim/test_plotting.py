import numpy as np
import pandas as pd
import pytest
import matplotlib

matplotlib.use("Agg")

from body_sim import plotting


def _walk_df(n_days: int = 30) -> pd.DataFrame:
    rows = []
    rng = np.random.default_rng(0)
    for d in range(n_days):
        for s in range(20):
            rows.append(
                {
                    "date": pd.Timestamp("2026-05-01") + pd.Timedelta(days=d),
                    "sample": s,
                    "predicted_weight_kg": 80 + rng.normal(0, 0.5),
                    "observed_weight_kg": 80.2 if d % 2 == 0 else np.nan,
                    "body_fat_pct": 22 + rng.normal(0, 0.3),
                }
            )
    return pd.DataFrame(rows)


def test_trajectory_plot_returns_figure():
    walk = _walk_df()
    fig = plotting.trajectory_plot(walk, metric="weight")
    assert fig is not None
    ax = fig.axes[0]
    assert "kg" in ax.get_ylabel().lower() or "weight" in ax.get_ylabel().lower()


def test_trajectory_plot_bf_metric():
    walk = _walk_df()
    fig = plotting.trajectory_plot(walk, metric="bf")
    assert fig is not None


def test_residual_plot_returns_figure():
    walk = _walk_df()
    fig = plotting.residual_plot(walk)
    assert fig is not None
    ax = fig.axes[0]
    # Reference lines at ±0.5 kg are drawn
    horizontal_lines = [line for line in ax.lines if line.get_linestyle() in ("--", ":")]
    assert len(horizontal_lines) >= 2


def test_three_panel_summary_returns_figure():
    walk = _walk_df()
    fig = plotting.three_panel_summary(walk)
    assert len(fig.axes) == 3


def test_residual_plot_weekly_overlay():
    """residual_plot(walk_df, weekly_overlay=True) returns a Figure with the
    weekly trace as an additional labeled line."""
    rng = np.random.default_rng(0)
    rows = []
    for d in range(21):
        for s in range(10):
            rows.append({
                "date": pd.Timestamp("2026-05-01") + pd.Timedelta(days=d),
                "sample": s,
                "predicted_weight_kg": 80.0 + rng.normal(0, 0.3),
                "observed_weight_kg": 80.0 + rng.normal(0, 1.0),
            })
    walk_df = pd.DataFrame(rows)
    fig = plotting.residual_plot(walk_df, weekly_overlay=True)
    ax = fig.axes[0]
    labels = [line.get_label() for line in ax.get_lines()]
    assert any("week" in label.lower() for label in labels), (
        f"weekly overlay line not found; got labels {labels}"
    )
