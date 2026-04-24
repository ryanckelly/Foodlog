# Resolution: Google Health integration follow-ups

Follow-up to `2026-04-24-google-health-followups.md`. Session on 2026-04-24 closed most of what that handoff listed. This doc records the delta in case the next person needs history.

## What was resolved

### Per-type parsers rewritten against real v4 response shapes

- `steps` and `total-calories` now use the `:dailyRollUp` POST endpoint and parse `steps.countSum` / `totalCalories.kcalSum` per civil day (list was minute-level for steps, unsupported entirely for total-calories).
- `weight` reads `weight.weightGrams` (÷1000 → kg). `body-fat` reads `bodyFat.percentage`.
- `daily-resting-heart-rate` reads `dailyRestingHeartRate.beatsPerMinute` with the date anchored to civil midnight.
- `heart-rate` reads `heartRate.beatsPerMinute` + `heartRate.sampleTime.physicalTime`.
- `exercise` (workouts) reads `exercise.interval.{startTime,endTime}`, `exercise.exerciseType`, `exercise.displayName`, and the `metricsSummary.*` bag. **No** `maxHeartRateBeatsPerMinute` exists in the response — max HR is derived from `workout_hr_samples` by the sync service.
- `sleep` parser already worked; left untouched.

All parsers log-and-skip on unexpected shape rather than `KeyError`-crashing — so a future Google schema change can't take down the whole sync.

### Filter grammar fix (the root cause of half the 400s)

`FILTER_FIELDS` entries for multi-word types use the **snake_case** data-type prefix (`body_fat`, `heart_rate`, `daily_resting_heart_rate`). The camelCase forms the earlier session inherited from the docs returned `INVALID_DATA_POINT_FILTER_DATA_TYPE_MEMBER`.

### Concurrency bug (`OperationalError: database is locked`)

`HealthSyncService` held a SQLite write transaction open across all of Google's HTTP calls. Two overlapping dashboard requests → second request's writer collided with the first. **Fix:** every per-type `_sync_*` now drains its async iterator into a list before opening any transaction. Lock is held for ms instead of seconds.

### Performance fix (HR-sample refetch)

Heart-rate samples paginate at ~50 per page; a 46-min walk was ~1500 samples = 30+ HTTP round-trips per workout, repeated on every on-presence sync. Now `_sync_workouts_with_hr` skips any workout whose samples are already in DB (upserts are idempotent so one successful pull is enough).

### Sleep endpoint brittleness

Google's sleep `list` endpoint 500s intermittently for this account regardless of filter window (confirmed with 14d, 3d, and 1d look-backs). Marked brittle in `sync_all._run()` — brittle types log at INFO on `GoogleHealthError` and do NOT flip the stale banner. Sleep's cursor is a fixed 3-day look-back for robustness.

### UI surface additions

- Steps card in the Movement & Recovery section (`activity` context key). Shows per-period step count and active-calories under the title.
- `SyncResult` now plumbed through to the dashboard so `rate_limited` renders a distinct banner ("rate limited — retry in a moment") vs. generic `stale`.
- `max_hr` derivation + upsert so the HR spark-chart bars have a proper peak for scaling.

## What's still open (deferred, low priority)

- **Weight trend sparkline over 30 days** — currently shows just a 7-day delta number. User had no scale data during this session; can add when data appears.
- **Sleep stage breakdown** (REM / deep / light) — Google returns `sleep.stages` array; we ignore it.
- **Duplicate workout detection** across Pixel Watch + Caliber sources — schema has `source` column; dedup rule can wait until real dupes appear.
- **`/dashboard/debug/health` admin endpoint** — dump recent sync results for ops visibility.
- **Sleep endpoint 500s on Google's side** — not a code issue. If it keeps happening, file via Google's issue tracker.
- **Design system pass** on the rendered cards — visual review against `DESIGN.md` tokens.

## Test expectations

Baseline is now **123 passing** (was 112 at the start of the session). Fixtures under `tests/fixtures/google_health/` encode the real v4 envelope shapes — update those first if Google's schema changes again.

## Useful session memories

- `feedback_docker_env_plumbing.md` — adding a `Settings` field requires edits in 3 files; docker-compose doesn't use `env_file`.
- `feedback_docker_compose_run_duplicates_tunnel.md` — **never** use `docker compose run` for diagnostics; spawns a duplicate cloudflared connector and CF round-robins producing phantom split-brain bugs. Use `docker exec foodlog` instead.

## If the dashboard still shows the stale banner

Check `docker logs --tail 500 foodlog | grep -E "google-error|sync crashed"` for the failing type. Sleep 500s are now silenced; anything else showing up there is a real regression.
