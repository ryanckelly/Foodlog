# Body-Composition Scenario Simulator — Design Spec

**Status:** Approved 2026-05-18
**Authors:** ryan, claude
**Builds on:** `2026-04-22-foodlog-google-health-design.md` (health data integration), `2026-05-01-foodlog-granular-timeline-design.md` (interval-level data tables)
**Related beads:** `foodlog-jok` Phase 1 epic, `foodlog-j90` Phase 2, `foodlog-6bi` Phase 3, `foodlog-evq` Phase 4, `foodlog-b1f` / `foodlog-fkn` / `foodlog-taq` Phase 1 data enhancements, `foodlog-a73` Phase 3 dashboard integration

**Scope of this spec:** umbrella design for all four phases of the sub-project. The *first implementation plan* derived from this spec scopes to Phase 1 only (`foodlog-jok`). Phase 2, 3, and 4 get their own implementation plans when their data-accumulation triggers fire — this spec is the contract they all share.

## Problem

FoodLog now collects food intake (per-meal macros), daily activity (steps, active calories), interval-level heart rate / steps / AZM, sleep sessions, resting heart rate, workouts, and body composition (weight + bf% from a Withings/Renpho scale). The user wants to use this data to **simulate counterfactual diet/exercise scenarios** ("what if I cut calories 10% for 8 weeks", "what if I increase steps 20%", "what if I increase protein and reduce fat"), not just predict the next day.

Pure regression / ML approaches answer the wrong question — they can correlate but not extrapolate intervention, and on 14 weight readings they overfit catastrophically. The right tool is a **mechanistic energy-balance model** with personalized parameters fit via Bayesian inference, structured so it produces immediately-useful output on minimal data and grows in fidelity as data accumulates.

This sub-project lives inside the foodlog repository as a notebook-driven workflow modeled on the parallel NHL game-outcome prediction project at `~/hockey`. Same temporal discipline, same baseline-then-personalize sequencing, same notebook-plus-`src/`-module layout.

## Goals

- Produce a runnable scenario simulator (Jupyter notebook with `ipywidgets`) that lets the user explore counterfactual diet/exercise inputs and see predicted body weight + body fat % trajectories with quantified uncertainty.
- Use a mechanistic Hall-style energy-balance model extended with terms for heart-rate-derived expenditure, macronutrient thermogenesis, glycogen-bound water, and sodium-bound water — population defaults at Phase 1, personalized via PyMC at Phase 2+.
- Handle missing inputs (smartwatch not worn, meals not logged, weigh-ins skipped) by treating them as latent variables with priors, not by row exclusion or naive imputation.
- Validate the model against observed weigh-ins using forward-walking validation, eyeball-first plots, MAE, and a defined "passing" calibration threshold.
- Establish a four-phase roadmap (population defaults → fit two parameters → fit more → optional ML residual) that earns complexity as data accumulates.
- Ship the simulator behind a notebook surface in Phase 1; promote to dashboard integration in Phase 3 once the model is calibrated.

## Non-goals

- Real-time prediction or production-API exposure during Phase 1. Notebook only.
- Recommendation engine ("you should eat X tomorrow"). The model produces forecasts; the user interprets.
- Multi-user. Foodlog is single-user; the model parameters are personal.
- Replacing the existing daily dashboard. This work is additive and orthogonal.
- Free-form natural-language input. The simulator inputs are numeric (kcal, g, steps, min).
- Population-comparison benchmarks ("you burn more than 70% of users your age"). No comparative dataset.
- Real-time model retraining from the UI. Fits happen offline, in notebook 05.

## Empirical foundation

Confirmed against the live foodlog database on 2026-05-18:

| Table | Rows | Date range | Notes |
|---|---|---|---|
| `food_entries` | 178 | 2026-04-16 → 05-18 (33d) | `meal_type` clean: only `breakfast` / `lunch` / `dinner` / `snack` values present; MCP correctly tags per-item even across batch submissions spanning multiple meals |
| `daily_activity` | 23 | 2026-04-23 → 05-18 | Daily rollup from Fitbit (steps, active kcal) |
| `body_composition` | 14 | 2026-05-02 → 05-15 | Weight + bf%, sparse (~1/day at best, gaps common) |
| `sleep_sessions` | 23 | 2026-01-27 → 05-18 | Duration only today; stage breakdown to be added under `foodlog-taq` |
| `workouts` | 8 | 2026-04-12 → 05-14 | With HR samples table populated for workout windows |
| `resting_heart_rate` | 65 | 2026-01-26 → 05-18 | Daily |
| `interval_heart_rate` | many | varies | Minute-level for full-day Keytel integration when watch is worn |
| `interval_azm` | many | varies | AZM (FAT_BURN / CARDIO / PEAK) intervals from Fitbit |

The dominant data-volume constraint: **14 body-composition readings.** All design choices flow from this. Population-default model first, single-parameter fit at Phase 2 once data doubles, sequential parameter addition thereafter.

## Conceptual foundation

### The energy-balance model

The simulator is a discrete-time dynamical system:

```
state_{t+1} = f(state_t, inputs_t, parameters)
observation_t = g(state_t) + noise
```

The state tracks two slow compartments (fat mass `F`, lean mass `L`) and two fast compartments (glycogen-bound water, sodium-bound water). The inputs are daily food intake (kcal + macros + sodium) and daily activity (HR-derived expenditure, vigorous minutes, workouts). The observation is the morning scale reading (weight in kg and bf%).

Per-day update (sketch — full equations live in `src/body_sim/model.py`):

```
TEF      = 0.25·protein_kcal + 0.08·carb_kcal + 0.03·fat_kcal
RMR      = mifflin_st_jeor(F, L, age, sex) · RMR_scale
activity = EE_keytel(hr_minute_series, F+L, age) if hr_coverage > 0.5
           else fallback_from_steps_and_workouts(steps, workout_kcal)
activity = activity · activity_bias
adapt    = adaptive_thermogenesis(history)
EE       = RMR + activity + TEF + adapt
ΔE       = intake_kcal · intake_bias − EE
p        = forbes_partition(F) · protein_protection(protein_g_per_kg, ΔE)
ΔF       = p · ΔE / 9500
ΔL       = (1 − p) · ΔE / 7600
Δglyc    = glycogen_dynamics(carb_g, current_glyc)
weight_observed = F + L + 3.5·glycogen_g/1000 + sodium_water(sodium_mg) + noise
```

Variables prefixed `parameter_name` are the personalized parameters (Section "Personalization"). The remaining functions use published functional forms with population-default constants drawn from the Hall et al. 2011 paper and subsequent literature.

### Why mechanistic

Three properties drop out of the mechanistic form that pure ML approaches lack:

1. **Counterfactual validity.** Changing an input and rolling forward is a defined operation. ML models trained on observational data correlate inputs with outputs in ways that violate intervention semantics — e.g., they may learn "lower intake correlates with higher weight" because the user logs fewer calories on workout-recovery days when fluid retention is elevated.
2. **Small-data robustness.** ~5-10 parameters, anchored to physiology, are fitted from sparse data far better than thousands of ML weights.
3. **Native missingness handling.** State-space form treats missing observations as "skip the measurement update step" and missing inputs as "use prior over the latent value." No imputation required.

### Why Bayesian

With N=14 weigh-ins, frequentist point-estimation degenerates. Bayesian inference contributes:

- **Priors anchor the fit** to physiologically plausible values (e.g., `RMR_scale ~ Normal(1.0, 0.05)` — narrow because RMR rarely varies more than 10% across individuals). As data accumulates, the prior loses influence and the posterior tightens.
- **Posterior distributions, not point estimates.** Every counterfactual produces a *fan* of trajectories, with 95% credible bands. Wide bands today; narrowing as the dataset grows.
- **Posterior-predictive checks** for honest validation — sample from the posterior, simulate observation noise, ask whether the model's predictive distribution covers actual readings at the declared rate.

The standard tooling is PyMC. ~50-200 lines for the full model.

## Data inputs — canonical daily-rollup table

One row per calendar day, produced by `src/body_sim/pipeline.py::build_daily_rollup(start, end)`:

| Column | Unit | Source | If missing |
|---|---|---|---|
| **Intake** ||||
| `intake_kcal` | kcal | `food_entries` sum | NaN + `intake_logged=False` |
| `protein_g` | g | `food_entries` sum | NaN if intake missing |
| `carb_g` | g | `food_entries` sum | NaN if intake missing |
| `fat_g` | g | `food_entries` sum | NaN if intake missing |
| `sodium_mg` | mg | `food_entries` sum | NaN if intake missing |
| `meal_types_logged` | frozenset | `food_entries.meal_type` distinct | empty set |
| `intake_coverage` | 0.0–1.0 | derived: count of {breakfast, lunch, dinner} present, divided by 3 | 0.0 |
| `intake_logged` | bool | `intake_coverage >= 0.67` | False |
| **Activity** ||||
| `steps` | count | `daily_activity` | NaN if no row |
| `active_kcal_fitbit` | kcal | `daily_activity` | NaN if no row |
| `ee_hr_keytel_kcal` | kcal | computed from `interval_heart_rate` via Keytel, integrated over the day | NaN if `hr_coverage_pct < 50` |
| `vigorous_min` | min | `interval_azm.peak_min` sum over day | 0 |
| `cardio_min` | min | `interval_azm.cardio_min` sum over day | 0 |
| `hr_coverage_pct` | 0–100 | minutes of HR data / 1440 | 0 |
| `rhr_bpm` | bpm | `resting_heart_rate` | forward-fill up to 3 days, else NaN |
| **Workouts** ||||
| `workout_kcal` | kcal | `workouts` sum (started on this day) | 0 |
| `workout_min` | min | `workouts.duration_min` sum | 0 |
| **Recovery (carried, not yet modeled)** ||||
| `sleep_total_h_prev_night` | h | `sleep_sessions` ending today before noon | NaN |
| `sleep_rem_h` | h | `sleep_sessions` (after `foodlog-taq` lands) | NaN |
| `sleep_deep_h` | h | `sleep_sessions` (after `foodlog-taq`) | NaN |
| `sleep_light_h` | h | `sleep_sessions` (after `foodlog-taq`) | NaN |
| `sleep_awake_h` | h | `sleep_sessions` (after `foodlog-taq`) | NaN |
| **Observations (targets)** ||||
| `weight_kg` | kg | `body_composition` median (if multiple weigh-ins) | NaN — never imputed |
| `bf_pct` | % | `body_composition` median | NaN — never imputed |
| `n_weighins` | count | `body_composition` count | 0 |

### Missingness conventions

The conventions are not negotiable design constants — they encode the difference between "no signal" and "true zero":

| Convention | Applies to | Rationale |
|---|---|---|
| **`NaN` = unknown latent variable** | intake when no log; steps when watch not worn; weight/bf% when no weigh-in | These quantities exist on the missing day but are unobserved. The model treats them as latent and uses priors. |
| **`0` = true zero** | workouts, vigorous minutes, AZM minutes | The dominant case is genuinely "did not do a workout"; treating as `NaN` would force the model to invent imaginary workouts. |
| **Forward-fill up to N days** | `rhr_bpm` (N=3) | RHR is slow-moving; one missing day is well-approximated by yesterday's value. Beyond 3 days the signal stales. |
| **Confidence weight, not filter** | `hr_coverage_pct`, `intake_coverage` | The model uses these to widen/narrow priors on the latent quantities, not to drop rows. |
| **Targets never imputed** | `weight_kg`, `bf_pct` | A missing observation contributes no measurement update; the state continues evolving via the dynamics. |

### `intake_coverage` heuristic — empirical validation

Confirmed against the 33 days of food data on 2026-05-18:

- Distribution: 43% of days at coverage=1.0 (breakfast + lunch + dinner present), 47% at 0.67 (two of three), 10% at 0.33 (one main meal). Snacks ignored — they are noise, not signal, for completeness detection.
- Most common missing meal: breakfast. Plausibly genuinely small/skipped rather than under-logged.
- Batch logging (multiple `food_entries` rows from one MCP submission) does not corrupt the heuristic. The MCP correctly tags each item with its own `meal_type`, including across cross-meal batches (10 such batches observed, all correctly tagged — e.g., one submission on 2026-05-10 at 20:16 contained items tagged `breakfast`, `lunch`, and `snack` for items consumed at different times during that day).

The heuristic flows into the model as a continuous confidence weight on `intake_bias`: low coverage → wider prior on logged intake's true value.

## Personalization — Bayesian parameter fitting

Parameters that get personalized, in the order they are added:

| Parameter | Phase | Role | Prior (population) |
|---|---|---|---|
| `intake_bias` | 2 | Multiplier on `intake_kcal` to correct systematic under/over-reporting | `Normal(0.85, 0.10)` (mean reflects literature 15% under-reporting bias) |
| `RMR_scale` | 2 | Multiplier on textbook RMR formula | `Normal(1.0, 0.05)` |
| `NEAT_response` | 3 | Strength of spontaneous-activity adaptation to over/under-eating | `Normal(0.2, 0.1)` |
| `protein_protection` | 3 | Effect of adequate protein on lean-mass preservation during deficit | `Normal(0.5, 0.2)`, bounded [0, 1] |
| `activity_bias` | 3 | Scaling between HR-Keytel expenditure and true activity calories | `Normal(1.0, 0.1)` |
| `water_noise_sd` | 2 | Observation noise SD on weight likelihood (always fit from Phase 2 onward as part of the likelihood, not a behavior parameter) | `HalfNormal(0.8)` (kg) |

`water_noise_sd` is structurally different from the behavior parameters: it parameterizes the likelihood of `weight_observed` given the latent state, not a physiological pathway. It is fit jointly with whichever behavior parameters are active in the current phase (i.e., from Phase 2 onward, always).

Each behavior parameter is added one at a time with an **identifiability check** before adoption:

1. Posterior should be narrower than prior (the data is informative).
2. Posterior-predictive should improve on a held-out window (measured forward-walking).
3. No drift in already-fit parameters (orthogonality check).
4. Sampler health: Rhat < 1.05, no divergences, ESS adequate.

If any check fails for a parameter at a given phase, it stays at population default and we document what data accumulation would be needed.

## Validation

### The dominant constraint

N=14 weigh-ins as of 2026-05-18. Standard train/test/validation splits do not apply. Validation is **forward-walking**, eyeball-first, with a tightly-defined passing threshold.

### Required plots in every model notebook

1. **Predicted weight trajectory + 95% credible band + observed weigh-ins overlaid as dots.** This is *the* plot. If the dots track the band, the model is working. If they drift outside, it is not.
2. **Predicted bf% trajectory + 95% band + observed bf% overlaid.**
3. **Residual time-series: `observed − predicted` over time**, with horizontal reference lines at ±0.5 kg (typical day-to-day scale noise). Inspected for monotonic drift, autocorrelation, and correlation with unmodeled covariates (sodium spikes, low-coverage days, sleep deficits — these are diagnostic, not yet model inputs).

### Forward-walking protocol

```
1. Fit on days 1..N
2. Forward-simulate days N+1..N+7, score against observed weigh-ins in that window
3. Refit on days 1..N+7
4. Forward-simulate days N+8..N+14, score
5. ...repeat
```

Aggregated scores: MAE (mean absolute error), calibration coverage rate (fraction of observed weigh-ins inside the 95% band), residual Kendall's tau (drift test).

RMSE is **not** used. On small samples it is dominated by single outliers and produces unstable rankings.

### Passing thresholds (Phase 1)

| Metric | Target | Reason |
|---|---|---|
| Weight calibration | ≥80% of observed weigh-ins inside predicted 95% band | If the band misses systematically, the model is wrong (not just imprecise). |
| Weight MAE | < 1.0 kg | The day-to-day scale noise floor. Below this, additional accuracy is below sensor resolution. |
| Weight residual drift | Kendall's tau p > 0.1 | A drifting residual means a missing slow-acting term (probable culprits: adaptive thermogenesis, unmodeled NEAT). |
| bf% calibration | ≥80% inside 95% band | bf% noise floor wider (impedance scales are noisy). |
| bf% MAE | < 2.5% absolute | Withings/Renpho measurement noise level. |

If Phase 1 (population defaults) hits all five, we ship the simulator. If not, Phase 2 fits parameters until it does. If Phase 2/3 also fall short, the diagnostic plot from check #3 above tells us which mechanism is missing.

## Phases

The sub-project decomposes into four phases. Each phase is a beads epic; phase-2 depends on phase-1, etc.

### Phase 1 — `foodlog-jok` — Extended Hall model with population defaults

**Trigger:** current.

**Deliverables:**

- `notebooks/02_data_pipeline.ipynb` — SQLite → daily-rollup DataFrame, HR-Keytel integration, macro aggregation
- `notebooks/03_descriptive_eda.ipynb` — energy-balance plots, weight-vs-glycogen-water decomposition, missingness map, HR-coverage stats
- `notebooks/04_hall_baseline.ipynb` — extended Hall model with TEF + HR-derived EE + glycogen-water + sodium-water, population-default parameters, observed-vs-predicted trajectory plot
- `notebooks/06_scenario_simulator.ipynb` — `ipywidgets` sliders for intake kcal, macro split, steps, vigorous_min, horizon — renders trajectory bands using population priors
- `notebooks/07_live_tracking.ipynb` — scaffold for weekly forecast logging (so Phase 2 has something to score)
- `src/body_sim/` Python module with `model.py`, `pipeline.py`, `keytel.py`, `validation.py`, `evaluate.py`
- `tests/body_sim/` — unit tests for the rollup pipeline, Keytel integration, Hall update step, validation harness

**Parallel enablers** (non-blocking, can land any time during Phase 1):
- `foodlog-b1f` — submission_id on `food_entries`
- `foodlog-fkn` — separate `consumed_at` from `logged_at`
- `foodlog-taq` — sleep stage breakdown in `sleep_sessions`

**Exit criteria:** the simulator notebook runs end-to-end on real data and produces the three required validation plots. **The five passing thresholds are aspirational at Phase 1** — with population defaults and 14 weigh-ins, some are likely to fail. Phase 1 is complete when the diagnostic plot has been inspected and any failing threshold has a documented diagnosis pointing to which parameter would close the gap (informs Phase 2 prioritization). Phase 1 does not block on hitting all thresholds.

### Phase 2 — `foodlog-j90` — Personalize `intake_bias` and `RMR_scale` via PyMC

**Trigger:** ~30 total weigh-ins with paired food/activity coverage (i.e., ~4-6 more weeks beyond Phase 1 kickoff).

**Deliverables:**

- `notebooks/05_personalize_fit.ipynb` (v1) — PyMC model definition, NUTS sampling, diagnostic plots (Rhat, ESS, divergences, posterior plots, posterior-predictive)
- Updated `notebooks/06_scenario_simulator.ipynb` to draw from posterior samples → narrower credible bands
- Retrospective: did Phase 1 weekly forecasts hold up?

**Exit criteria:** the two parameters fit identifiably (posterior narrower than prior), sampler healthy, simulator credible bands measurably tighter, exit criteria from Phase 1 thresholds still met or improved.

### Phase 3 — `foodlog-6bi` — Add `NEAT_response`, `protein_protection`, `activity_bias`

**Trigger:** ~3 months of data accumulated, AND the variation in the data is sufficient to identify each new parameter (e.g., enough deficit/surplus weeks for NEAT_response).

**Deliverables:**

- `notebooks/05_personalize_fit.ipynb` (v2) — sequential parameter addition with identifiability checks
- Decision document on which parameters are *not* yet identifiable
- Updated simulator with full personalized posterior

### Phase 4 — `foodlog-evq` (optional) — ML residual model

**Trigger:** ~6 months of data AND residual structure diagnostic shows non-noise patterns.

**Deliverables:**

- `notebooks/08_residual_ml.ipynb` — residual autocorrelation + partial-dependence checks first; only proceeds to model fitting if structure exists
- Hybrid prediction = mechanistic forecast + ML residual correction
- Comparison vs mechanistic-only on a held-out window

Phase 4 may be cancelled if residuals are noise — explicit decision documented with diagnostic plots.

### Phase 3+ deliverable — `foodlog-a73` — Dashboard integration

**Trigger:** Phase 3 milestone complete AND Phase 1 passing thresholds met across multiple forward-walking windows.

**Deliverables:**

- `/dashboard/simulator` route in the FastAPI app, gated by SSO, rendered as Notion-system per `DESIGN.md`
- Serves the same simulator UX as notebook 06 but accessible from phone or any browser

## Deliverable shape — Phase 1

**Jupyter notebook with `ipywidgets` sliders.**

```python
# In notebook 06, cell N
from ipywidgets import interactive, FloatSlider, IntSlider
from body_sim.simulate import run_scenario, plot_trajectory

def render(intake_kcal, protein_g, carb_g, fat_g, steps, vigorous_min, horizon_days):
    traj = run_scenario(
        baseline_state=current_state,
        inputs={
            "intake_kcal": intake_kcal,
            "protein_g": protein_g,
            "carb_g": carb_g,
            "fat_g": fat_g,
            "steps": steps,
            "vigorous_min": vigorous_min,
        },
        horizon_days=horizon_days,
        parameter_samples=parameter_samples,  # Phase 1: samples from prior; Phase 2+: from posterior
        n_traces=200,
    )
    return plot_trajectory(traj)

interactive(
    render,
    intake_kcal=FloatSlider(min=1200, max=3500, step=50, value=2000),
    protein_g=FloatSlider(min=40, max=250, step=10, value=120),
    carb_g=FloatSlider(min=50, max=400, step=10, value=200),
    fat_g=FloatSlider(min=20, max=200, step=5, value=70),
    steps=IntSlider(min=2000, max=20000, step=500, value=8000),
    vigorous_min=IntSlider(min=0, max=120, step=5, value=15),
    horizon_days=IntSlider(min=7, max=180, step=7, value=56),
)
```

Output: matplotlib figure showing predicted weight + bf% trajectories with 95% credible bands, plus a small derived-quantities table (`predicted_fat_lost`, `predicted_lean_change`, `predicted_avg_TDEE`).

Streamlit, batch-runner-via-YAML, and dashboard integration are explicitly **not** Phase 1 deliverables. Dashboard integration is a Phase 3+ bead (`foodlog-a73`). Streamlit and batch-runner are skipped unless a concrete need emerges.

## Repository layout

```
foodlog/                         # existing package; unchanged by this work
notebooks/                       # new
  02_data_pipeline.ipynb
  03_descriptive_eda.ipynb
  04_hall_baseline.ipynb
  05_personalize_fit.ipynb       # Phase 2+
  06_scenario_simulator.ipynb
  07_live_tracking.ipynb
  08_residual_ml.ipynb           # Phase 4 only
src/body_sim/                    # new — reusable code consumed by notebooks
  __init__.py
  pipeline.py                    # build_daily_rollup, missingness conventions
  keytel.py                      # HR → kcal-per-min via Keytel equation
  model.py                       # Hall-extended difference equations
  partition.py                   # Forbes partition + protein_protection
  glycogen.py                    # carb → glycogen → water
  sodium.py                      # sodium → water
  fit.py                         # PyMC model definition (Phase 2+)
  simulate.py                    # forward-simulate scenarios from posterior samples
  validation.py                  # forward-walking harness
  evaluate.py                    # MAE, calibration coverage, residual diagnostics
  plotting.py                    # the three required plots
tests/body_sim/                  # new
  test_pipeline.py               # rollup correctness on synthetic data
  test_keytel.py                 # equation matches published values
  test_model.py                  # update step conserves mass and energy
  test_validation.py             # forward-walking harness behaves on known input
```

`src/body_sim/` follows the same pattern as `~/hockey/src/` — Python modules anchored via `Path(__file__).resolve().parent.parent` so notebook CWD does not break paths.

## Open questions / known limitations

These are accepted constraints, not bugs to fix in this design:

- **Body fat % is noisier than weight** (impedance method ±2-3% under good conditions). The validation thresholds reflect this; bf% predictions will have wider bands than weight predictions throughout all phases.
- **Adaptive thermogenesis** (the "your body fights back" effect during prolonged dieting) is included in the model via a simple time-integrated term. It may not be the right functional form for this user; if Phase 1 residuals show monotonic drift after several weeks of deficit, that's the term to revisit.
- **Hydration shifts from glycogen and sodium are first-order accurate, not exact.** A high-carb / high-sodium meal can move the scale 1-2 kg overnight. The model accounts for this in the `water_kg` term but may not catch unusual events (illness, hot weather, alcohol).
- **The model assumes steady-state hormonal context.** Major hormonal shifts (illness, severe sleep deprivation, alcohol binges) are not represented. Days with such events should be flagged manually in EDA.
- **No real-time predictions during Phase 1.** Live tracking is a weekly cadence (forecast logged at the start of each week, scored at the end).
- **`intake_bias` will absorb logging errors.** If under-reporting is consistent across days, the parameter compensates and counterfactuals remain valid. If it is inconsistent (e.g., good logging weekdays, poor weekends), the model will be biased and the residual plot should reveal weekend structure.
- **Workouts table is sparse (8 rows).** Most activity expenditure flows through HR-Keytel from `interval_heart_rate`; the workouts table is supplementary. This is fine as long as HR coverage on workout days is high.

## Beads conventions for this sub-project

Documented in `CLAUDE.md` as of 2026-05-18:

- Umbrella label `body-sim` on every bead.
- Phase label `phase-1` / `phase-2` / `phase-3` / `phase-4` on every bead, exactly one.
- `bd list --label=body-sim` to scope to the sub-project; `bd list --label=body-sim,phase-1` to scope to the current phase (comma-separated = AND).
- New beads use `bd create --type=task --labels=body-sim,phase-1 --title="..." --description="..."`.

## Out of scope for this design

- Migrating the model from notebooks into the foodlog FastAPI app — that is `foodlog-a73` (Phase 3 bead).
- Caching strategies for posterior samples in the dashboard — also `foodlog-a73`.
- Multi-user model parameters or sharing scenarios — not a foodlog concern.
- Population-comparison benchmarks — no comparative dataset exists.
- Alternative tooling (Stan, NumPyro, JAX) — PyMC is chosen and the model is small enough that runtime is not the bottleneck.
