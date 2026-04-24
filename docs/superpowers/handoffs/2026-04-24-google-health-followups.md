# Handoff: Finish the Google Health integration

## TL;DR

The Google Health OAuth flow, DB schema, dashboard integration, and **sleep** data path are all working end-to-end in production (`https://foodlog.ryanckelly.ca/dashboard`). Everything else from the original spec (`docs/superpowers/specs/2026-04-22-foodlog-google-health-design.md`) is either stubbed with placeholder request shapes that fail gracefully, or a UI piece that hasn't been wired up yet. This handoff lists what's left, in priority order.

## Before you start: orient yourself

Read these in this order (~10 minutes total):

1. `docs/superpowers/specs/2026-04-22-foodlog-google-health-design.md` — the product spec, especially the "Dashboard Surfacing — Option B" section which describes the target UI.
2. `docs/superpowers/plans/2026-04-22-foodlog-google-health.md` — the implementation plan that most of this session executed.
3. `DASHBOARD.md` — operator-facing doc, has the setup/flow summary and explains the on-presence sync model.
4. `foodlog/clients/google_health.py` — look at the module docstring ("Status per data type") for the current health of each endpoint. `FILTER_FIELDS` at the top is the single source of truth for per-type request grammar.
5. `foodlog/services/health_sync.py` — per-type sync methods; orchestrator wraps each in try/except so a broken type doesn't tank the pipeline (important: this is why the dashboard "works" even though several list methods crash).
6. `foodlog/api/routers/dashboard.py` → `_build_movement_context()` — assembles the template context from DB rows.
7. `foodlog/templates/dashboard/movement_partial.html` — the UI spec's "Option B" targeted layout. Three card types: workout (with HR spark chart), sleep, weight, plus net-calories pill badge in the summary.
8. `git log --oneline 702b9c2..HEAD` — the commit trail shows the whole build.

Then run the test suite to confirm baseline green:

```bash
source /opt/foodlog/.venv/bin/activate && pytest -q
# expect: 112 passed
```

## Reality check on the live API

All of the following was empirically observed against the live Google Health API in this session. Google's published docs matched reality only for the `sleep` endpoint; other types had surprises. The `list_sleep_sessions` method is the only one that parses a real API response shape today. The others assume a shape Google doesn't emit and will `KeyError` when invoked.

| Logical type (our name) | Google endpoint | List-action supported? | Filter grammar | Response shape status |
|---|---|---|---|---|
| `daily_steps` | `steps` | yes, 200 OK | `steps.interval.civil_start_time >= "…"` works | **WRONG** — returns minute-level samples nested under `pt["steps"]["count"]` (string), not daily aggregates. Client expects `pt["startTime"]` etc. → KeyError. |
| `daily_active_calories` | `total-calories` | **NO** — returns 400 `UNSUPPORTED_DATA_TYPE_ACTION`; must use `rollup`, `dailyRollup`, or `reconcile` at a different path | n/a | Need to switch to the `dailyRollup` endpoint. |
| `body_weight` | `weight` | yes, 200 OK | `weight.sample_time.civil_time` works | **Unverified** — test user had no weight data; returns `{}`. Real shape unknown; current parser assumes old flat layout. |
| `body_fat` | `body-fat` | yes, 200 OK | `bodyFat.sample_time.civil_time` works | Same as weight — unverified, no data in test account. |
| `resting_heart_rate` | `daily-resting-heart-rate` | list returns 400 | `dailyRestingHeartRate.date` is rejected with `INVALID_DATA_POINT_FILTER_DATA_TYPE_RESTRICTION` — **docs are wrong** about the filter field name | Can't fetch until grammar is discovered. |
| `heart_rate_sample` | `heart-rate` | list returns 400 | `heartRate.sample_time.physical_time` is rejected, "heartRate does not match any data type" — **docs are wrong** | Same as above. |
| `sleep_session` | `sleep` | yes, 200 OK ✓ | `sleep.interval.civil_end_time` works ✓ | ✓ Real parser. Use this as a template for the others. |
| `workout` | `exercise` | yes, 200 OK | `exercise.interval.civil_start_time` works | **Unverified** — test user had no workouts in window; returns `{}`. Assumed shape in `list_workouts` is from the plan, not from real data. |

An example of a real response shape (from the live API, captured this session):

```json
// GET /v4/users/me/dataTypes/sleep/dataPoints?filter=…
{
  "dataPoints": [{
    "name": "users/7108215177813058725/dataTypes/sleep/dataPoints/625849550671069752",
    "dataSource": {
      "recordingMethod": "DERIVED",
      "device": {"displayName": "Pixel Watch 3"},
      "platform": "FITBIT"
    },
    "sleep": {
      "interval": {
        "startTime": "2026-04-23T02:09:00Z",
        "startUtcOffset": "-10800s",
        "endTime": "2026-04-23T10:57:30Z",
        "endUtcOffset": "-10800s"
      },
      "type": "STAGES",
      "stages": [ /* detailed segments; we currently ignore these */ ]
    }
  }]
}
```

vs. `steps`:

```json
{
  "dataPoints": [{
    "dataSource": { "device": {"displayName": "Pixel Watch 3"}, "platform": "FITBIT" },
    "steps": {
      "interval": {
        "startTime": "2026-04-23T22:42:00Z",
        "civilStartTime": { "date": {"year": 2026, "month": 4, "day": 23},
                             "time": {"hours": 19, "minutes": 42} },
        /* civilEndTime similar */
      },
      "count": "10"   // note: STRING
    }
    // note: steps data points do NOT include a top-level `name` field
  }]
}
```

Key takeaways:
- Value field lives under a type-specific envelope (`pt["steps"]["count"]`, `pt["sleep"]["interval"]`, `pt["weight"]["…"]`), never under a generic `pt["value"]`.
- Top-level `name` is present on session-oriented types (`sleep`, probably `exercise`) and absent on sample-granularity types (`steps`, likely `heart-rate`). For types without `name`, synthesise an idempotent key from device + civilStartTime/civilEndTime or sample_time.
- `dataSource.device.displayName` (or `dataSource.platform`) is the cross-type way to populate our `source` column — plan's `originDataSource` doesn't exist in v4.
- Numeric values are often strings (`"count": "10"`). Cast on extraction.

## Probing the live API (fastest feedback loop)

A working access token is already stored in the DB via Google Health OAuth (encrypted with Fernet). To probe a data type from inside the container:

```bash
docker exec foodlog python - <<'PY'
import asyncio, httpx, datetime
from foodlog.db.database import get_session_factory
from foodlog.services.google_token import GoogleTokenService
from foodlog.clients.google_health import FILTER_FIELDS, _fmt_filter_ts

async def main():
    db = get_session_factory()()
    svc = GoogleTokenService(db)
    async with httpx.AsyncClient(timeout=20) as http:
        access = await svc.mint_access_token(http)
        TYPE = "steps"   # <-- change this
        field, fmt = FILTER_FIELDS[TYPE]
        since = datetime.datetime.utcnow() - datetime.timedelta(days=2)
        f = f'{field} >= "{_fmt_filter_ts(since, fmt)}"'
        url = f"https://health.googleapis.com/v4/users/me/dataTypes/{TYPE}/dataPoints"
        resp = await http.get(url, params={"filter": f},
                              headers={"Authorization": f"Bearer {access.value}"})
        print(resp.status_code, resp.text[:2000])

asyncio.run(main())
PY
```

Use this to discover the correct filter grammar for `heart-rate` and `daily-resting-heart-rate` (try variations: `heart_rate`, `heartrate`, `heart-rate`, with and without the type prefix in the filter field), and to explore the `rollup` / `dailyRollup` endpoints for `total-calories`.

**⚠ never use `docker compose run` for this — it spins up a sidecar that re-registers the cloudflared tunnel connector and silently round-robins with the live app.** See `~/.claude/projects/-opt-foodlog/memory/feedback_docker_compose_run_duplicates_tunnel.md` for the incident that taught us this.

## Work to do, in priority order

### 1. Backfill the broken data types (high value, moderate effort)

For each data type below, the fix pattern is:
1. Probe the real response with the snippet above.
2. Update the corresponding `list_*` method in `foodlog/clients/google_health.py` to parse the real shape — mirror what `list_sleep_sessions` did.
3. If the filter grammar is wrong (heart-rate, daily-resting-heart-rate), adjust `FILTER_FIELDS`.
4. If the action is wrong (total-calories), add a separate endpoint path for the rollup action; `_paginate` assumes `/dataPoints` — you'll need a companion helper for `/dataPoints:dailyRollup` or similar.
5. Update fixtures under `tests/fixtures/google_health/` to reflect the real shape, and adjust tests so they match the new parser contract.
6. Commit per type with a `fix(health): parse <type> against real API shape` message.

Priority within this bucket: `workout` (exercise) first — it's the biggest UI payoff once the user has a workout recorded; then `steps`/`total-calories` (daily activity rollup drives the net-calories badge); then `weight`/`body-fat`; then the heart rate pair (filter grammar discovery might be a small research rabbit hole).

### 2. Steps semantic mismatch (medium effort, architectural)

Google returns step count at 1-minute granularity. Our `daily_activity` table has a single row per date. You need to aggregate. Two reasonable approaches:

- **Client-side**: have `list_daily_activity` sum all minute-level `count` values grouped by the local civil date, then yield one row per date. Keep the existing DailyActivity schema. Simplest; matches spec intent.
- **Server-side rollup**: use Google's `dailyRollup` action for the steps endpoint too (if supported) and take a pre-summed total. Fewer samples to pull, but adds another endpoint shape.

Pick whichever is cleaner after you've verified the `dailyRollup` action shape for `total-calories` — you may end up wanting both to use the rollup endpoint for consistency.

### 3. Front-end completion (medium effort, no new domain knowledge)

The spec calls for three card types in the Movement & Recovery section: **workout** (with an inline HR spark chart), **sleep** (✓ working), **weight**. Templates already support all three (`foodlog/templates/dashboard/movement_partial.html`), but only sleep has real data flowing today. Once workout + weight data is populating the DB, those cards will just appear.

Remaining frontend-only work:
- **Net-calories pill badge** in the summary strip. Already templated (`{% if net_calories is not none %}` in `feed_partial.html`) and computed server-side in `dashboard.py`. Will light up automatically once `daily_activity.active_calories_kcal` has real values, which requires completing the `total-calories` rollup (item 1/2 above). Verify visually when data flows.
- **Workout spark chart visuals**. The template loops `{% for s in w.hr_samples %}<span style="height:{{ s.pct }}%"></span>` — `_build_movement_context` already scales bpm to a 0–100 pct using `workout.max_hr` as the peak. When real workout + hr-sample data lands, eyeball whether the peak scaling looks sane; may want to normalise against a configurable max (e.g. 180) instead of observed peak.
- **Stale / rate-limited banner copy.** Current treatment renders "Health data may be stale (sync failed)" via `stale=True`. `HealthSyncService.SyncResult` distinguishes `rate_limited` vs `server_error` but that signal is thrown away in `_run_health_sync` (which returns None). If you want the UI to say "rate limited, retry in a moment" vs. "sync failed," plumb the `SyncResult` through. Minor polish.
- **Design system pass.** `DESIGN.md` at repo root is authoritative; compare the rendered cards against the Notion-inspired tokens and tune.

### 4. Follow-ups explicitly deferred by the spec (low priority)

- **Duplicate workout detection** across Pixel Watch + Caliber apps. The `source` column was added to capture provenance so a dedup rule can be designed after real dupes appear. Diagnostic query: find time-overlapping `workouts` rows with different `source` values. Ignore until a user reports dupes.
- **Workout detail drill-down** (full HR time-series in a modal). Out of scope for the original spec; come back when basic cards are polished.
- **Weight trend sparkline** over 30 days. Currently we show a single week-delta number.
- **Sleep stage breakdown** (REM/deep/light). Google returns the stages array; we currently ignore it. Fine for v1.

### 5. Housekeeping

- After workouts become real, add a test for `list_workouts` response-shape parsing mirroring the sleep test style.
- Consider adding a `/dashboard/debug/health` read-only admin endpoint that dumps recent sync results for easier ops visibility (gated behind SSO like the rest of the dashboard).
- If you pull in the rollup endpoint for steps/calories, consider exposing the last sync result in the UI as a timestamp, for user trust.

## Test suite expectations

Baseline: 112 passing tests. Every change in `list_*` parsers needs a test update because the fixtures under `tests/fixtures/google_health/` encode the (currently placeholder) response shapes. Prefer writing the test first against a real captured response body, then rewriting the fixture to match, then updating the parser — TDD.

## Environment invariants

- `/opt/foodlog/.env` holds live secrets including a valid `FOODLOG_GOOGLE_TOKEN_KEY` (Fernet key). Don't regenerate — it's what decrypts the existing refresh token row.
- `docker-compose.yml` passes `FOODLOG_GOOGLE_TOKEN_KEY` through explicitly (one of the three places you need to edit when adding a new `Settings` field — see `~/.claude/projects/-opt-foodlog/memory/feedback_docker_env_plumbing.md`).
- Google Cloud Console is already configured: OAuth client has `https://foodlog.ryanckelly.ca/health/connect/callback` as an authorized redirect URI, Health API is enabled, scopes `googlehealth.{activity_and_fitness,health_metrics_and_measurements,sleep}.readonly` are added to the consent screen, and the user is on the test-user list. Don't touch any of this unless you're adding a new scope.
- `/opt/foodlog/.env.diagnos` contains a Cloudflare API token — unrelated to Google Health, only useful if a CF issue surfaces. `.gitignore`d.

## First move I'd recommend

Fix `workout` (exercise) parsing first. It's the data type with the biggest dashboard payoff, the user will probably record a workout soon, and doing it gives you a second working `list_*` method to reference from when you circle back to the trickier `heart-rate` and `total-calories` endpoints. Steps aggregation comes second because it has an architectural decision embedded (client-side vs rollup) that you'll want to have the rollup endpoint shape discovered first.
