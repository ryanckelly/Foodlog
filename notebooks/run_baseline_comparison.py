"""Compare validation metrics across four Keytel baseline methods.

Runs ``build_daily_rollup`` four times (naive + sleep + avg_desk + min_desk),
runs ``validation.forward_walk`` against each, prints a comparison table of
MAE / calibration / drift / observations / mean baseline_bpm / mean keytel_kcal.

Usage:
    .venv/bin/python notebooks/run_baseline_comparison.py
"""

from __future__ import annotations

import datetime
import os
import sys
from pathlib import Path


def _bootstrap() -> Path:
    repo = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(repo))
    env = repo / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())
    return repo


REPO = _bootstrap()

import pandas as pd  # noqa: E402

from body_sim import evaluate, pipeline, validation  # noqa: E402
from body_sim.config import DEFAULT_PROFILE  # noqa: E402
from foodlog.db.database import get_session_factory  # noqa: E402


METHODS = [
    "naive",
    "sleep",
    "avg_desk",
    "min_desk",
    "resting_states",
    "resting_states_p10",
    "evening_avg",
    "evening_min",
    "evening_resting_p10",
]


def main() -> None:
    end = datetime.date.today()
    start = end - datetime.timedelta(days=60)

    rows: list[dict] = []
    for method in METHODS:
        session = get_session_factory()()
        df = pipeline.build_daily_rollup(
            session=session,
            start=start,
            end=end,
            weight_kg_fallback=80.0,
            age=DEFAULT_PROFILE["age"],
            sex=DEFAULT_PROFILE["sex"],
            keytel_baseline_method=method,
        )
        walk = validation.forward_walk(
            df, step_days=7, profile=DEFAULT_PROFILE, sample_n=200, seed=42
        )
        rep = evaluate.summary_report(walk)
        rows.append(
            {
                "method": method,
                "mean_baseline_bpm": float(df["keytel_baseline_bpm"].mean()),
                "mean_keytel_kcal": float(df["ee_hr_keytel_kcal"].mean()),
                "mae_kg": rep["mae"],
                "calibration": rep["calibration_coverage"],
                "drift_p": rep["residual_drift_p"],
                "n_obs": rep["n_observations"],
            }
        )

    out = pd.DataFrame(rows).set_index("method")
    pd.set_option("display.float_format", lambda v: f"{v:.3f}")
    print(out.to_string())
    print()
    print("Phase 1 thresholds: MAE < 1.0 kg, calibration >= 80%, drift p > 0.1")
    print()
    for m, row in out.iterrows():
        status = []
        status.append(f"MAE {'PASS' if row['mae_kg'] < 1.0 else 'FAIL'}")
        status.append(f"cal {'PASS' if row['calibration'] >= 0.8 else 'FAIL'}")
        status.append(f"drift {'PASS' if row['drift_p'] > 0.1 else 'FAIL'}")
        print(f"  {m:10s} → {' · '.join(status)}")


if __name__ == "__main__":
    main()
