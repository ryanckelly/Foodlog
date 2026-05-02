# Google Health Data Coverage

What each connected device records, what the Google Health v4 REST API exposes, and what FoodLog actually pulls in. Also: the granularity available from Google vs. the granularity we store, and how often we sync.

This doc is descriptive, not aspirational — every claim about FoodLog reflects current code in `foodlog/clients/google_health.py` and `foodlog/services/health_sync.py`.

## Sync mechanics

| Aspect | Value | Source |
|---|---|---|
| Trigger | Dashboard render schedules a `BackgroundTask` after the response is sent | `dashboard.py:91` |
| Min interval between syncs | 30 s | `SYNC_MIN_INTERVAL_S`, `dashboard.py:33` |
| Concurrency guard | One sync at a time (`_sync_state.inflight`) | `dashboard.py:97` |
| Banner state | Reflects the **previous** completed sync (lags by one cycle) | `CLAUDE.md` |
| Default first-sync look-back | 90 days for cursor-based types | `DEFAULT_BACKFILL_DAYS`, `health_sync.py:30` |

A sync only runs when the dashboard is loaded — there is no separate scheduler. FoodLog catches up whenever you next open the dashboard, capped to one fetch per 30 s.

### Source chain by device

The Google Health REST API only reads from your **Google cloud account**. That cloud is populated by:

- **Pixel Watch** → Fitbit cloud (Fitbit being a Google subsidiary that powers Pixel Watch) → Google account. This is automatic; all watch metrics flow through.
- **Renpho scale** → **Fitbit cloud** → Google account. Renpho writes directly to Health Connect on Android, but **Health Connect is on-device only** — its data does not sync to the Google cloud, so the Google Health REST API can never see it. The working path is to link Renpho → Fitbit in the Renpho app's third-party connections; Renpho then pushes weigh-ins to Fitbit cloud, which the Google Health API does read. Confirmed working 2026-05-02 with `platform: FITBIT_WEB_API` data points appearing within ~5 min of a weigh-in.

Direct Renpho → Google Fit is also no longer a working path (Google Fit is being sunset, and Renpho's modern app prefers Health Connect).

### Per-type look-back window

| Type | Window each sync | Why |
|---|---|---|
| `daily_activity` | Yesterday + today, always re-fetched | Daily totals can change late as the watch backfills minute-level samples |
| `body_composition` | Cursor: `max(measured_at)` → now (90 d on empty table) | Each weigh-in is a fresh row; cursor walk is sufficient |
| `resting_heart_rate` | Cursor: `max(measured_at)` → now (90 d on empty table) | One row per day; cursor walk is sufficient |
| `sleep_sessions` | Fixed 3-day rolling | Google 500s on wider sleep queries; 3 d catches the most recent night reliably |
| `workouts` | Fixed 14-day rolling | Filter is device-local civil time; cursor would skew across timezones |
| `workout_hr_samples` | Only fetched when a workout's `external_id` is **not** already in `workout_hr_samples` | A 46-min walk emits thousands of samples; refetching every sync took tens of seconds |

## What we currently collect

The full set of data FoodLog pulls today, in one place. Detail tables follow below.

| Metric | Device | API type | Granularity stored | Look-back per sync | Table |
|---|---|---|---|---|---|
| Steps | Pixel Watch | `steps` (dailyRollUp) | One total per civil date | Yesterday + today | `daily_activity` |
| Active calories | Pixel Watch | `total-calories` (dailyRollUp) | One total per civil date | Yesterday + today | `daily_activity` |
| Weight | Renpho scale (via Fitbit relay) | `weight` | Per weigh-in sample | Cursor; 90 d on first sync | `body_composition` |
| Body fat % | (none in practice) | `body-fat` | Code wired but Google has no data — see below | Cursor; 90 d on first sync | `body_composition` |
| Resting heart rate | Pixel Watch | `daily-resting-heart-rate` | One bpm per civil date | Cursor; 90 d on first sync | `resting_heart_rate` |
| Sleep sessions | Pixel Watch | `sleep` | Per-session envelope (start, end, duration; no stages) | Fixed 3-day rolling | `sleep_sessions` |
| Workouts | Pixel Watch | `exercise` | Per-session: type, duration, distance, calories, avg/max HR | Fixed 14-day rolling | `workouts` |
| Workout HR samples | Pixel Watch | `heart-rate` | Per-sample (~1/sec), workout window only | Once per new workout in the 14-day window | `workout_hr_samples` |

All syncs share the same trigger: dashboard load, capped to one fetch per 30 s.

## Coverage matrix

Legend:
- **API** = exposed by Google Health v4 (`health.googleapis.com`)
- **Pulled** = FoodLog currently fetches and persists it
- **Stored at** = the granularity row in our SQLite, not the granularity Google returns

### Pixel Watch (Pixel Watch 2 / 3 via Fitbit app)

| Device records | API type | API granularity | Pulled? | Stored at | Table |
|---|---|---|---|---|---|
| Steps | `steps` | Minute-level samples; `dailyRollUp` for per-day totals | Yes (rollup) | One row per civil date | `daily_activity` |
| Total / active calories | `total-calories` | `dailyRollUp` only (`list` unsupported) | Yes (rollup) | One row per civil date (`active_calories_kcal`) | `daily_activity` |
| Distance | `distance` | Interval samples | No | — | — |
| Floors climbed | `floors` | Interval samples | No | — | — |
| Altitude | `altitude` | Interval samples | No | — | — |
| Active minutes / AZM | `active-minutes`, `active-zone-minutes` | Interval | No | — | — |
| Activity level | `activity-level` | Interval categorical | No | — | — |
| Sedentary periods | `sedentary-period` | Interval | No | — | — |
| Basal energy burned | `basal-energy-burned` | kcal | No | — | — |
| Heart rate (continuous) | `heart-rate` | Per-sample (~1/sec during workouts) | Workout-window only | Per-sample inside a workout | `workout_hr_samples` |
| Heart rate variability | `heart-rate-variability`, `daily-heart-rate-variability` | Per-sample / daily ms | No | — | — |
| Resting heart rate | `daily-resting-heart-rate` | One per civil day | Yes | One row per day | `resting_heart_rate` |
| Daily HR zones | `daily-heart-rate-zones`, `time-in-heart-rate-zone`, `calories-in-heart-rate-zone` | Per-zone | No | — | — |
| VO₂ max | `vo2-max`, `daily-vo2-max`, `run-vo2-max` | Per-sample / daily | No | — | — |
| Blood oxygen (SpO₂) | `oxygen-saturation`, `daily-oxygen-saturation` | Per-sample / daily | No | — | — |
| Respiratory rate | `daily-respiratory-rate`, `respiratory-rate-sleep-summary` | Daily / per-session | No | — | — |
| Skin temperature (sleep) | `daily-sleep-temperature-derivations` | Per-night delta | No | — | — |
| Sleep | `sleep` | Per-session envelope (`startTime`, `endTime`, asleep/awake totals) | Yes | Per-session, envelope only — no stage breakdown | `sleep_sessions` |
| Workout (exercise) | `exercise` | Per-session + `metricsSummary` | Yes | Per-session: type, duration, distance, calories, avg/max HR | `workouts` |
| Swim laps | `swim-lengths-data` | Per-interval | No | — | — |
| Hydration log (manual) | `hydration-log` | Per-entry | No | — | — |

**Recorded by Pixel Watch but not in v4 API at all:**
Stress / EDA score, Daily Readiness, Sleep Score, Cardio Load, sleep stage breakdown (REM/deep/light), continuous skin temperature, ECG / AFib history, menstrual cycle data, step cadence within workouts. These live behind the Fitbit Web API, not Google Health.

### Renpho smart scale

Reaches FoodLog only via the Renpho → **Fitbit cloud** → Google account chain (see "Source chain by device" above). The Renpho → Health Connect path is a dead end for FoodLog because Health Connect doesn't bridge to Google's cloud.

| Device records | API type | API granularity | Pulled? | Stored at | Table |
|---|---|---|---|---|---|
| Weight | `weight` | Per-sample (each weigh-in) | Yes (via Fitbit relay) | Per-sample | `body_composition` (`weight_kg`) |
| Body fat % | `body-fat` | Per-sample | Code wired, no data | Per-sample (always null in practice) | `body_composition` (`body_fat_pct`) |
| Height (one-time) | `height` | Per-sample | No | — | — |

**Why body fat shows up in the schema but never has data:** Renpho's own FAQ states *"When using third-party apps between platforms and the Renpho app, it only brings over Weight, Change and BMI. Other metrics like body fat% are not transferred over."* The Renpho → Fitbit hop drops body fat. Confirmed empirically 2026-05-02 — fresh weigh-in produced 1 weight point, 0 body-fat points in Google.

**Recorded by Renpho but not reachable via Google Health at all:**
Body fat %, BMI, lean body mass, skeletal muscle mass, bone mass, body water %, visceral fat, BMR, metabolic age, protein %, subcutaneous fat. These appear in Health Connect on the phone but are not exposed via the cloud REST API. The realistic path to capture any of these is a direct **Renpho cloud-API client** (`renpho-api` on PyPI, reverse-engineered, hits `renpho.qnclouds.com`) running alongside the Google Health client. See "Notes for future work" below.

## Granularity gap (available vs. stored)

Where we deliberately downsample:

| Type | API offers | We store | Reason |
|---|---|---|---|
| Steps | Minute-level samples | One total per civil day | Dashboard only renders daily totals; minute-level would 10–100× the row count for no UI benefit |
| Heart rate | Continuous samples 24/7 | Only samples inside a known workout | Storing 86 400 samples/day was rejected during initial design; workout-window detail is enough for the workouts view |
| Resting HR | Daily aggregate | Daily aggregate | No gap — Google itself only emits this as a daily value |
| Sleep | Session envelope (no stages from this API) | Session envelope | No gap at the API level; stages aren't available here |
| Workout HR samples | Per-sample, paginated 50/page | Per-sample, idempotent | Stored full-fidelity; that's why we skip already-synced workouts on subsequent syncs |

## Notes for future work

- Adding a new pulled type means: extend `DATA_TYPES` and `FILTER_FIELDS` in `clients/google_health.py`, add a dataclass + a `list_*` async iterator, add a SQLAlchemy model, add a `_sync_*` method to `HealthSyncService`, and wire it into `sync_all`. See `docs/superpowers/specs/2026-04-22-foodlog-google-health-design.md` for the original design notes.
- The 30 s sync floor and the look-back windows above are deliberate; widen them carefully — sleep in particular regresses to deterministic 500s on wider queries on at least one test account.
- For metrics not in v4 (sleep stages, SpO₂, stress, scale body composition extras), the realistic options are the Fitbit Web API or a Health Connect Android shim — both meaningfully bigger projects than extending this client.
- For body fat / muscle / water / BMR / visceral fat from the Renpho scale specifically, the practical path is a parallel client against the **Renpho cloud API** (`renpho.qnclouds.com`). Reverse-engineered references: [`renpho-api` on PyPI](https://pypi.org/project/renpho-api/), [`antoinebou12/hass_renpho`](https://github.com/antoinebou12/hass_renpho), and [Neil Gary Allen's writeup](https://neilgaryallen.dev/blog/reverse-engineering-the-renpho-app). The new client would write into the existing `body_composition` table with a distinct `source` value (e.g. `RENPHO_CLOUD`), letting weight from Fitbit and body-fat from Renpho coexist on the same Weight card.
