# Weekly Rolling-Mean Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Beads:** `foodlog-1or` (phase-1) — run `bd show foodlog-1or` for the canonical bead.

**Goal:** Notebook 04 reports daily AND 7-day-trailing rolling-mean metrics side-by-side. Weekly calibration should reach the ≥80% threshold with the existing Phase-1 population-default model — confirming that the Phase-1 "calibration FAIL" was a timescale mismatch (band doesn't propagate glycogen-water / sodium ECF / gut-content noise that averages out over a week), not a model defect.

**Architecture:** Refactor `body_sim/evaluate.py` so the per-day aggregation helper accepts a `window_days` parameter. Each metric (`mae`, `calibration_coverage`, `residual_drift_p_value`, `summary_report`) gains the same parameter, defaulting to `1` (daily — the existing behavior). Add a thin `summary_report_weekly()` convenience. Update notebook 04 to print both reports. Add a weekly-smoothed overlay to `plotting.residual_plot`.

**Tech Stack:** Python 3.12, NumPy, pandas, SciPy (Kendall tau), matplotlib, pytest. No new dependencies.

**Smoothing convention:** 7-day **trailing** rolling mean (window=7, min_periods=1, closed='right'). Each day D's smoothed value is the mean of predictions / observations on [D-6, D]. Trailing (not centered) because it matches how live tracking would evaluate the model in real time — you can compute "today's 7-day mean" the day of, no peeking ahead.

---

## File structure

### Modified files

```
body_sim/evaluate.py                  add window_days parameter to existing fns; add summary_report_weekly
body_sim/plotting.py                  add weekly overlay to residual_plot
notebooks/04_hall_baseline.ipynb      print weekly metrics block; weekly overlay on residual plot
tests/body_sim/test_evaluate.py       new tests for window_days=7 behavior
tests/body_sim/test_plotting.py       new test for weekly overlay
body_sim/CLAUDE.md                    update "Phase 1 known limitations" — note weekly is canonical
```

### No new files

This is a refactor + extension. All work happens inside existing modules.

---

## Task 1: Refactor evaluate._aggregate_to_per_day → window-aware

**Files:**
- Modify: `body_sim/evaluate.py:12-22`
- Test: `tests/body_sim/test_evaluate.py`

- [ ] **Step 1: Write the failing test for window=1 backward compatibility**

Add to `tests/body_sim/test_evaluate.py`:

```python
def test_aggregate_to_per_period_window_1_matches_per_day():
    """window_days=1 must reproduce the pre-refactor _aggregate_to_per_day output."""
    df = _walk_df([80.0, 80.5, 81.0], [80.2, 80.4, 81.1])
    legacy = evaluate._aggregate_to_per_day(df).sort_values("date").reset_index(drop=True)
    new = evaluate._aggregate_to_per_period(df, window_days=1).sort_values("date").reset_index(drop=True)
    pd.testing.assert_frame_equal(legacy, new)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/body_sim/test_evaluate.py::test_aggregate_to_per_period_window_1_matches_per_day -v`

Expected: FAIL with `AttributeError: module 'body_sim.evaluate' has no attribute '_aggregate_to_per_period'`.

- [ ] **Step 3: Implement `_aggregate_to_per_period`, keeping `_aggregate_to_per_day` as a thin alias**

Replace lines 12-22 of `body_sim/evaluate.py` with:

```python
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/body_sim/test_evaluate.py::test_aggregate_to_per_period_window_1_matches_per_day -v`

Expected: PASS.

- [ ] **Step 5: Run the full evaluate test module to confirm no regression**

Run: `pytest tests/body_sim/test_evaluate.py -v`

Expected: all existing tests still PASS.

- [ ] **Step 6: Commit**

```bash
git add body_sim/evaluate.py tests/body_sim/test_evaluate.py
git commit -m "refactor(body_sim): make evaluate aggregation window-aware (foodlog-1or)"
```

---

## Task 2: Add window_days parameter to mae / calibration_coverage / residual_drift_p_value / summary_report

**Files:**
- Modify: `body_sim/evaluate.py:25-63`
- Test: `tests/body_sim/test_evaluate.py`

- [ ] **Step 1: Write failing test — weekly MAE smooths out a noisy observation**

Add to `tests/body_sim/test_evaluate.py`:

```python
def test_mae_window_7_smooths_noise():
    """Weekly MAE on a flat-prediction series with high-frequency observation
    noise should be smaller than daily MAE — the rolling mean cancels noise."""
    rng = np.random.default_rng(0)
    # 21 days, flat true weight 80, observations have sigma=1.0 daily noise
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/body_sim/test_evaluate.py::test_mae_window_7_smooths_noise tests/body_sim/test_evaluate.py::test_summary_report_weekly_returns_same_keys -v`

Expected: FAIL with TypeError on `window_days` kwarg and AttributeError on `summary_report_weekly`.

- [ ] **Step 3: Add window_days to each metric and add summary_report_weekly**

Replace `body_sim/evaluate.py:25-63` with:

```python
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
```

- [ ] **Step 4: Run the new tests**

Run: `pytest tests/body_sim/test_evaluate.py::test_mae_window_7_smooths_noise tests/body_sim/test_evaluate.py::test_summary_report_weekly_returns_same_keys -v`

Expected: PASS.

- [ ] **Step 5: Run the full evaluate test module**

Run: `pytest tests/body_sim/test_evaluate.py -v`

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add body_sim/evaluate.py tests/body_sim/test_evaluate.py
git commit -m "feat(body_sim): add window_days to evaluate metrics + summary_report_weekly (foodlog-1or)"
```

---

## Task 3: Add weekly overlay to plotting.residual_plot

**Files:**
- Modify: `body_sim/plotting.py:53-69`
- Test: `tests/body_sim/test_plotting.py`

- [ ] **Step 1: Write failing test — residual_plot accepts weekly_overlay kwarg**

Add to `tests/body_sim/test_plotting.py`:

```python
def test_residual_plot_weekly_overlay():
    """residual_plot(walk_df, weekly_overlay=True) returns a Figure with the
    weekly trace as an additional line."""
    # Build a small walk_df
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
    # The weekly overlay should appear as an additional Line2D in the axes
    labels = [line.get_label() for line in ax.get_lines()]
    assert any("week" in label.lower() for label in labels), (
        f"weekly overlay line not found; got labels {labels}"
    )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/body_sim/test_plotting.py::test_residual_plot_weekly_overlay -v`

Expected: FAIL with TypeError on unexpected kwarg `weekly_overlay`.

- [ ] **Step 3: Add weekly overlay to residual_plot**

Replace `body_sim/plotting.py:53-69` with:

```python
def residual_plot(
    walk_df: pd.DataFrame, weekly_overlay: bool = False
) -> plt.Figure:
    """Residual time-series: observed − predicted median, with ±0.5 kg refs.

    If ``weekly_overlay=True``, additionally plot the 7-day trailing
    rolling mean of the residuals. This is the trace that the Phase-1
    weekly calibration metric (summary_report_weekly) operates on — useful
    visual confirmation that the weekly signal stays inside the noise band
    even when the daily signal is busy.
    """
    agg = _aggregate(walk_df, "weight").dropna(subset=["observed"])
    residuals = agg["observed"] - agg["median"]
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.scatter(agg["date"], residuals, color="black", label="Daily residual")
    if weekly_overlay:
        weekly_resid = residuals.rolling(window=7, min_periods=1).mean()
        ax.plot(
            agg["date"], weekly_resid,
            color="tab:blue", linewidth=2, label="7-day trailing mean residual",
        )
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
```

- [ ] **Step 4: Run the test**

Run: `pytest tests/body_sim/test_plotting.py::test_residual_plot_weekly_overlay -v`

Expected: PASS.

- [ ] **Step 5: Run the full plotting test module**

Run: `pytest tests/body_sim/test_plotting.py -v`

Expected: all PASS (existing tests don't pass the new kwarg, so default `False` keeps them unchanged).

- [ ] **Step 6: Commit**

```bash
git add body_sim/plotting.py tests/body_sim/test_plotting.py
git commit -m "feat(body_sim): add 7-day rolling overlay to residual_plot (foodlog-1or)"
```

---

## Task 4: Update notebook 04 to print weekly metrics + weekly residual overlay

**Files:**
- Modify: `notebooks/04_hall_baseline.ipynb`

Notebook edits use the `jupyter nbconvert` round-trip from `body_sim/CLAUDE.md`. To edit cells programmatically:

- [ ] **Step 1: Locate the summary-metrics cell**

The current summary cell (id `b681c8ff`) prints daily metrics. We'll insert a new markdown header + weekly-metrics cell after it, before the plots section.

Run to see current cells:

```bash
.venv/bin/jupyter nbconvert --to script notebooks/04_hall_baseline.ipynb --stdout | head -60
```

Identify the line range of the daily summary cell and confirm the next cell is the "## The three required plots" markdown.

- [ ] **Step 2: Edit the daily-summary cell to wrap output in a labeled section**

Open the notebook in Jupyter (`.venv/bin/jupyter notebook notebooks/04_hall_baseline.ipynb` from `/opt/foodlog/`, or edit the JSON directly), and change cell `b681c8ff` to read:

```python
rep_daily = evaluate.summary_report(walk)
print("=== Daily metrics (single-day weigh-in vs. single-day prediction) ===")
print(f'MAE:                   {rep_daily["mae"]:.3f} kg')
print(f'95% calibration:       {100*rep_daily["calibration_coverage"]:.1f}% of observed weigh-ins inside band')
print(f'Residual drift p-value: {rep_daily["residual_drift_p"]:.3f}')
print(f'Observations used:      {rep_daily["n_observations"]}')

print()
print('Phase 1 passing thresholds (daily — known to be noise-limited at Phase 1):')
print(f'  MAE < 1.0 kg:                 {"PASS" if rep_daily["mae"] < 1.0 else "FAIL"}')
print(f'  Calibration >= 80%:           {"PASS" if rep_daily["calibration_coverage"] >= 0.8 else "FAIL"}')
print(f'  No drift (p > 0.1):           {"PASS" if rep_daily["residual_drift_p"] > 0.1 else "FAIL"}')
```

- [ ] **Step 3: Add a new markdown cell after the daily-summary cell**

Insert after cell `b681c8ff`:

```markdown
## Weekly metrics

The daily band only propagates Hall **parameter** uncertainty — it doesn't model the latent-state noise (glycogen-water ~0.5–1.5 kg/day, gut contents ~0.4–1 kg, sodium ECF ~0.3–0.8 kg) that dominates day-to-day weigh-in variation. That's tracked separately under `foodlog-adu` (Phase 2 PyMC latent state).

The 7-day trailing rolling mean averages most of that latent-state noise out on both sides of the comparison, so it's the metric that reflects whether the Hall energy-balance core actually has predictive power on the timescale it claims to. Calibration on this track is the canonical Phase-1 pass/fail.
```

- [ ] **Step 4: Add a new code cell with weekly metrics**

Insert immediately after the markdown cell from Step 3:

```python
rep_weekly = evaluate.summary_report_weekly(walk)
print("=== Weekly metrics (7-day trailing rolling mean) ===")
print(f'MAE:                   {rep_weekly["mae"]:.3f} kg')
print(f'95% calibration:       {100*rep_weekly["calibration_coverage"]:.1f}% of smoothed observations inside smoothed band')
print(f'Residual drift p-value: {rep_weekly["residual_drift_p"]:.3f}')
print(f'Observations used:      {rep_weekly["n_observations"]}')

print()
print('Phase 1 passing thresholds (weekly — canonical):')
print(f'  MAE < 1.0 kg:                 {"PASS" if rep_weekly["mae"] < 1.0 else "FAIL"}')
print(f'  Calibration >= 80%:           {"PASS" if rep_weekly["calibration_coverage"] >= 0.8 else "FAIL"}')
print(f'  No drift (p > 0.1):           {"PASS" if rep_weekly["residual_drift_p"] > 0.1 else "FAIL"}')
```

- [ ] **Step 5: Update the residual plot cell to pass `weekly_overlay=True`**

Change cell `d8db2929` from:

```python
fig = plotting.residual_plot(walk)
plt.show()
```

to:

```python
fig = plotting.residual_plot(walk, weekly_overlay=True)
plt.show()
```

- [ ] **Step 6: Re-execute the notebook end-to-end**

Run from `/opt/foodlog/`:

```bash
.venv/bin/jupyter nbconvert --to notebook --execute notebooks/04_hall_baseline.ipynb \
    --output 04_hall_baseline.ipynb --ExecutePreprocessor.timeout=600
```

Expected: notebook runs to completion. Inspect the new weekly-metrics cell output — calibration should now show **PASS** (or at minimum a substantial improvement over 43%).

- [ ] **Step 7: Sanity-check the result**

Open the notebook and confirm:
- Daily metrics block printed first
- Weekly markdown header + weekly metrics block follows
- Weekly calibration is ≥80% (the test that the timescale-mismatch hypothesis was right)
- Residual plot now has a blue 7-day-trailing-mean line overlaid on the black daily dots
- The blue line stays mostly inside the ±0.5 kg band

If weekly calibration is still <80%, do **not** silently push — that means either (a) the model has a real systematic offset that smoothing doesn't fix (intake under-reporting, RMR mis-set), or (b) there's a bug in the new code. Investigate before committing.

- [ ] **Step 8: Commit the notebook**

```bash
git add notebooks/04_hall_baseline.ipynb
git commit -m "feat(body_sim): notebook 04 — add weekly rolling-mean metrics block (foodlog-1or)"
```

---

## Task 5: Update body_sim/CLAUDE.md — note weekly is canonical

**Files:**
- Modify: `body_sim/CLAUDE.md` (section "Phase 1 known limitations")

- [ ] **Step 1: Edit the limitations section**

In `body_sim/CLAUDE.md`, find the "Phase 1 known limitations (open Phase 2 inputs)" section and replace the first bullet (`State-seeding doesn't back out glycogen-water...`) and the second bullet (`Parameter-prior bands are too narrow post-fix...`) with:

```markdown
- **Daily calibration is structurally noise-limited.** The 200-sample Monte Carlo band in `validation.forward_walk` propagates only Hall **parameter** uncertainty, not the dominant sources of daily weigh-in variance: glycogen-water (~0.5–1.5 kg/day), gut contents (~0.4–1 kg), sodium ECF (~0.3–0.8 kg). `validation._seed_state` further treats observed weight as fat+lean only, so day-1 predicted weight is systematically ~0.5–1.4 kg above the seed once glycogen + sodium water are added back in `BodyState.predicted_weight_kg`. As of `foodlog-1or` (2026-05-21), notebook 04 reports both daily AND 7-day-trailing-rolling-mean metrics — the **weekly track is the canonical Phase-1 calibration metric** because most of the latent-state noise averages out over a week of typical eating. Daily-track failure with weekly-track success is the expected Phase-1 result. Daily calibration is unblocked by `foodlog-adu` (glycogen-water as PyMC latent state, Phase 2).
- **Only ~12 weigh-ins (post-exclusion).** Phase 2 fitting kicks in once we have ~30 paired food+weight days.
```

- [ ] **Step 2: Commit**

```bash
git add body_sim/CLAUDE.md
git commit -m "docs(body_sim): note weekly is canonical Phase-1 calibration metric (foodlog-1or)"
```

---

## Task 6: Verification and close-out

- [ ] **Step 1: Run the full body_sim test suite**

Run: `pytest tests/body_sim/ -v`

Expected: all PASS.

- [ ] **Step 2: Confirm notebook 04 still executes clean**

Run: `.venv/bin/jupyter nbconvert --to notebook --execute notebooks/04_hall_baseline.ipynb --output 04_hall_baseline.ipynb --ExecutePreprocessor.timeout=600`

Expected: zero errors, weekly calibration PASS.

- [ ] **Step 3: Close the bead**

```bash
bd close foodlog-1or --reason="Weekly rolling-mean metrics + overlay landed; weekly calibration PASSes the >=80% threshold confirming the timescale-mismatch diagnosis from 2026-05-21."
```

- [ ] **Step 4: Session-close protocol**

Per `/opt/foodlog/CLAUDE.md` "Session Completion":

```bash
git pull --rebase
bd dolt push 2>&1 || true   # no-op if no dolt remote configured
git push
git status                    # MUST show "up to date with origin"
```

---

## Self-review notes

- **Scope:** all spec items in the foodlog-1or bead description are covered (daily + weekly metrics, weekly calibration target, smoothed weekly residual overlay).
- **No placeholders:** every code change is fully spelled out.
- **Type consistency:** `window_days: int` everywhere; `summary_report_weekly` returns the same dict shape as `summary_report`.
- **Closure:** Task 6 closes the bead and pushes per the session-completion protocol.
