"""The three required validation plots.

Imported by notebooks 03 and 04. All functions return a matplotlib Figure
so the notebook just needs to assign the return value to display it.
"""

from typing import Literal

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def _aggregate(walk_df: pd.DataFrame, metric: str) -> pd.DataFrame:
    pred_col = "body_fat_pct" if metric == "bf" else "predicted_weight_kg"
    obs_col = "observed_weight_kg"  # bf observed handled separately when available
    grouped = walk_df.groupby("date")
    out = pd.DataFrame(
        {
            "median": grouped[pred_col].median(),
            "lo": grouped[pred_col].quantile(0.025),
            "hi": grouped[pred_col].quantile(0.975),
            "observed": grouped[obs_col].first() if metric == "weight" else np.nan,
        }
    ).reset_index()
    return out


def trajectory_plot(
    walk_df: pd.DataFrame, metric: Literal["weight", "bf"] = "weight"
) -> plt.Figure:
    """Predicted trajectory with 95% band + observed dots overlaid."""
    agg = _aggregate(walk_df, metric)
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.fill_between(agg["date"], agg["lo"], agg["hi"], alpha=0.2, label="95% predictive band")
    ax.plot(agg["date"], agg["median"], label="Predicted median", linewidth=2)
    if metric == "weight":
        observed = agg.dropna(subset=["observed"])
        ax.scatter(observed["date"], observed["observed"], color="black", zorder=5, label="Observed")
        ax.set_ylabel("Body weight (kg)")
        ax.set_title("Predicted weight trajectory vs. observed weigh-ins")
    else:
        ax.set_ylabel("Body fat (%)")
        ax.set_title("Predicted body-fat trajectory")
    ax.set_xlabel("Date")
    ax.legend(loc="best")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    plt.close(fig)
    return fig


def residual_plot(walk_df: pd.DataFrame) -> plt.Figure:
    """Residual time-series: observed − predicted median, with ±0.5 kg refs."""
    agg = _aggregate(walk_df, "weight").dropna(subset=["observed"])
    residuals = agg["observed"] - agg["median"]
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.scatter(agg["date"], residuals, color="black")
    ax.axhline(0, color="gray", linewidth=1)
    ax.axhline(0.5, color="red", linestyle="--", linewidth=1, label="±0.5 kg scale noise")
    ax.axhline(-0.5, color="red", linestyle="--", linewidth=1)
    ax.set_xlabel("Date")
    ax.set_ylabel("Residual (observed − predicted), kg")
    ax.set_title("Residual time-series")
    ax.legend(loc="best")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    plt.close(fig)
    return fig


def three_panel_summary(walk_df: pd.DataFrame) -> plt.Figure:
    """Three required plots stacked vertically for the validation overview."""
    fig, axes = plt.subplots(3, 1, figsize=(10, 12))
    # Re-render each plot on the shared figure axes
    weight_agg = _aggregate(walk_df, "weight")
    axes[0].fill_between(weight_agg["date"], weight_agg["lo"], weight_agg["hi"], alpha=0.2)
    axes[0].plot(weight_agg["date"], weight_agg["median"], linewidth=2)
    obs = weight_agg.dropna(subset=["observed"])
    axes[0].scatter(obs["date"], obs["observed"], color="black", zorder=5)
    axes[0].set_ylabel("Weight (kg)")
    axes[0].set_title("Weight trajectory")

    bf_agg = _aggregate(walk_df, "bf")
    axes[1].fill_between(bf_agg["date"], bf_agg["lo"], bf_agg["hi"], alpha=0.2)
    axes[1].plot(bf_agg["date"], bf_agg["median"], linewidth=2)
    axes[1].set_ylabel("Body fat (%)")
    axes[1].set_title("Body fat trajectory")

    res = obs["observed"] - obs["median"]
    axes[2].scatter(obs["date"], res, color="black")
    axes[2].axhline(0, color="gray")
    axes[2].axhline(0.5, color="red", linestyle="--")
    axes[2].axhline(-0.5, color="red", linestyle="--")
    axes[2].set_ylabel("Residual (kg)")
    axes[2].set_title("Residual time-series")

    for ax in axes:
        ax.grid(alpha=0.3)
    fig.tight_layout()
    plt.close(fig)
    return fig
