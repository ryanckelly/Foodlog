# body_sim — sub-project guidance

The body-composition scenario simulator: a notebook-driven research workflow that consumes the foodlog SQLite DB and produces forecasts of weight + body-fat trajectories under counterfactual diet/exercise scenarios. Lives alongside the foodlog FastAPI app but does not deploy with it — this is research code.

## Pointers

- **Design spec:** `docs/superpowers/specs/2026-05-18-body-composition-simulator-design.md`
- **Phase 1 implementation plan:** `docs/superpowers/plans/2026-05-18-body-sim-phase-1.md`
- **Beads (filter to sub-project):** `bd list --label=body-sim`
- **Phase epics:**
  - `foodlog-jok` — Phase 1 (extended Hall + population defaults) — **CLOSED**
  - `foodlog-j90` — Phase 2 (personalize `intake_bias` + `RMR_scale` via PyMC) — open, awaiting more data
  - `foodlog-6bi` — Phase 3 (add NEAT, protein_protection, activity_bias)
  - `foodlog-evq` — Phase 4 (optional ML residual layer)

## Layout

```
body_sim/                  this package — pure-math modules + pipeline + simulator + validation
notebooks/                 Jupyter notebooks (02 → 07) — execute against the live DB
notebooks/predictions/     parquet rollup artifact + JSONL live-forecast log
tests/body_sim/            in-memory-SQLite tests for every module
```

The package is flat-layout (`body_sim/`, not `src/body_sim/`) to match the foodlog repo convention. Module map is in `README.md`.

## Conventions for new work

All beads in this sub-project carry **two labels**: `body-sim` and exactly one of `phase-1` / `phase-2` / `phase-3` / `phase-4`. See `/opt/foodlog/CLAUDE.md` (root) for the full convention.

```bash
bd create --type=task --labels=body-sim,phase-2 --title="..." --description="..."
```

## Data exclusions

The model in this sub-project excludes the following `body_composition` readings from analysis. **The DB rows themselves are not modified** by the body_sim pipeline — the exclusion is enforced at pipeline-read time only, so the foodlog dashboard and MCP tools continue to see the full data.

The exclusion list is maintained as a constant in `body_sim/pipeline.py`:

```python
EXCLUDED_BODY_COMP_IDS: frozenset[str] = frozenset({
    "users/7108215177813058725/dataTypes/weight/dataPoints/1777669898000",
    "users/7108215177813058725/dataTypes/weight/dataPoints/1777824995000",
})
```

| external_id | measured_at | weight_kg | bf% | Reason for exclusion |
|---|---|---|---|---|
| `.../weight/dataPoints/1777669898000` | 2026-05-02 00:11:38 | 85.3 | — | Taken with clothes on, outside the regular morning-routine time-of-day. ~2 kg heavier than subsequent readings, missing body-fat measurement (consistent with the scale not being able to measure bf% on a clothed weigh-in). |
| `.../weight/dataPoints/1777824995000` | 2026-05-03 19:16:35 | 84.75 | — | Same reason. Evening weigh-in, off the established methodology. |

The rest of the body_composition history is a consistent post-void naked morning routine (~10–11 AM) with paired weight + body-fat readings from a Withings/Renpho scale via Fitbit Web API sync.

**To add more exclusions later:** append the row's `external_id` to `EXCLUDED_BODY_COMP_IDS` and re-execute the notebooks. No schema migration required, no DB writes needed. The exclusion test (`test_body_comp_rollup_skips_excluded_external_ids` in `tests/body_sim/test_pipeline_other.py`) verifies the filter is wired up.

If a single methodologically-clean reading later proves to be a real outlier (illness, dehydration, hardware fault) and you want to exclude it, the same mechanism applies — get the row's `external_id` from `body_composition.external_id` and add it to the constant.

## Weigh-in protocol metadata

Each `body_composition` row carries a `weigh_in_protocol` string column. Classification uses **scheme B — cutoff-date only** (`foodlog-aou`, 2026-06-06):

- `"controlled_morning"` — **any** reading on or after the cutoff date **2026-05-21**, regardless of time-of-day. The user takes one disciplined morning weigh-in per day (post-void, pre-breakfast, consistent clothing); a post-cutoff reading is assumed to be that routine reading.
- `"uncontrolled"` — any pre-cutoff weigh-in.
- `"controlled_evening"` — **no longer emitted.** Retained in the `Protocol` literal only so rollup code that still recognizes pre-existing rows keeps type-checking. It was part of the abandoned AM/PM diurnal design (`foodlog-dwt`).
- `NULL` — un-backfilled rows; treated as `"uncontrolled"` downstream.

> ### ⚠️ Forget-proofing: why there is NO time-of-day window
>
> **If you change your weigh-in routine — different time of day, or more than one weigh-in per day — this classifier will silently mislabel the off-protocol readings as `controlled_morning` and the Phase-2 fit will over-trust them.** Scheme B trusts *everything* post-cutoff. The fix when that happens: either add the bad rows to `EXCLUDED_BODY_COMP_IDS` (preferred for one-offs), or set a new `WEIGH_IN_PROTOCOL_CUTOFF`.
>
> **Do NOT "fix" this by reintroducing a clock window.** That was the original design and it was buggy: it compared a **naive-UTC** `measured_at` (normalized in `google_health.py`) against a `07:00–11:00` window written with **local-time (Atlantic)** intent. The user's 08:00–09:00 ADT weigh-ins land at 11:00–12:00 UTC — just past the window — so every real weigh-in was tagged `uncontrolled`, feeding the user's *cleanest* data the loose `sigma_obs_uncontrolled` (0.8) instead of `sigma_obs_controlled` (0.3). An empirical A/B (timezone-corrected window vs. cutoff-only) gave **identical labels on all real data**; the window only mattered for hypothetical off-time post-cutoff readings that don't occur. So the window was deleted, not repaired. If you ever genuinely need per-reading time discrimination, convert UTC → `zoneinfo("America/Halifax")` *first* — but prefer the exclusion list.

The classification is the pure function `body_sim.weigh_in.classify_protocol(datetime) -> Protocol`. Sync (`foodlog.services.health_sync._sync_body_composition`) applies it at upsert; backfill existing rows with `python -m body_sim.tag_weigh_ins --apply` (add `--force` to overwrite rows mislabeled under the old window logic).

The daily rollup surfaces this as a `weigh_in_protocol_controlled: bool` column on `rollup_body_comp` output — `True` only if every non-excluded weigh-in that day is `controlled_morning`. The flag is propagated through `validation.forward_walk` for downstream consumers.

This metadata is **soft** — not a filter. Filtering of methodologically-broken rows continues to happen via `EXCLUDED_BODY_COMP_IDS` (see "Data exclusions" above). Phase 2 (`foodlog-adu`) uses this column to assign tighter σ_obs to controlled rows in the PyMC likelihood — empirically, correctly tagging the post-cutoff block sharpened `sigma_obs_controlled` from its 0.24 prior mean to **0.13** (the model learns the standardized weigh-ins are tight) while `sigma_obs_uncontrolled` rose to 0.69 (the scattered pre-cutoff readings are correctly isolated as noisy).

## Phase 3 diurnal model (infrastructure only)

`foodlog-dwt` (closed 2026-05-21, infrastructure-only) adds the framework to model paired AM/PM weigh-ins as separate observation channels. The real-data acceptance metrics are deferred until ~30 days of paired weigh-ins exist.

Architecture:
- `body_sim/weigh_in.py` — `Protocol` literal still includes `controlled_evening`, but as of `foodlog-aou` (scheme B) `classify_protocol` **no longer emits it** — the evening clock window was removed along with the morning one. This whole diurnal stack is dormant infrastructure (the user takes single morning weigh-ins, not AM/PM pairs); a future teardown bead can remove it. See "Weigh-in protocol metadata" above.
- `body_sim/diurnal.py` — pure-function model: `diurnal_delta = food_in_transit + sodium_pm_water − sweat`.
- `body_sim/model.py` — `BodyState.predicted_evening_weight_kg(...)`.
- `body_sim/pipeline.py` — `rollup_body_comp` emits `morning_weight_kg`, `evening_weight_kg`, `diurnal_delta_kg`.
- `body_sim/validation.py` — `forward_walk(track="morning" | "evening" | "delta")` filter; the morning track preserves prior behavior.
- `notebooks/04_hall_baseline.ipynb` — three-track section that auto-skips when paired data is absent.

Synthetic-data unit tests pass (model, diurnal, pipeline, validation). Real-data evaluation is gated by paired-weigh-in accumulation — once the user logs ~30 days of both AM and PM weigh-ins, the three-track section will produce per-track MAE / calibration and a `pearsonr` sanity check of `diurnal_delta_kg` vs intake / sodium / workout features.

Open Phase-3.1 inputs once paired data exists:
- If diurnal_delta correlates weakly with intake_kcal, the `FOOD_TRANSIT_FRACTION_AT_EVENING` coefficient (currently 0.50) is wrong for this user — refit empirically.
- If sodium correlates strongly with the NEXT morning's weight (carryover effect), `sodium.water_kg` needs a one-day-lag term.
- Optional Phase-3.2: extend the Bayesian fit to include a diurnal latent + observation channel.

## Phase 2 results

`foodlog-adu` (closed 2026-05-21) landed the PyMC fit with glycogen-water as a Gaussian-random-walk latent state plus per-protocol observation noise. Architecture:

- `body_sim/bayesian.py` — PyMC model. Free RVs: `sigma_glycogen` (HalfNormal(0.4)), `sigma_obs_controlled` (HalfNormal(0.3)), `sigma_obs_uncontrolled` (HalfNormal(0.8)), `g` (GaussianRandomWalk length-n).
- `body_sim/bayesian_predict.py` — posterior predictive band that includes Hall trajectory + latent + obs noise.
- `body_sim/validation.py` — `forward_walk(mode="posterior", idata=...)` consumes the trace.
- `notebooks/05_bayesian_fit.ipynb` — runs the fit, saves trace to `notebooks/predictions/posterior.nc` (gitignored).
- `notebooks/04_hall_baseline.ipynb` — appended posterior-track section.

Posterior-track results on current data (n=8 daily obs):

| Track | Prior MAE | Prior calibration | Posterior MAE | Posterior calibration |
|---|---|---|---|---|
| Daily | 0.321 kg | 42.9% | **0.189 kg** | **100.0%** |
| Weekly | 0.275 kg | 62.5% | **0.128 kg** | **100.0%** |

The 100% calibration is wide-band — at n=8 the posterior over `sigma_obs_uncontrolled` is still loose (mean 0.51 kg). As more weigh-ins accumulate, `sigma_obs_*` will sharpen and calibration will settle to a tighter number above the 80% target. This is the architecturally-correct band, where the Phase-1 prior-track band was structurally too narrow.

Scope deferred to Phase 2.1 (file a new bead when wanted):
- **Joint fit of `intake_bias` and `RMR_scale`.** Current Phase-2 v1 uses population defaults for the Hall trajectory. The glycogen latent absorbs the resulting systematic offset, which is acceptable for the predictive band but means we're not yet identifying intake under-reporting magnitude.
- **Per-day `sigma_obs` driven by protocol.** Once enough `controlled_morning` rows exist (post-2026-05-21 weigh-ins), the per-protocol split should become informative (currently `sigma_obs_controlled` is mostly prior).
- **Diagnostic refinement.** Convergence on `sigma_glycogen` is marginal at low data volume (r_hat ≈ 1.04 in latest fit); expect r_hat to settle as data accumulates.

## Phase 1 known limitations (open Phase 2 inputs)

These came out of the Phase 1 validation run on 2026-05-19 and are documented in `foodlog-j90` notes:

- **Daily and weekly bands are noise-limited.** As of `foodlog-1or` (2026-05-21), notebook 04 reports both daily AND 7-day-trailing-rolling-mean metrics. Current numbers (n=7 daily obs, n=16 weekly obs):
  - Daily — MAE 0.321 kg (PASS), calibration **42.9%** (FAIL), drift p=0.562 (PASS).
  - Weekly — MAE 0.275 kg (PASS), calibration **62.5%** (FAIL), drift p=0.000 (FAIL — model can't track the user's trend with population defaults).

  The ~20-point calibration improvement at weekly cadence confirms the timescale-mismatch hypothesis (glycogen-water + gut-content noise dominate daily variance). The remaining gap to 80% is the 200-sample Monte Carlo band propagating only Hall **parameter** uncertainty — not latent-state uncertainty. `validation._seed_state` further treats observed weight as fat+lean only, so day-1 predicted weight is systematically ~0.5–1.4 kg above the seed once glycogen + sodium water are added back in `BodyState.predicted_weight_kg`. **The weekly track is the canonical Phase-1 calibration metric** because most of the latent-state noise averages out over a week of typical eating. Daily-track failure with weekly-track partial improvement is the expected Phase-1 result. Daily calibration is unblocked by `foodlog-adu` (glycogen-water as PyMC latent state, Phase 2).
- **Only ~12 weigh-ins (post-exclusion).** Phase 2 fitting kicks in once we have ~30 paired food+weight days.

### Resolved in Phase 1

- **Keytel overcounting at sedentary HR** (`foodlog-w76`, 2026-05-20). Naïve daily integration of Keytel double-counted RMR for sedentary minutes — `ee_hr_keytel_kcal` averaged ~3,400 kcal/day, driving total expenditure to ~5,150 kcal (≈2× RMR). The fix subtracts the per-minute kcal Keytel predicts at a personal *awake-resting* baseline HR before integrating, so only activity *above* baseline is added to Mifflin RMR. Default baseline method is `resting_states_p10`: P10 of HR across 15-min windows with zero steps, not in sleep, not in a workout (eligibility filter uses `IntervalActivity`/`SleepSession`/`Workout` tables). Empirical winner of a 9-method bake-off (`notebooks/run_baseline_comparison.py`). Pre-fix nb04: MAE 1.154 kg, calibration 0%. Post-fix nb04: MAE 0.321 kg, calibration 43%.
- **Validation harness silently bypassed model's NaN-intake skip contract** (`foodlog-5tf`, 2026-05-20). `validation._row_to_input` coerced NaN intake to 0.0, making the model treat unlogged days as zero-intake days under full expenditure. Fix: preserve NaN so `model.step`'s skip guard fires. Bug was latent on the current walk window (no NaN-intake days post-first-weigh-in) but is correctness-preserving regression-prevention.

## Re-executing the notebooks

From `/opt/foodlog/`:

```bash
for nb in 02_data_pipeline 03_descriptive_eda 04_hall_baseline 06_scenario_simulator 07_live_tracking; do
    .venv/bin/jupyter nbconvert --to notebook --execute notebooks/${nb}.ipynb \
        --output ${nb}.ipynb --ExecutePreprocessor.timeout=600
done
```

Notebook 02 must run first — it produces the parquet artifact that the others consume.

The default window auto-tracks logging history: nb02 calls `pipeline.first_food_log_date(session)` and pulls everything from that date forward. To scope to a fixed lookback instead (e.g. for a 60-day retrospective HR-only analysis), override the `start` variable in the second cell.
