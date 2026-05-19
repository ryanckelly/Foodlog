# Pixel Watch / Google Health Connect — data type discovery

Investigation deliverable for [`foodlog-jav`](../.beads/issues/foodlog-jav).
Purpose: decide which additional Google Health v4 data types are worth syncing
in support of the body-composition simulator's "unusual day" detector
(illness / alcohol / severe sleep debt) — and which to skip.

**Method.** Pulled the v4
[discovery doc](https://health.googleapis.com/$discovery/rest?version=v4) for
the exhaustive type catalog, then probed each candidate live against the
account's OAuth token over a 30-day window. Probe script lives at
`scripts/probe_pixel_watch_types.py`.

**Date.** 2026-05-19. Device: Pixel Watch 3, platform `FITBIT`.

---

## Summary recommendations

| Action | Type | Phase |
|---|---|---|
| **Sync** | `sleep` stages + summary (already pulled, just read more fields) | phase-1 |
| **Sync** | `daily-heart-rate-variability` | phase-1 |
| **Sync** | `daily-sleep-temperature-derivations` | phase-1 |
| **Sync** | `daily-oxygen-saturation` (bundle with respiratory-rate) | phase-1 |
| **Sync** | `daily-respiratory-rate` (bundle with SpO2) | phase-1 |
| **Sync** | `activity-level` (1-min categorical) — large volume, defer to phase-2/3 | phase-2 |
| **Fix doc** | Correct `doc/HEALTH_DATA.md` sleep-stages claims (wrong) | phase-1 |
| **Skip** | `respiratory-rate-sleep-summary` — known unit bug (1000× scaled) | n/a |
| **Skip** | `vo2-max` / `daily-vo2-max` / `run-vo2-max` — empty for this account | n/a |
| **Skip** | `hydration-log` — manual entry, requires extra OAuth scope, behavior-change cost outweighs body-sim value | n/a |
| **Skip** | Personal-range types — documented in schema but not actually exposed via the API | n/a |

Beads to file are listed at the bottom under [Recommended follow-up beads](#recommended-follow-up-beads).

---

## Method notes worth keeping

These belong in the persistent memory layer alongside the existing v4 quirks.

1. **The v4 discovery doc is authoritative for the *type catalog and field schemas*** — do not guess data-type names or field names. URL: `https://health.googleapis.com/$discovery/rest?version=v4`. The reverse-engineering style of `clients/google_health.py:FILTER_FIELDS` only needs to cover the filter-grammar quirk (snake_case prefix), not field discovery.
2. **The discovery doc is *not* authoritative for what's actually accessible.** Several types (`heart-rate-variability-personal-range`, `resting-heart-rate-personal-range`) appear in schema descriptions but return `INVALID_PARENT_DATA_TYPE_COLLECTION` on every request shape we tried. Schema = aspirational; live probe = real.
3. **`daily-*` types do not support `:dailyRollUp` or `:rollUp`.** Only `list` and `reconcile`. Confirmed for `daily-heart-rate-variability` and `daily-resting-heart-rate`; assume true for the other daily-* siblings.
4. **Pixel Watch wear coverage drives missingness.** Daily-aggregate types (HRV, SpO2, resp rate, skin temp, sleep stages) all converged at **60–67% of nights present** over 30 days. Missingness is a feature, not a bug — treat NaN as "no signal today, do not update trust weight."

---

## Per-type findings

### 1. `sleep` — already synced, missing 90% of the payload

- **Availability.** ✅ 20 sessions over 30 days. 19 with `type: STAGES` and one `CLASSIC` (older/edge case).
- **Coverage.** 20/30 = 67%.
- **Data quality.** Excellent. `stagesStatus: SUCCEEDED` on every STAGES session. Per-night DEEP minutes 41–113, REM 51–140, LIGHT 103–281, AWAKE 3–61. Sensible ranges.
- **API quirks.** Same as the existing sync — only filter member is `sleep.interval.civil_end_time`, intermittent 500s on wider ranges (already mitigated with a 3-day rolling window in `_sync_sleep`).
- **Schema sketch.** Two options:
  - **(A) Extend `sleep_sessions` with columns** — add `sleep_type` (enum `STAGES`/`CLASSIC`/`UNSPECIFIED`), `nap` (bool), `stages_status`, and per-stage minute totals (`awake_min`, `light_min`, `deep_min`, `rem_min`, `restless_min`, `asleep_min`) read straight from `summary.stagesSummary`.
  - **(B) New `sleep_stages` table** for per-segment detail (`session_id`, `stage_type`, `start_at`, `end_at`).
  - Recommend doing (A) first — it's where 95% of body-sim value lives. (B) is only useful for fine-grained sleep-architecture analysis later.
- **Why this matters for the body-sim.** Deep-sleep minutes is the strongest passive predictor of HRV recovery and recovery state. The current `sleep_sessions` table records the envelope but throws away the stage breakdown that's on the *same payload* we already fetch — pure waste.
- **Value assessment.** ✅ **Sync. Highest priority.** Marginal cost: zero new HTTP calls (we already fetch this payload), one schema migration, one parser change.

### 2. `daily-heart-rate-variability` — the cleanest body-sim signal

- **Availability.** ✅ Endpoint name confirmed via discovery doc.
- **Coverage.** 19/30 days = 63%.
- **Data quality.** High. Per-night fields:
  - `averageHeartRateVariabilityMilliseconds`: 25.4 – 64.7 ms (median 48). Sane.
  - `deepSleepRootMeanSquareOfSuccessiveDifferencesMilliseconds`: 20.7 – 58.25 ms (median 47). The gold-standard RMSSD-during-deep-sleep metric.
  - `entropy`: 2.796 – 3.396 (Shannon entropy of heartbeat intervals).
  - `nonRemHeartRateBeatsPerMinute`: 52 – 67 bpm (median 56). **Returned as a string** — cast at parse time.
- **API quirks.**
  - Filter member is `daily_heart_rate_variability.date`, date format `YYYY-MM-DD`.
  - Action set is `list, reconcile` only — no rollup.
  - `nonRemHeartRateBeatsPerMinute` is a `string<int64>` per the discovery doc (same shape quirk as `averageHeartRateBeatsPerMinute` on `exercise`).
- **Schema sketch.** New table `daily_hrv` with columns:
  - `date` (PK), `avg_hrv_ms`, `deep_sleep_rmssd_ms`, `non_rem_hr_bpm`, `entropy`, `source`, `external_id`.
  - Cursor-walk on `date`, 90-day default backfill (same pattern as `resting_heart_rate`).
- **Value assessment.** ✅ **Sync. Phase-1 priority.** This is the single most informative passive signal for the "unusual day" detector (illness, alcohol, severe sleep debt all drop HRV 20-50% from baseline). Personal baseline is computed locally — see "Personal range" below.

### 3. `daily-sleep-temperature-derivations` — illness flag, with the baseline math pre-shipped

- **Availability.** ✅
- **Coverage.** 19/30 = 63%.
- **Data quality.** High. Per-night fields:
  - `nightlyTemperatureCelsius`: 30.81 – 33.94 °C (median 32.8). Skin temp, not core.
  - `baselineTemperatureCelsius`: 32.80 – 33.06 °C (very stable — 30-day median computed by Google).
  - `relativeNightlyStddev30dCelsius`: 0.087 – 0.857. **Pre-computed "how unusual is tonight vs. user's 30-day baseline."**
- **API quirks.** Standard `date`-filter. No surprises.
- **Schema sketch.** New table `daily_sleep_temperature` with columns:
  - `date` (PK), `nightly_temp_c`, `baseline_temp_c`, `relative_stddev_30d_c`, `source`, `external_id`.
- **Value assessment.** ✅ **Sync. Phase-1 priority.** Skin-temp deviation is the textbook passive flag for illness onset (typically rises 2-3 days before symptoms) and alcohol (raises baseline 0.3-0.8°C). The fact that Google ships `relativeNightlyStddev30dCelsius` means we get the "is today unusual" judgment without re-implementing rolling-baseline math on our side.

### 4. `daily-oxygen-saturation` + `daily-respiratory-rate` — bundle them

- **`daily-oxygen-saturation`**
  - Coverage 18/30 (60%). Fields: `averagePercentage` 93.7–97, `lowerBoundPercentage` 90.1–95.6, `upperBoundPercentage` 95.8–99, `standardDeviationPercentage` 0.6–1.0.
  - All within physiologically normal range for a healthy sleeper. Periodic drops below 90% would flag sleep-disordered breathing or altitude.
- **`daily-respiratory-rate`**
  - Coverage 19/30 (63%). Field: `breathsPerMinute` 9.8–11.4. On the low end of clinical normal (12-20 BPM is typical), but consistent and plausible for a fit individual.
- **API quirks.** Both use `.date` filter, standard shape, no surprises.
- **Schema sketch.** Single shared table `daily_respiratory_oxygen`:
  - `date` (PK), `breaths_per_min`, `spo2_avg_pct`, `spo2_low_pct`, `spo2_high_pct`, `spo2_std_pct`, `source`, `external_id`.
- **Value assessment.** ✅ **Sync, bundle as one bead.** Modest standalone value; combined they're a cheap second-opinion check against the skin-temp illness signal. Bundling cuts the sync-method count and table count.

### 5. `activity-level` — defer to phase-2

- **Availability.** ✅ Pixel Watch 3 emits 1-minute samples with `activityLevelType` ∈ {`SEDENTARY`, `LIGHTLY_ACTIVE`, `MODERATELY_ACTIVE`, `VERY_ACTIVE`}.
- **Coverage.** Effectively continuous — 1-minute granularity, paginated. 30 days × 1440 samples/day = ~43k rows uncompressed.
- **Data quality.** Categorical; quality is whatever Pixel's classifier is. Per-minute granularity is overkill for the body-sim. Useful aggregation would be **minutes-per-day per category**, computable from this raw feed.
- **API quirks.** Filter member is `activity_level.interval.civil_start_time`.
- **Value assessment.** Defer. Not phase-1 critical (NEAT/activity-bias work doesn't kick in until phase-3 per the body-sim spec). When ready, write as **rolled-up daily totals** (`daily_activity_minutes` table with `sedentary_min`, `lightly_min`, `moderately_min`, `very_min`), not per-sample.

### 6. `respiratory-rate-sleep-summary` — skip, has a unit bug

- **Availability.** Endpoint returns 200 with no filter (no filterable members on the schema). 92 samples in 30 days (multi-stage breakdown per night).
- **Data quality.** ❌ **Documented field values are off by a factor of 1000.**
  - Reported `breathsPerMinute` ranges 0.0098–0.0124. Daily-resp-rate for the same nights shows 9.8–11.4 BPM. Multiply the small values by 1000 → exact agreement on medians.
  - `remSleepStats` fields occasionally go negative (`breathsPerMinute = -0.001`) — likely sentinels for "no REM detected this night."
- **API quirks.** No filter members. Either you take all pages or you don't.
- **Value assessment.** ❌ **Skip.** Per-stage breathing-rate split could in principle add nuance over the daily aggregate, but with a known 1000× scale bug on Google's side and undocumented negative-value sentinels, the cost of trusting this stream exceeds its marginal value. Use `daily-respiratory-rate` instead. Revisit if Google ships a fix.

### 7. `vo2-max` / `daily-vo2-max` / `run-vo2-max` — skip, empty for this account

- **Availability.** Endpoints all return 200 with **0 data points** over 14 days.
- **Data quality.** N/A — no data.
- **Why empty.** Pixel Watch's VO2 max / Cardio Fitness Score is gated on completing a GPS-tracked run/walk meeting Fitbit's algorithm requirements. The account has walks but no GPS runs.
- **Value assessment.** ❌ **Skip.** Re-evaluate if GPS-tracked runs become a regular thing.

### 8. `hydration-log` — skip on scope + behavior cost

- **Availability.** 403 — `MISSING_OAUTH_SCOPE` (needs `nutrition` or `nutrition_readonly`).
- **Data quality.** Untested — manual-entry data, quality is whatever the user logs.
- **Value assessment.** ❌ **Skip.** Adding a scope requires Google reconsent. Hydration manually-logged through the Fitbit app would compete with the food-logging path that already runs through FoodLog. Marginal body-sim value (hydration affects weight by a few hundred grams) is not worth the friction.

### 9. Personal-range types — schema says yes, API says no

- **Availability.** Discovery doc lists `heart-rate-variability-personal-range` and `resting-heart-rate-personal-range` as "rollup type identifiers" returned by default when rolling up `daily-heart-rate-variability` and `daily-resting-heart-rate`.
- **Reality.** `daily-heart-rate-variability` and `daily-resting-heart-rate` reject every rollup form (`:rollUp` and `:dailyRollUp`) with `UNSUPPORTED_DATA_TYPE_ACTION`. `:dailyRollUp` on sibling types (`heart-rate`, `steps`, `active-minutes`, `active-zone-minutes`) returns 200 but with no personal-range fields embedded. The personal-range schema is unreachable via this API.
- **Value assessment.** ❌ **Skip — compute personal baseline locally.** A trailing 30-day median + IQR computed on the synced `daily_hrv` and `resting_heart_rate` tables gives us a transparent, adjustable equivalent. The body-sim is better served by a baseline we understand than one Google computes internally.

### 10. Already-captured types with field-level gaps (informational)

For completeness, the [field-level catalog](http://192.168.1.40:9999/google-health-v4-endpoint-catalog) flagged these as PARTIAL captures:

- **`exercise`** — we ignore `splits`, `splitSummaries`, `exerciseEvents`, `exerciseMetadata`, `activeDuration`, `notes`. Modest value (per-split pace data inside walks). Not phase-1 for body-sim.
- **`daily-resting-heart-rate`** — we ignore `dailyRestingHeartRateMetadata`. Unknown value until inspected on a live point.
- **`heart-rate`** — we ignore `metadata`. Low likely value.
- **`weight`** — we ignore `notes`. Nil value (we don't have manual-entry weighings).

These are deferred for now; file follow-ups only if a concrete use case appears.

---

## Recommended follow-up beads

These are ready to file with `bd create --labels=body-sim,phase-1` once approved.
Single-line titles + one-paragraph descriptions; full design specs live in this doc.

1. **Sync sleep stages + per-night summary** — extend `_sync_sleep` to also parse `sleep.type`, `sleep.metadata`, `sleep.summary.stagesSummary`. Add columns to `sleep_sessions` (Option A above). Zero new HTTP cost; pure parser + migration.

2. **Sync `daily-heart-rate-variability`** — new table `daily_hrv`, new client method `list_daily_hrv`, new `_sync_daily_hrv` cursor-walk on `date`. Highest-priority signal for the body-sim's "unusual day" detector.

3. **Sync `daily-sleep-temperature-derivations`** — new table `daily_sleep_temperature`, cursor-walk. Captures `relativeNightlyStddev30dCelsius` so the body-sim doesn't have to re-implement rolling-baseline math.

4. **Sync `daily-oxygen-saturation` + `daily-respiratory-rate`** — bundled into one table `daily_respiratory_oxygen` with one `_sync_` method that calls both endpoints. Modest standalone value, cheap to add together.

5. **Correct `doc/HEALTH_DATA.md` sleep-stages claims** — current doc says "session envelope only — no stage breakdown" and lists stages as "not in v4 API at all." Both wrong. Fix in the same PR as #1.

6. **Persist v4 method-discovery learnings to `bd remember`** — single memory entry covering: discovery doc URL, the snake_case filter prefix rule, daily-* types being list+reconcile only, and personal-range being unreachable. Replaces the stale `reference_google_health_v4_quirks` memory referenced in the bead.

### Deferred (not phase-1)

7. **Roll up `activity-level` to daily totals** — when phase-2/3 (NEAT, activity-bias) starts. Per-minute storage is overkill; daily totals per category is the right shape.

8. **Read `exercise.splits` / `splitSummaries`** — only if a concrete pace-within-walks question shows up.

### Explicitly not filed (skip rationale documented above)

- `respiratory-rate-sleep-summary` — unit bug.
- `vo2-max` family — empty.
- `hydration-log` — scope + behavior cost.
- Personal-range types — unreachable.
