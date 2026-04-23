# FoodLog Google Health Integration Design

## Overview

Pull the user's Pixel Watch and Renpho scale data from the Google Health API (the replacement for the legacy Fitbit Web API, deprecated September 2026) into the FoodLog dashboard so meals can be viewed alongside activity, sleep, body composition, and heart-rate signals. Single user, personal OAuth app, "Testing" publishing status, no verification review.

Data is fetched on-presence — when the user loads the dashboard — not by a background scheduler. This collapses the OAuth architecture because the user is always available to re-consent when tokens expire.

## Relationship to the Google SSO Spec

The Google SSO spec (`2026-04-20-foodlog-google-sso-design.md`) and this spec are **independent**. Both use Google OAuth, but:

| | SSO (`openid email profile`) | Health (`googlehealth.*`) |
|---|---|---|
| Purpose | Identity gate for `/dashboard` | Offline access to fitness/health data |
| Token lifecycle | Session cookie only; no refresh token stored | Refresh token persisted server-side |
| 7-day expiry | Exempt (SSO-only scopes are allowed long-lived) | Bound by Google's 7-day limit in Testing mode |
| User presence | Required at login | Required at dashboard load (our design choice) |
| Consent screen | Once per cookie session | Once per ~7-day refresh token window |

Keeping them separate means:
- The SSO plan ships first, unchanged. Nothing in this spec modifies it.
- A separate "Connect Google Health" button lives on the dashboard. It kicks off its own OAuth flow with its own callback, its own token storage, and its own consent screen.
- Revoking either grant does not affect the other.

## Architecture

### On-Presence Fetch Pattern

No background scheduler. No APScheduler. No cron-in-container. The ingestion pipeline runs inside the HTMX handler that renders the dashboard feed partial.

```
Browser → GET /dashboard/feed
          ↓
      feed handler:
        1. Check google_oauth_token row. If missing → render "Connect Google Health" prompt.
        2. If token issued_at is > 5 days old → redirect to /health/connect (opportunistic re-auth).
        3. Use refresh token → mint access token.
        4. Fetch per-type data from Google Health API (only windows we don't have yet).
        5. Upsert into per-type tables on external_id.
        6. Render meals + movement & recovery sections from local DB.
```

If step 3 returns `invalid_grant`, the handler returns a banner prompting the user to reconnect (a 401 branch in HTMX). Step 4 failures (429, 5xx) return cached DB data with a "data may be stale" flag.

### OAuth Client

A **second** Google OAuth 2.0 Client registered separately from the SSO client, so the two surfaces can be enabled/disabled independently, tokens revoked independently, and consent screens reasoned about independently.

Scopes requested (all read-only):
- `https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly` — steps, active calories, workouts
- `https://www.googleapis.com/auth/googlehealth.health_metrics_and_measurements.readonly` — weight, body fat, resting HR, workout HR samples
- `https://www.googleapis.com/auth/googlehealth.sleep.readonly` — sleep sessions

Authorization request uses `access_type=offline` to get a refresh token. `prompt=consent` is used on the initial connect but omitted on opportunistic re-auth so Google can silently issue a new refresh token when the existing session already has the grant.

### Token Storage

New table `google_oauth_token` holds a single row (single-user app). The refresh token is encrypted at rest using Fernet with a new env var `FOODLOG_GOOGLE_TOKEN_KEY`.

```
google_oauth_token(
  id INTEGER PK DEFAULT 1 CHECK (id = 1),  -- singleton
  refresh_token_encrypted TEXT NOT NULL,
  scopes_json TEXT NOT NULL,
  issued_at TIMESTAMP NOT NULL,
  last_used_at TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
```

Access tokens are never stored — they're minted on demand per request, held in a request-scoped variable, discarded.

### Handling the 7-Day Expiry

Google's Testing-mode policy expires refresh tokens 7 days after issuance. Mitigation: opportunistic re-auth at ~5 days.

- On each dashboard load, if `now - issued_at > 5 days`, the dashboard redirects through `/health/connect` before attempting to fetch.
- Google typically fulfills this redirect silently (the user already has an active Google session and an existing grant) — no user interaction, one redirect bounce.
- If the user is gone longer than 7 days, the refresh token has expired: the dashboard shows a "Reconnect Google Health" banner, one click runs the flow with `prompt=consent`.

## Data Model

Six tables, all in the existing SQLite database, all managed via `Base.metadata.create_all()` consistent with the current project convention (no Alembic).

```
daily_activity(
  date DATE PRIMARY KEY,
  steps INTEGER NOT NULL,
  active_calories_kcal REAL NOT NULL,
  source TEXT NOT NULL,        -- Google data source id / package name
  external_id TEXT NOT NULL,
  fetched_at TIMESTAMP NOT NULL
)

body_composition(
  measured_at TIMESTAMP NOT NULL,
  source TEXT NOT NULL,
  weight_kg REAL,
  body_fat_pct REAL,
  external_id TEXT NOT NULL,
  fetched_at TIMESTAMP NOT NULL,
  PRIMARY KEY (external_id)
)

resting_heart_rate(
  measured_at TIMESTAMP NOT NULL,
  source TEXT NOT NULL,
  bpm INTEGER NOT NULL,
  external_id TEXT NOT NULL,
  fetched_at TIMESTAMP NOT NULL,
  PRIMARY KEY (external_id)
)

sleep_sessions(
  external_id TEXT PRIMARY KEY,
  start_at TIMESTAMP NOT NULL,
  end_at TIMESTAMP NOT NULL,
  duration_min INTEGER NOT NULL,
  source TEXT NOT NULL,
  fetched_at TIMESTAMP NOT NULL
)

workouts(
  external_id TEXT PRIMARY KEY,
  start_at TIMESTAMP NOT NULL,
  end_at TIMESTAMP NOT NULL,
  activity_type TEXT NOT NULL,    -- "run", "strength", etc.
  duration_min INTEGER NOT NULL,
  calories_kcal REAL,
  distance_m REAL,
  avg_hr INTEGER,
  max_hr INTEGER,
  source TEXT NOT NULL,
  fetched_at TIMESTAMP NOT NULL
)

workout_hr_samples(
  workout_id TEXT NOT NULL REFERENCES workouts(external_id) ON DELETE CASCADE,
  sample_at TIMESTAMP NOT NULL,
  bpm INTEGER NOT NULL,
  PRIMARY KEY (workout_id, sample_at)
)
```

**Timestamps:** All stored as UTC. Dashboard converts to the server's local timezone at render time (consistent with current behavior).

**The `source` column:** free-text string holding the Google data source identifier or application package name (e.g., `"com.caliber.android"`, `"com.google.android.wearable.app"`, `"com.renpho.fit"`). We capture this distinctly so that post-launch we have evidence to design a dedup rule if duplicate workouts appear (see Open Items).

**Idempotency:** Every table uses `external_id` (Google's resource identifier) as the dedupe key. Upserts use `INSERT ... ON CONFLICT(external_id) DO UPDATE SET ...`. Re-fetching the same window produces identical rows.

## Ingestion Strategy

### First-Fetch (Connect Moment)

When the user first connects Google Health, fetch the last **90 days** for every data type. This is enough to populate weekly weight trends and give workout/sleep charts meaningful content without making the connect step slow. Runs synchronously during the `/health/connect/callback` handler; user sees a "Syncing your data…" progress page.

### Incremental Cursor (Per Dashboard Load)

Each data type has its own watermark, derived from the data's own timestamp rather than `fetched_at` (robust against clock skew and late-arriving samples):

| Table | Cursor query | Fetch window |
|---|---|---|
| `daily_activity` | Always re-fetch today + yesterday | 2 days |
| `body_composition` | `SELECT max(measured_at) FROM body_composition` | `> cursor` to now |
| `resting_heart_rate` | `SELECT max(measured_at) FROM resting_heart_rate` | `> cursor` to now |
| `sleep_sessions` | `SELECT max(start_at) FROM sleep_sessions` | `> cursor` to now |
| `workouts` | `SELECT max(start_at) FROM workouts` | `> cursor` to now |
| `workout_hr_samples` | Pulled alongside parent workout | n/a |

Daily activity is always refreshed for today and yesterday because the watch reports late-arriving samples for partial days. Upserts handle the re-write idempotently.

### Rate Limiting & Failures

- **429:** Return cached DB data, render with a small "data may be stale (rate-limited)" flag near the Movement & Recovery section head. No retries in-request.
- **5xx:** Same as 429.
- **`invalid_grant` on refresh:** Show the reconnect banner.
- **Any other auth error:** Log, render with stale flag.

No retry loops inside the request. The next dashboard load is the retry.

## Dashboard Surfacing — Option B

The existing meals section stays as-is. A new **Movement & Recovery** section appears below it. The summary strip gains a compact net-calories badge.

```
┌─ FoodLog · Wed, Apr 22 ·  [Today] [Yesterday] [7 days] ─┐
│                                                          │
│  1,842 kcal     [ net −368 · burned 2,210 ]              │
│  ████████░░░░  (P/C/F bar)                               │
│                                                          │
│  Meals                                                    │
│  ● Breakfast  8:14 am  420                               │
│  ● Lunch     12:47 pm  612                               │
│  ● Dinner     7:05 pm  810                               │
│                                                          │
│  Movement & Recovery                                      │
│  ┌─ Run · 6.8 km ─┐ ┌─ Sleep ──────┐ ┌─ Weight ────────┐ │
│  │ 42 min         │ │ 6h 27m       │ │ 81.4 kg         │ │
│  │ ▄▆██▇█▇▆▄▂    │ │ below 7h     │ │ −0.3 kg / week  │ │
│  │ 410 · 152 avg  │ │ RHR 58       │ │ body fat 19.2%  │ │
│  └────────────────┘ └──────────────┘ └─────────────────┘ │
└──────────────────────────────────────────────────────────┘
```

- **Net-calories badge** (`net −368 · burned 2,210`) is a pill badge using the existing `.fl-badge-accent` style: tinted blue bg, darker blue text.
- **Workout card** shows activity type as a text label, duration, a tiny HR spark chart (inline CSS bars using `workout_hr_samples`), calories + avg HR. Clicking the workout card can later open a detail modal with the full HR time series — out of scope for this spec.
- **Sleep card** shows total duration + whether it hit the 7h target, plus resting HR alongside for context.
- **Weight card** shows current weight + 7-day delta + body fat %.
- All cards use the existing Notion-inspired card style from `DESIGN.md` (whisper border, 12px radius, 4-layer shadow).
- **Color usage:** All three cards are neutral (white bg, near-black text, warm gray secondary). The meal dot accent colors (orange/green/purple/teal) stay reserved for meal types — workout cards do not reuse them to avoid cross-category confusion. The HR spark chart uses Notion Blue (`#0075de`) at 0.75 opacity, consistent with the single-accent philosophy.

If no data for the selected range, the section header renders with an empty-state line "No movement or recovery data for this period."

Styling follows `DESIGN.md` tokens — no new colors, no new type families.

## New Modules

- `foodlog/clients/google_health.py` — thin HTTP client wrapping the Google Health API endpoints we use.
- `foodlog/services/health_sync.py` — orchestrates the fetch → upsert pipeline, one entry point called by the dashboard feed handler.
- `foodlog/services/google_token.py` — encrypts/decrypts the refresh token; mints access tokens; handles re-auth detection.
- `foodlog/api/routers/health_oauth.py` — `/health/connect` and `/health/connect/callback` routes.
- `foodlog/db/models.py` — six new SQLAlchemy models.
- Templates:
  - `templates/dashboard/movement_partial.html` — new partial rendered by `/dashboard/feed`.
  - `templates/dashboard/health_connect.html` — full-page connect prompt for the unconnected state.

## Configuration

New environment variables (added to `.env.example`):
- `GOOGLE_HEALTH_CLIENT_ID` — OAuth 2.0 client id for the Health-scoped app (distinct from `GOOGLE_CLIENT_ID` used for SSO).
- `GOOGLE_HEALTH_CLIENT_SECRET` — client secret.
- `FOODLOG_GOOGLE_TOKEN_KEY` — Fernet key for encrypting the refresh token at rest.

Health settings join `foodlog/config.py`:
```python
google_health_client_id: str = ""
google_health_client_secret: str = ""
foodlog_google_token_key: str = ""

@property
def google_health_configured(self) -> bool:
    return bool(
        self.google_health_client_id
        and self.google_health_client_secret
        and self.foodlog_google_token_key
    )
```

## Testing

- **httpx client:** mocked with `respx` + recorded fixtures under `tests/fixtures/google_health/*.json`. No live Google calls in CI.
- **OAuth flow:** `respx` mocks for the `/token` and authorization endpoints; verify refresh token is encrypted on write, decrypted on read.
- **Ingestion:** test each per-type upsert path with fixture responses and assert idempotency (run twice, same row count).
- **Dashboard partial:** render-only tests following the pattern of `tests/test_dashboard_render.py`; assert the Movement & Recovery section appears when data is present and is absent (or empty-state) when not.
- **Token expiry handling:** test that a 5-day-old token triggers redirect to `/health/connect`, test that `invalid_grant` from Google triggers the reconnect banner.

## Non-Goals

Explicitly out of scope for this spec:
- **Manual workout entry in FoodLog.** Workouts only arrive from Google.
- **Workout detail page / full HR time series view.** Cards show spark chart summaries. Drill-down is a future spec.
- **GPS routes / map tiles.** `googlehealth.location.readonly` scope is not requested.
- **Sleep stages (REM/deep/light breakdown).** Only total duration.
- **Google Fit nutrition import.** FoodLog is the source of truth for nutrition.
- **Cross-device deduplication logic** (Caliber ↔ Pixel Watch). See Open Items.
- **Background/scheduled polling.** On-presence only.
- **Publishing / verification of the OAuth app.** Stays in Testing mode.
- **Multi-user support.** Single-row token table enforces this.
- **Profile data** (age, height). Hardcoded or re-use existing user info if needed.

## Open Items (Post-Launch)

- **Duplicate workout detection:** Caliber app syncs workouts to Google Health; Pixel Watch may auto-detect the same workout. Whether Google's backend dedupes for us, whether one always wins, or whether we get duplicates is unknown until we look at real data. The `source` column captures enough provenance to design a dedup rule after first exposure. Diagnostic task: after first-sync, inspect `workouts` for time-overlapping rows with different `source`.
- **Workout detail drill-down:** Spark chart is a preview; a click-to-expand full HR time-series view is deferred.
- **Weight trend chart:** Currently showing a single week-delta number. A sparkline over the last 30 days would be a small follow-up.
- **Stale-data badge copy:** When 429/5xx returns cached data, exact wording of the "data may be stale" indicator TBD when we see the UI.
