# FoodLog Dashboard

FoodLog includes a local web dashboard to view daily food logs, caloric intake, macronutrients, and trends.

## Access

The dashboard is gated by Google Single Sign-On (SSO). When SSO is configured via environment variables (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `FOODLOG_SESSION_SECRET_KEY`, `FOODLOG_AUTHORIZED_EMAIL`, plus `FOODLOG_PUBLIC_BASE_URL`), any unauthenticated request to `/dashboard` or `/dashboard/feed` redirects to `/login`, which starts the Google OAuth flow. On return, `/auth/callback` verifies the authenticated Google email case-insensitively matches `FOODLOG_AUTHORIZED_EMAIL` and installs a signed session cookie (Starlette's `SessionMiddleware` + `itsdangerous`). Only the single authorized email can reach the dashboard.

When SSO is *not* configured (any of the required env vars missing), the dashboard falls back to being open — intended for local development only. The app emits a startup warning to the logs in this case so the operator sees the misconfiguration.

Docker Compose binds port `3474` to all interfaces so the dashboard is reachable on the LAN at `http://<host>:3474/dashboard`. On the public Cloudflare Tunnel, `https://foodlog.ryanckelly.ca/dashboard` routes to the same gate. Either way, the SSO check enforces the single-user policy.

To log out, visit `/logout` — the session key is cleared and you're redirected to `/dashboard`, which then redirects back to `/login` if SSO is configured.

## Architecture

The dashboard is built directly into the existing FastAPI backend using Server-Side Rendering (SSR) to prioritize simplicity and zero external build dependencies:

* **HTML Templating:** Jinja2 templates (`foodlog/templates/`) rendered on the server.
* **Interactivity:** HTMX for dynamic content updates (like changing date ranges) without full page reloads.
* **Styling:** Inline CSS in `base.html` driven by CSS custom properties, with Inter loaded from Google Fonts. The visual language is a Notion-inspired design system — full spec in `DESIGN.md` at the repo root. When changing palette, typography, or component patterns, update `DESIGN.md` alongside the templates so the spec stays authoritative.

## How it Accesses Data

The dashboard does not use a separate client-side API layer. Instead, the Jinja2 routes in `foodlog/api/routers/dashboard.py` directly instantiate the existing internal domain services (`EntryService` and `SummaryService`) from `foodlog/services/`, passing in the SQLAlchemy database session provided by FastAPI's dependency injection (`Depends(get_db)`).

1. **Routing:** A request hits `/dashboard/feed?date_range=today`.
2. **Service Call:** The router converts the `date_range` into `start_date` and `end_date` objects. It then calls `entry_svc.get_by_range(start_date, end_date)` and `summary_svc.range(start_date, end_date)`.
3. **Data Grouping:** The router groups the returned `FoodEntry` objects by meal type and time (consecutive items of the same meal logged within 5 minutes of each other).
4. **Template Rendering:** The router returns a `TemplateResponse` mapping to `dashboard/feed_partial.html`, passing the `grouped_entries` and `summary` data.
5. **Jinja2:** The template iterates over the grouped entries and renders the HTML, applying specific CSS classes to color-code meals (e.g., `.meal-breakfast`, `.meal-lunch`).

This architecture ensures the dashboard shares the exact same business logic and data persistence layer as the REST API and the MCP endpoint.

## Google Health (Movement & Recovery)

The dashboard can surface Pixel Watch / Renpho data alongside meals via the Google Health API. The integration is opt-in, on-presence (no background scheduler), and uses the same Google OAuth client as SSO.

### Setup

1. Set `FOODLOG_GOOGLE_TOKEN_KEY` in `.env`. Generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. This encrypts the refresh token at rest.
2. In Google Cloud Console, add `${FOODLOG_PUBLIC_BASE_URL}/health/connect/callback` as an authorized redirect URI on the existing SSO OAuth client, enable the Google Health API, and add the three `googlehealth.*.readonly` scopes to the consent screen.
3. After SSO login, click **Connect Google Health** on the dashboard. The callback persists an encrypted refresh token in the singleton `google_oauth_token` row.
4. Confirm the `DATA_TYPES` identifiers in `foodlog/clients/google_health.py` against the live Google Health REST API reference before the first real sync — the defaults are placeholders.

### Flow

* `/dashboard/feed` checks `google_health_configured` and the presence of the `google_oauth_token` row. If configured but unconnected, it renders `dashboard/health_connect.html` instead of the meals feed.
* If the stored refresh token is older than `REAUTH_AGE_DAYS` (5) it returns an empty body with `HX-Redirect: /health/connect` so the dashboard bounces through Google for a silent re-consent before Google's 7-day Testing-mode wall.
* Otherwise it mints an access token, runs `HealthSyncService.sync_all()`, then renders the **Movement & Recovery** section from local DB rows (`daily_activity`, `body_composition`, `resting_heart_rate`, `sleep_sessions`, `workouts`, `workout_hr_samples`). A net-calories badge appears in the summary when active calories are present.
* `TokenInvalid` / `TokenMissing` → reconnect banner. Transient Google errors on non-brittle types → "data may be stale" flag but the section still renders from cached DB data. Errors on brittle types (currently: `sleep_sessions`) are logged at INFO and do **not** flip the stale banner — see below.

Session gate: `/health/connect` and `/health/connect/callback` require an active SSO session and reject any Google identity that doesn't match `FOODLOG_AUTHORIZED_EMAIL`.

### Per-type request style (source of truth in `foodlog/clients/google_health.py`)

Google's v4 data types split across two endpoint styles and require careful filter-grammar choices. Discovered empirically against the live API on 2026-04-24:

| Type | Endpoint | Request style | Filter field (if `list`) | Notes |
|---|---|---|---|---|
| `daily_steps` | `steps` | `:dailyRollUp` POST | n/a | Returns `steps.countSum` (string) per civil day. `list` action returns minute-level samples — don't use for daily totals. |
| `daily_active_calories` | `total-calories` | `:dailyRollUp` POST | n/a | Returns `totalCalories.kcalSum` (float) per civil day. `list` action is **unsupported** by Google. |
| `body_weight` | `weight` | `list` GET | `weight.sample_time.civil_time` | Value at `weight.weightGrams` — divide by 1000 for kg. |
| `body_fat` | `body-fat` | `list` GET | `body_fat.sample_time.civil_time` | Value at `bodyFat.percentage`. |
| `resting_heart_rate` | `daily-resting-heart-rate` | `list` GET | `daily_resting_heart_rate.date` | Value at `dailyRestingHeartRate.beatsPerMinute`. |
| `heart_rate_sample` | `heart-rate` | `list` GET | `heart_rate.sample_time.physical_time` | Value at `heartRate.beatsPerMinute`. |
| `sleep_session` | `sleep` | `list` GET | `sleep.interval.civil_end_time` | Brittle — Google 500s intermittently; marked brittle in `sync_all`. |
| `workout` | `exercise` | `list` GET | `exercise.interval.civil_start_time` | No max-HR aggregate; derived from HR samples. `displayName` preferred over `exerciseType` for UI. |

**Filter-grammar gotcha:** the filter path prefix uses the **snake_case** form of the data type name (`body_fat`, `heart_rate`, `daily_resting_heart_rate`, `total_calories`), **not** camelCase. Google's docs are misleading on this — camelCase prefixes return `INVALID_DATA_POINT_FILTER_DATA_TYPE_MEMBER`. `FILTER_FIELDS` in the client is the single source of truth.

### Concurrency notes

* `HealthSyncService` methods **drain each async iterator into a list before opening a write transaction**. Holding a SQLite write transaction across Google HTTP calls caused `OperationalError: database is locked` when two dashboard requests overlapped. Keep this pattern if you add new per-type methods.
* Heart-rate samples paginate at ~50 per page. For any workout whose HR samples are already in DB, `_sync_workouts_with_hr` skips the refetch — otherwise a single dashboard hit can spawn dozens of HTTP calls per workout.
* Sleep cursor uses a fixed 3-day look-back instead of `cursor_for()`. The list endpoint 500s intermittently on this account for wider windows; narrower is safer and upserts are idempotent.
