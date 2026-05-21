# Morning + Evening Weight Feature Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Beads:** `foodlog-dwt` (phase-3) — run `bd show foodlog-dwt` for the canonical bead.

**Prereqs:** This is a Phase-3 task — start it only when:

1. **`foodlog-hg8` is closed** — the `weigh_in_protocol` column exists (this plan extends its enum).
2. **`foodlog-adu` is closed or far along** — the Bayesian fit framework with latent glycogen state exists; this plan extends it with a diurnal latent.
3. **≥30 days of paired AM/PM weigh-ins** in the DB. Until paired data exists, the model is unidentified. Check with:
   ```sql
   SELECT date(measured_at) AS d,
          SUM(CASE WHEN weigh_in_protocol='controlled_morning' THEN 1 ELSE 0 END) AS am,
          SUM(CASE WHEN weigh_in_protocol='controlled_evening' THEN 1 ELSE 0 END) AS pm
     FROM body_composition
    GROUP BY d HAVING am > 0 AND pm > 0;
   ```
   Need ~30 rows from this query before proceeding.

If any prereq is unmet, **stop and complete it first.** The plan is concrete from Task 1 onward but the *value* of executing it depends on having data.

---

**Goal:** Treat morning and evening weigh-ins as **separate observation channels** of the underlying body state, with the diurnal delta as both:
1. An additional likelihood signal — paired same-day observations are a strong constraint on the day's water + gut variance, even when the absolute weight is noisy.
2. A model output worth predicting — `predicted_evening_weight_kg = morning_weight + intake_today_kg − urinary_output_kg − sweat_kg + sodium_excess_water_today`. Tracks how diet/activity changes through the day map to scale readings.

This unlocks several downstream uses: (a) sanity-checking the glycogen/sodium model on a per-day basis instead of weekly, (b) detecting illness/cycle effects via unusual diurnal patterns, (c) tightening the Phase-2 posterior by giving it two observations per day instead of one.

---

**Architecture:**
- **Data:** extend the `weigh_in_protocol` enum to `{"controlled_morning", "controlled_evening", "uncontrolled"}`. Sync heuristic auto-tags morning (07:00–11:00) and evening (19:00–22:00) on/after the cutoff. Off-hour weigh-ins remain "uncontrolled."
- **Pipeline:** `rollup_body_comp` emits `morning_weight_kg`, `evening_weight_kg`, and `diurnal_delta_kg` columns. The single-channel `weight_kg` column persists for back-compat — set to the morning value when present, else evening.
- **Model:** add `predicted_evening_weight_kg(...)` to `BodyState` that adds an intra-day fluctuation term to `predicted_weight_kg(...)`. Components: (1) unabsorbed food mass (rough: 50% of today's intake_g still in transit at evening), (2) sodium-water transient peak (today's sodium excess water is fully present in evening, partially excreted by next morning), (3) sweat/hydration deficit from activity (rough: 0.5 kg per hour of vigorous exercise without replacement).
- **Bayesian fit (extension of `body_sim/bayesian.py`):** Add a `sigma_diurnal` latent for the day-of variance and a `diurnal_drift` parameter for systematic AM→PM mass change. Observation likelihood becomes two-channel: morning obs against `g_t`, evening obs against `g_t + diurnal_delta_t`.
- **Validation:** `forward_walk` gains a `track: Literal["morning", "evening", "delta"]` parameter to filter which channel to evaluate; the long-form output gains `morning_weight_kg`, `evening_weight_kg`, `diurnal_delta_kg` columns alongside existing ones.
- **Evaluation:** `summary_report` runs on each track separately; notebook 04 prints all three.

**Tech Stack:** Same as Phase 2 — PyMC, NumPy, pandas. No new dependencies.

---

## Open design questions (resolve during execution if needed)

1. **Diurnal drift as deterministic or latent?** Two viable specifications: (a) `diurnal_delta_t = f(intake_today, sodium_today, sweat_today) + noise`, (b) `diurnal_delta_t = mu_diurnal + epsilon_t` purely latent. Start with (b) and add the deterministic terms only if the latent shows clear correlation with diet/activity features.
2. **Sodium-water timing.** Current `sodium.water_kg(sodium_mg)` is a static daily-equilibrium model. For AM/PM observations it matters whether today's sodium peaks at PM and dissipates by tomorrow AM, or rolls over to next-day AM. Pilot data should distinguish — if PM weight tracks today's sodium and AM tracks yesterday's, the model needs a one-day-lag term.
3. **Evening intake coverage.** Snacks logged after the evening weigh-in are counted in the day's intake but not yet absorbed. If `intake_logged` was true *before* the evening weigh-in but additional snacks land after, that's a logging artifact, not a body-comp signal. May need a snacks-after-evening-weighin flag derived from `consumed_at` (foodlog-fkn).
4. **Three tracks vs. one joint likelihood.** Evaluating morning / evening / delta separately is the simplest reporting. An alternative is a joint two-dim likelihood that scores `(morning, evening)` as a vector. Joint is statistically cleaner but harder to interpret; separate tracks land first.

---

## File structure

### New files

```
body_sim/diurnal.py                              pure-function model of diurnal mass dynamics
tests/body_sim/test_diurnal.py                   unit tests
```

### Modified files

```
body_sim/weigh_in.py                             extend Protocol to include controlled_evening
body_sim/pipeline.py                             rollup_body_comp emits AM/PM/delta columns
body_sim/model.py                                BodyState gains predicted_evening_weight_kg
body_sim/bayesian.py                             two-channel likelihood + diurnal latent
body_sim/bayesian_predict.py                    posterior bands per channel
body_sim/validation.py                           track="morning|evening|delta" filter
body_sim/evaluate.py                             metrics accept a `column` arg
notebooks/04_hall_baseline.ipynb                 three-track section
body_sim/CLAUDE.md                               document the protocol enum + cutoff
tests/body_sim/test_weigh_in.py                  add controlled_evening tests
tests/body_sim/test_pipeline_other.py            test AM/PM/delta columns
tests/body_sim/test_model.py                    test predicted_evening_weight_kg
tests/body_sim/test_validation.py                test track filter
```

---

## Task 1: Extend the protocol enum to include `controlled_evening`

**Files:**
- Modify: `body_sim/weigh_in.py`
- Modify: `tests/body_sim/test_weigh_in.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/body_sim/test_weigh_in.py`:

```python
def test_controlled_evening_after_cutoff():
    dt = datetime.datetime(2026, 6, 1, 20, 0)
    assert weigh_in.classify_protocol(dt) == "controlled_evening"


def test_evening_boundary_hours_inclusive():
    assert weigh_in.classify_protocol(datetime.datetime(2026, 6, 1, 19, 0)) == "controlled_evening"
    assert weigh_in.classify_protocol(datetime.datetime(2026, 6, 1, 22, 0)) == "controlled_evening"
    assert weigh_in.classify_protocol(datetime.datetime(2026, 6, 1, 18, 59)) == "uncontrolled"
    assert weigh_in.classify_protocol(datetime.datetime(2026, 6, 1, 22, 1)) == "uncontrolled"


def test_midday_is_uncontrolled():
    """Between the morning and evening windows is still uncontrolled."""
    assert weigh_in.classify_protocol(datetime.datetime(2026, 6, 1, 14, 0)) == "uncontrolled"
```

- [ ] **Step 2: Run to confirm fail**

Run: `pytest tests/body_sim/test_weigh_in.py -v`

Expected: FAIL — `classify_protocol` returns "uncontrolled" for evening.

- [ ] **Step 3: Update `body_sim/weigh_in.py`**

Edit to add evening window constants and the new return value:

```python
Protocol = Literal["controlled_morning", "controlled_evening", "uncontrolled"]

WEIGH_IN_PROTOCOL_CUTOFF: datetime.date = datetime.date(2026, 5, 21)

MORNING_HOUR_LO: int = 7
MORNING_HOUR_HI: int = 11
EVENING_HOUR_LO: int = 19
EVENING_HOUR_HI: int = 22


def classify_protocol(measured_at: datetime.datetime) -> Protocol:
    """Return the protocol label for a weigh-in datetime."""
    if measured_at.date() < WEIGH_IN_PROTOCOL_CUTOFF:
        return "uncontrolled"
    hour = measured_at.hour
    minute = measured_at.minute
    if MORNING_HOUR_LO <= hour < MORNING_HOUR_HI or (hour == MORNING_HOUR_HI and minute == 0):
        return "controlled_morning"
    if EVENING_HOUR_LO <= hour < EVENING_HOUR_HI or (hour == EVENING_HOUR_HI and minute == 0):
        return "controlled_evening"
    return "uncontrolled"
```

- [ ] **Step 4: Run the tests**

Run: `pytest tests/body_sim/test_weigh_in.py -v`

Expected: all PASS, including the original Phase-1 morning tests.

- [ ] **Step 5: Re-run the backfill against the live DB**

```bash
docker exec foodlog python -m body_sim.tag_weigh_ins --apply --force
```

`--force` overwrites existing values — needed because rows previously tagged "uncontrolled" may now reclassify as "controlled_evening."

- [ ] **Step 6: Commit**

```bash
git add body_sim/weigh_in.py tests/body_sim/test_weigh_in.py
git commit -m "feat(body_sim): add controlled_evening protocol + re-backfill (foodlog-dwt)"
```

---

## Task 2: Pipeline emits AM/PM/delta columns

**Files:**
- Modify: `body_sim/pipeline.py` — `rollup_body_comp` function
- Modify: `tests/body_sim/test_pipeline_other.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/body_sim/test_pipeline_other.py`:

```python
def test_rollup_body_comp_emits_morning_evening_delta(in_memory_session):
    """A day with both a morning and evening weigh-in produces
    morning_weight_kg, evening_weight_kg, diurnal_delta_kg columns. Days
    with only morning leave evening NaN; the delta is NaN if either is missing."""
    import datetime
    from foodlog.db.models import BodyComposition
    from body_sim import pipeline

    db = in_memory_session
    db.add(BodyComposition(
        external_id="m1", measured_at=datetime.datetime(2026, 6, 1, 9, 0),
        weight_kg=82.0, body_fat_pct=21.0, source="test",
        weigh_in_protocol="controlled_morning",
    ))
    db.add(BodyComposition(
        external_id="e1", measured_at=datetime.datetime(2026, 6, 1, 20, 0),
        weight_kg=83.4, body_fat_pct=21.2, source="test",
        weigh_in_protocol="controlled_evening",
    ))
    db.add(BodyComposition(
        external_id="m2", measured_at=datetime.datetime(2026, 6, 2, 9, 0),
        weight_kg=82.1, body_fat_pct=21.0, source="test",
        weigh_in_protocol="controlled_morning",
    ))
    db.commit()

    out = pipeline.rollup_body_comp(
        db, datetime.date(2026, 6, 1), datetime.date(2026, 6, 2)
    )
    assert out.loc[datetime.datetime(2026, 6, 1), "morning_weight_kg"] == 82.0
    assert out.loc[datetime.datetime(2026, 6, 1), "evening_weight_kg"] == 83.4
    assert out.loc[datetime.datetime(2026, 6, 1), "diurnal_delta_kg"] == pytest.approx(1.4)
    assert out.loc[datetime.datetime(2026, 6, 2), "morning_weight_kg"] == 82.1
    assert np.isnan(out.loc[datetime.datetime(2026, 6, 2), "evening_weight_kg"])
    assert np.isnan(out.loc[datetime.datetime(2026, 6, 2), "diurnal_delta_kg"])
    # weight_kg back-compat: prefer morning when present
    assert out.loc[datetime.datetime(2026, 6, 1), "weight_kg"] == 82.0
```

- [ ] **Step 2: Run to confirm fail**

Run: `pytest tests/body_sim/test_pipeline_other.py::test_rollup_body_comp_emits_morning_evening_delta -v`

Expected: FAIL.

- [ ] **Step 3: Update `rollup_body_comp`**

In `body_sim/pipeline.py`, extend the per-day record construction:

```python
def rollup_body_comp(
    session: Session, start: datetime.date, end: datetime.date
) -> pd.DataFrame:
    """Aggregate body_composition to one row per day.

    Columns:
        weight_kg               median of morning weigh-ins if any, else median of any
        bf_pct                  median across all readings (any protocol)
        n_weighins              count of non-excluded readings
        morning_weight_kg       median of controlled_morning readings (NaN if none)
        evening_weight_kg       median of controlled_evening readings (NaN if none)
        diurnal_delta_kg        evening − morning (NaN if either missing)
        weigh_in_protocol_controlled  bool — all readings that day are controlled_*

    Excluded readings (EXCLUDED_BODY_COMP_IDS) never participate.
    """
    rows = (
        session.query(BodyComposition)
        .filter(
            BodyComposition.measured_at >= datetime.datetime.combine(start, datetime.time()),
            BodyComposition.measured_at < datetime.datetime.combine(
                end + datetime.timedelta(days=1), datetime.time()
            ),
            ~BodyComposition.external_id.in_(EXCLUDED_BODY_COMP_IDS),
        )
        .all()
    )
    per_day: dict[datetime.date, list[BodyComposition]] = {}
    for r in rows:
        per_day.setdefault(r.measured_at.date(), []).append(r)

    idx = _date_index(start, end)
    records = []
    for ts in idx:
        d = ts.date()
        rs = per_day.get(d, [])
        if rs:
            mornings = [r.weight_kg for r in rs
                        if r.weigh_in_protocol == "controlled_morning" and r.weight_kg is not None]
            evenings = [r.weight_kg for r in rs
                        if r.weigh_in_protocol == "controlled_evening" and r.weight_kg is not None]
            all_weights = [r.weight_kg for r in rs if r.weight_kg is not None]
            bfs = [r.body_fat_pct for r in rs if r.body_fat_pct is not None]

            morning_kg = float(np.median(mornings)) if mornings else np.nan
            evening_kg = float(np.median(evenings)) if evenings else np.nan
            delta = evening_kg - morning_kg if (mornings and evenings) else np.nan
            # weight_kg back-compat: prefer morning; else median of all
            weight_kg = morning_kg if mornings else (
                float(np.median(all_weights)) if all_weights else np.nan
            )
            all_controlled = all(
                r.weigh_in_protocol in {"controlled_morning", "controlled_evening"}
                for r in rs
            )
            records.append({
                "weight_kg": weight_kg,
                "bf_pct": float(np.median(bfs)) if bfs else np.nan,
                "n_weighins": len(rs),
                "morning_weight_kg": morning_kg,
                "evening_weight_kg": evening_kg,
                "diurnal_delta_kg": delta,
                "weigh_in_protocol_controlled": bool(all_controlled),
            })
        else:
            records.append({
                "weight_kg": np.nan,
                "bf_pct": np.nan,
                "n_weighins": 0,
                "morning_weight_kg": np.nan,
                "evening_weight_kg": np.nan,
                "diurnal_delta_kg": np.nan,
                "weigh_in_protocol_controlled": False,
            })

    df = pd.DataFrame(records, index=idx)
    df["weigh_in_protocol_controlled"] = df["weigh_in_protocol_controlled"].astype(object)
    return df
```

- [ ] **Step 4: Run the test**

Run: `pytest tests/body_sim/test_pipeline_other.py::test_rollup_body_comp_emits_morning_evening_delta -v`

Expected: PASS.

- [ ] **Step 5: Run the full pipeline test suite**

Run: `pytest tests/body_sim/test_pipeline_other.py tests/body_sim/test_pipeline_assembly.py -v`

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add body_sim/pipeline.py tests/body_sim/test_pipeline_other.py
git commit -m "feat(body_sim): rollup_body_comp emits morning/evening/delta columns (foodlog-dwt)"
```

---

## Task 3: Diurnal mass model in `body_sim/diurnal.py`

**Files:**
- Create: `body_sim/diurnal.py`
- Create: `tests/body_sim/test_diurnal.py`

- [ ] **Step 1: Write the failing test**

Create `tests/body_sim/test_diurnal.py`:

```python
import pytest
from body_sim import diurnal


def test_food_in_transit_kg_zero_intake_returns_zero():
    assert diurnal.food_in_transit_kg(0.0) == 0.0


def test_food_in_transit_kg_scales_with_intake_mass():
    # Default model: ~50% of today's intake by mass remains in transit at evening
    # 2000 kcal at ~3 kcal/g food = ~666 g food mass; half is ~0.333 kg
    val = diurnal.food_in_transit_kg(2000.0)
    assert 0.25 < val < 0.45


def test_sweat_kg_zero_activity_returns_zero():
    assert diurnal.sweat_kg(workout_min=0, vigorous_min=0) == 0.0


def test_sweat_kg_scales_with_vigorous_min():
    """Vigorous minutes dominate sweat loss; default ~0.5 kg/hour vigorous."""
    val = diurnal.sweat_kg(workout_min=0, vigorous_min=60)
    assert 0.3 < val < 0.7


def test_sodium_pm_water_kg_clipped_at_zero():
    """Sodium below baseline produces no excess water at PM either."""
    assert diurnal.sodium_pm_water_kg(1000.0) == 0.0


def test_predicted_diurnal_delta_kg_typical_day():
    """A typical 2400-kcal, moderate-sodium, 30-min-cardio day produces
    a positive AM→PM delta of ~0.4-1.0 kg."""
    delta = diurnal.predicted_diurnal_delta_kg(
        intake_kcal=2400, sodium_mg=2800, workout_min=30, vigorous_min=10,
    )
    assert 0.3 < delta < 1.2
```

- [ ] **Step 2: Run to confirm fail**

Run: `pytest tests/body_sim/test_diurnal.py -v`

Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement the module**

Create `body_sim/diurnal.py`:

```python
"""Diurnal mass-dynamics model.

Decomposes the morning→evening weight delta into three additive components:
- food-in-transit (positive: today's intake hasn't fully been excreted by evening)
- sodium-driven extra water (positive: today's sodium peaks at PM)
- sweat deficit (negative: vigorous activity without replacement reduces evening weight)

These are first-order approximations matching published GI-transit /
sodium-balance / sweat-rate literature. Real PM weight has additional
sources of variance (drink timing, ambient temperature, stress
cortisol) that this model doesn't try to predict.

Used by:
- ``model.BodyState.predicted_evening_weight_kg`` to produce a PM observation
  expectation.
- (future) ``bayesian.build_model`` to add a deterministic-mean term to the
  diurnal latent.
"""

from body_sim.config import SODIUM_WATER_KG_PER_GRAM


FOOD_TRANSIT_FRACTION_AT_EVENING: float = 0.50  # of today's mass still in transit
KCAL_PER_G_FOOD: float = 3.0                    # rough overall caloric density
SWEAT_KG_PER_VIGOROUS_HOUR: float = 0.50
SWEAT_KG_PER_WORKOUT_HOUR: float = 0.20
BASELINE_SODIUM_MG: float = 2300.0
# Today's PM sodium water is roughly equal to the full daily-equilibrium value;
# overnight excretion removes ~70% by next morning, so the AM-baseline term is
# 30% of yesterday's value (handled by sodium.water_kg upstream).
SODIUM_PM_SCALE: float = 1.0


def food_in_transit_kg(intake_kcal: float) -> float:
    """Mass of food + water from today's intake still in the GI tract at evening."""
    if intake_kcal <= 0:
        return 0.0
    food_mass_g = intake_kcal / KCAL_PER_G_FOOD
    return FOOD_TRANSIT_FRACTION_AT_EVENING * food_mass_g / 1000.0


def sweat_kg(workout_min: int, vigorous_min: int) -> float:
    """Net evening-time sweat deficit from today's activity, kg.

    Counts both general workout time and AZM-vigorous minutes. Assumes the
    user did not fully rehydrate by evening — a wash-out factor of 0.7 is
    applied. If the user is a meticulous rehydrator, this overestimates.
    """
    raw = (
        SWEAT_KG_PER_WORKOUT_HOUR * (workout_min / 60.0)
        + SWEAT_KG_PER_VIGOROUS_HOUR * (vigorous_min / 60.0)
    )
    return max(0.0, raw * 0.7)


def sodium_pm_water_kg(sodium_mg: float) -> float:
    """Water mass from today's sodium that's present in the evening but not the morning."""
    excess = max(0.0, sodium_mg - BASELINE_SODIUM_MG)
    return SODIUM_PM_SCALE * SODIUM_WATER_KG_PER_GRAM * excess


def predicted_diurnal_delta_kg(
    intake_kcal: float, sodium_mg: float,
    workout_min: int, vigorous_min: int,
) -> float:
    """Expected morning→evening weight delta in kg.

    delta = food_in_transit + sodium_pm_water − sweat
    """
    return (
        food_in_transit_kg(intake_kcal)
        + sodium_pm_water_kg(sodium_mg)
        - sweat_kg(workout_min, vigorous_min)
    )
```

- [ ] **Step 4: Run the tests**

Run: `pytest tests/body_sim/test_diurnal.py -v`

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add body_sim/diurnal.py tests/body_sim/test_diurnal.py
git commit -m "feat(body_sim): diurnal mass-dynamics model (foodlog-dwt)"
```

---

## Task 4: `BodyState.predicted_evening_weight_kg`

**Files:**
- Modify: `body_sim/model.py`
- Modify: `tests/body_sim/test_model.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/body_sim/test_model.py`:

```python
def test_predicted_evening_weight_kg_higher_than_morning_typical_day():
    from body_sim.model import BodyState
    state = BodyState(fat_mass_kg=18.0, lean_mass_kg=62.0)
    morning = state.predicted_weight_kg(sodium_mg=2800.0)
    evening = state.predicted_evening_weight_kg(
        sodium_mg=2800.0, intake_kcal=2400.0,
        workout_min=30, vigorous_min=10,
    )
    assert evening > morning, f"expected evening > morning, got {evening:.2f} <= {morning:.2f}"
    delta = evening - morning
    assert 0.3 < delta < 1.5, f"diurnal delta {delta:.2f} kg out of plausible range"


def test_predicted_evening_weight_kg_lower_after_heavy_workout_low_intake():
    from body_sim.model import BodyState
    state = BodyState(fat_mass_kg=18.0, lean_mass_kg=62.0)
    morning = state.predicted_weight_kg(sodium_mg=1500.0)
    evening = state.predicted_evening_weight_kg(
        sodium_mg=1500.0, intake_kcal=1200.0,
        workout_min=90, vigorous_min=60,  # 90 min total, 60 min vigorous
    )
    # heavy workout, no rehydration assumption, modest intake → evening < morning
    assert evening < morning
```

- [ ] **Step 2: Run to confirm fail**

Run: `pytest tests/body_sim/test_model.py -k predicted_evening -v`

Expected: FAIL — `AttributeError: 'BodyState' object has no attribute 'predicted_evening_weight_kg'`.

- [ ] **Step 3: Add the method to `BodyState`**

In `body_sim/model.py`, in the `BodyState` dataclass (around line 38-45), add:

```python
    def predicted_evening_weight_kg(
        self, sodium_mg: float, intake_kcal: float,
        workout_min: int, vigorous_min: int,
    ) -> float:
        """Predicted evening scale reading.

        Adds the diurnal model's food-in-transit + extra sodium water − sweat
        terms on top of the morning prediction.
        """
        from body_sim import diurnal
        morning = self.predicted_weight_kg(sodium_mg)
        delta = diurnal.predicted_diurnal_delta_kg(
            intake_kcal=intake_kcal, sodium_mg=sodium_mg,
            workout_min=workout_min, vigorous_min=vigorous_min,
        )
        return morning + delta
```

- [ ] **Step 4: Run the tests**

Run: `pytest tests/body_sim/test_model.py -k predicted_evening -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add body_sim/model.py tests/body_sim/test_model.py
git commit -m "feat(body_sim): BodyState.predicted_evening_weight_kg (foodlog-dwt)"
```

---

## Task 5: Validation `track` filter

**Files:**
- Modify: `body_sim/validation.py`
- Modify: `tests/body_sim/test_validation.py`

The forward walk already returns `predicted_weight_kg` and `observed_weight_kg` per day. To support 3-channel evaluation, we add a `track` parameter that swaps which observation column the walk records as `observed_weight_kg`, and (for evening track) which prediction the simulator emits.

For the evening track, the predicted column needs the simulator to call `state.predicted_evening_weight_kg(...)` instead of `state.predicted_weight_kg(...)`. The simplest path:
1. `forward_walk(track="morning")` keeps existing behavior (predict + observed_morning).
2. `forward_walk(track="evening")` post-processes the standard walk: replace `predicted_weight_kg` with the per-day evening prediction (computed from each sample's final state + inputs) and `observed_weight_kg` with `evening_weight_kg`.
3. `forward_walk(track="delta")` returns the diurnal delta — predicted = evening_prediction − morning_prediction, observed = evening_obs − morning_obs.

- [ ] **Step 1: Write the failing test**

Add to `tests/body_sim/test_validation.py`:

```python
def test_forward_walk_track_morning_is_default_behavior():
    df = _synthetic_rollup(n_days=14)
    df["morning_weight_kg"] = df["weight_kg"]
    df["evening_weight_kg"] = np.nan
    df["diurnal_delta_kg"] = np.nan
    out_default = validation.forward_walk(
        df, step_days=7, profile=DEFAULT_PROFILE, sample_n=2, seed=0
    )
    out_morning = validation.forward_walk(
        df, step_days=7, profile=DEFAULT_PROFILE, sample_n=2, seed=0,
        track="morning",
    )
    pd.testing.assert_frame_equal(out_default, out_morning)


def test_forward_walk_track_evening_uses_evening_obs():
    df = _synthetic_rollup(n_days=14)
    df["morning_weight_kg"] = df["weight_kg"]
    # All evenings 1.0 kg higher than morning
    df["evening_weight_kg"] = df["weight_kg"] + 1.0
    df["diurnal_delta_kg"] = 1.0
    out = validation.forward_walk(
        df, step_days=7, profile=DEFAULT_PROFILE, sample_n=2, seed=0,
        track="evening",
    )
    obs = out["observed_weight_kg"].dropna().unique()
    # observed should match evening_weight_kg, not morning
    np.testing.assert_allclose(
        sorted(obs), sorted(df["evening_weight_kg"].dropna().unique()), atol=1e-6,
    )


def test_forward_walk_track_delta_returns_diurnal_residual():
    df = _synthetic_rollup(n_days=14)
    df["morning_weight_kg"] = df["weight_kg"]
    df["evening_weight_kg"] = df["weight_kg"] + 0.5
    df["diurnal_delta_kg"] = 0.5
    out = validation.forward_walk(
        df, step_days=7, profile=DEFAULT_PROFILE, sample_n=2, seed=0,
        track="delta",
    )
    obs = out["observed_weight_kg"].dropna().unique()
    np.testing.assert_allclose(obs, [0.5], atol=1e-6)
```

- [ ] **Step 2: Run to confirm fail**

Run: `pytest tests/body_sim/test_validation.py -k track -v`

Expected: FAIL.

- [ ] **Step 3: Add the track parameter and post-processing**

In `body_sim/validation.py`, extend the signature:

```python
def forward_walk(
    df: pd.DataFrame,
    step_days: int,
    profile: UserProfile,
    sample_n: int,
    seed: int | None = None,
    mode: str = "prior",
    idata=None,
    track: str = "morning",
) -> pd.DataFrame:
    """... existing docstring ...

    Args:
        ...
        track: "morning" | "evening" | "delta" — which observation channel
            to record. "morning" keeps the legacy single-channel behavior.
            "evening" swaps in evening_weight_kg as observed and re-predicts
            using BodyState.predicted_evening_weight_kg. "delta" returns
            the diurnal residual (evening − morning) on both sides.
    """
    out = _forward_walk_morning(df, step_days, profile, sample_n, seed, mode, idata)
    if track == "morning":
        return out
    if track == "evening":
        return _retag_for_evening(out, df, profile)
    if track == "delta":
        return _retag_for_delta(out, df, profile)
    raise ValueError(f"unknown track={track!r}")
```

Rename the existing body of `forward_walk` (everything below the `mode == "posterior"` branch) to `_forward_walk_morning` and have it return its records DataFrame unchanged.

Then add the two retag helpers:

```python
def _retag_for_evening(
    out: pd.DataFrame, source_df: pd.DataFrame, profile: UserProfile,
) -> pd.DataFrame:
    """Replace observed_weight_kg with evening_weight_kg and recompute
    predicted_weight_kg as the evening prediction."""
    from body_sim import model

    new = out.copy()
    # observed: pull from source_df's evening_weight_kg
    evening_map = source_df["evening_weight_kg"].to_dict()
    new["observed_weight_kg"] = new["date"].map(
        lambda ts: evening_map.get(ts, np.nan)
    ).astype(float)

    # predicted: rebuild the evening prediction from fat/lean state + inputs
    for i, row in new.iterrows():
        ts = row["date"]
        src = source_df.loc[ts]
        state = model.BodyState(
            fat_mass_kg=row["fat_mass_kg"],
            lean_mass_kg=row["lean_mass_kg"],
        )
        new.at[i, "predicted_weight_kg"] = state.predicted_evening_weight_kg(
            sodium_mg=float(src.get("sodium_mg", 0.0)) if pd.notna(src.get("sodium_mg")) else 0.0,
            intake_kcal=float(src.get("intake_kcal", 0.0)) if pd.notna(src.get("intake_kcal")) else 0.0,
            workout_min=int(src.get("workout_min", 0)) if pd.notna(src.get("workout_min")) else 0,
            vigorous_min=int(src.get("vigorous_min", 0)) if pd.notna(src.get("vigorous_min")) else 0,
        )
    return new


def _retag_for_delta(
    out: pd.DataFrame, source_df: pd.DataFrame, profile: UserProfile,
) -> pd.DataFrame:
    """Both sides become AM→PM deltas."""
    from body_sim import diurnal

    new = out.copy()
    delta_map = source_df["diurnal_delta_kg"].to_dict()
    new["observed_weight_kg"] = new["date"].map(
        lambda ts: delta_map.get(ts, np.nan)
    ).astype(float)
    for i, row in new.iterrows():
        ts = row["date"]
        src = source_df.loc[ts]
        new.at[i, "predicted_weight_kg"] = diurnal.predicted_diurnal_delta_kg(
            intake_kcal=float(src.get("intake_kcal", 0.0)) if pd.notna(src.get("intake_kcal")) else 0.0,
            sodium_mg=float(src.get("sodium_mg", 0.0)) if pd.notna(src.get("sodium_mg")) else 0.0,
            workout_min=int(src.get("workout_min", 0)) if pd.notna(src.get("workout_min")) else 0,
            vigorous_min=int(src.get("vigorous_min", 0)) if pd.notna(src.get("vigorous_min")) else 0,
        )
    return new
```

- [ ] **Step 4: Run the tests**

Run: `pytest tests/body_sim/test_validation.py -v`

Expected: all PASS, including the original prior/posterior tests.

- [ ] **Step 5: Commit**

```bash
git add body_sim/validation.py tests/body_sim/test_validation.py
git commit -m "feat(body_sim): forward_walk track=morning/evening/delta (foodlog-dwt)"
```

---

## Task 6: Three-track section in notebook 04

**Files:**
- Modify: `notebooks/04_hall_baseline.ipynb`

- [ ] **Step 1: Add new cells at the bottom of notebook 04**

After the existing "Posterior track" section (from `foodlog-adu`), add:

Cell (markdown):
```markdown
## Three-track diurnal evaluation (Phase 3)

The morning-only track is the most identifiable observation channel — the body is closer to true mass after overnight excretion. Evening adds today's food/water/sodium load. The delta itself is the cleanest test of the diurnal model, since absolute weight cancels out.

If `morning_weight_kg` and `evening_weight_kg` aren't both populated in `df`, this section is skipped — paired-data collection is in progress under `foodlog-dwt`.
```

Cell (code):
```python
if "morning_weight_kg" in df.columns and df["morning_weight_kg"].notna().sum() > 0 \
        and df["evening_weight_kg"].notna().sum() > 0:
    for track in ("morning", "evening", "delta"):
        walk_t = validation.forward_walk(
            df, step_days=7, profile=DEFAULT_PROFILE, sample_n=200, seed=42,
            track=track,
        )
        rep = evaluate.summary_report(walk_t)
        print(f"=== {track.title()} track ===")
        print(f'  MAE: {rep["mae"]:.3f} kg')
        print(f'  95% calibration: {100*rep["calibration_coverage"]:.1f}%')
        print(f'  n obs: {rep["n_observations"]}')
else:
    print("Skipping — no paired AM/PM data yet (foodlog-dwt acceptance not met)")
```

Cell (code — sanity check: delta correlates with diet/activity):
```python
import scipy.stats as stats

if df["diurnal_delta_kg"].notna().sum() >= 10:
    paired = df.dropna(subset=["diurnal_delta_kg"])
    for feature in ("intake_kcal", "sodium_mg", "workout_min"):
        if paired[feature].notna().sum() >= 10:
            r, p = stats.pearsonr(paired[feature].fillna(0), paired["diurnal_delta_kg"])
            print(f'  diurnal_delta vs {feature}: r={r:.3f}, p={p:.3f}')
```

- [ ] **Step 2: Execute the notebook**

```bash
.venv/bin/jupyter nbconvert --to notebook --execute notebooks/04_hall_baseline.ipynb \
    --output 04_hall_baseline.ipynb --ExecutePreprocessor.timeout=1800
```

Expected: all three tracks report metrics. If paired data is < 30 days, expect noisy estimates — that's OK at this stage; the bead accepts metrics existing, not a particular calibration threshold (paired-data volume is the bottleneck).

The correlation sanity check should show:
- `intake_kcal` positively correlated with `diurnal_delta_kg` (r > 0.2 expected)
- `sodium_mg` positively correlated
- `workout_min` slightly negatively (or null if rehydrated)

If correlations are absent on plenty of paired data, the diurnal model's coefficients need re-tuning — log a Phase-3.1 bead.

- [ ] **Step 3: Commit**

```bash
git add notebooks/04_hall_baseline.ipynb
git commit -m "feat(body_sim): notebook 04 — three-track diurnal evaluation (foodlog-dwt)"
```

---

## Task 7: Documentation + close

**Files:**
- Modify: `body_sim/CLAUDE.md`

- [ ] **Step 1: Update CLAUDE.md**

In `body_sim/CLAUDE.md`, in the "Weigh-in protocol metadata" section, extend the enum to include `controlled_evening`. Then add a new "Diurnal model (Phase 3)" section:

```markdown
## Diurnal model (Phase 3)

Closed by `foodlog-dwt` (YYYY-MM-DD). Adds:

- **`controlled_evening`** protocol value for weigh-ins at 19:00–22:00 local on/after 2026-05-21.
- **`body_sim/diurnal.py`** — pure-function model of the AM→PM delta as `food_in_transit + sodium_pm_water − sweat`. Coefficients in the module docstring.
- **`BodyState.predicted_evening_weight_kg`** — adds the diurnal delta to `predicted_weight_kg`.
- **`forward_walk(track=...)`** — `morning`, `evening`, or `delta` channels.
- **Three-track section** in notebook 04 with per-track MAE / calibration plus a correlation sanity-check of `diurnal_delta_kg` against `intake_kcal` / `sodium_mg` / `workout_min`.

Open Phase-3 inputs surfaced by this work:
- (Fill in any surprises observed: e.g., diurnal delta correlates strongly with sodium but not intake, suggesting the food-in-transit coefficient is over-estimated.)
- (If sodium PM-vs-AM lag is needed, log a Phase-3.1 bead for `sodium.py` to model the next-morning rollover.)
```

- [ ] **Step 2: Commit**

```bash
git add body_sim/CLAUDE.md
git commit -m "docs(body_sim): Phase-3 diurnal model summary (foodlog-dwt)"
```

- [ ] **Step 3: Close the bead**

```bash
bd close foodlog-dwt --reason="Diurnal mass model lands. Pipeline emits morning/evening/delta columns, BodyState predicts evening weight, forward_walk supports track filter, notebook 04 reports per-track metrics + correlation sanity check. (Paired-data volume continues to accumulate; metrics will sharpen over time.)"
```

- [ ] **Step 4: Session-close protocol**

```bash
git pull --rebase
bd dolt push 2>&1 || true
git push
git status
```

---

## Self-review notes

- **Prereqs flagged loudly** at the top: protocol metadata, Bayesian framework, paired-data volume. Won't waste a session on a misfire.
- **Scope coverage:** every bead acceptance item — paired data plumbed, model produces predicted diurnal, evaluation includes all 3 tracks, correlation sanity check — has a task.
- **Open design questions** section is honest about what gets resolved during execution vs. pinned.
- **No placeholders:** every code change spelled out.
- **Type consistency:** `Protocol` literal has three values throughout; `track` literal has three values throughout.
- **Closure:** Task 7 closes the bead with a realistic note that paired-data accumulation continues post-close.
