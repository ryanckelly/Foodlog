# Granular Timeline View — Design Spec

**Status:** Approved 2026-05-01
**Authors:** ryan, claude
**Builds on:** `2026-04-22-foodlog-google-health-design.md` (existing daily-aggregate integration)
**Related:** `doc/HEALTH_DATA.md` (current data coverage matrix)

## Problem

Every metric FoodLog currently shows is aggregated to the day level. The dashboard tells the user *what happened today*; it doesn't tell them *when, within today*. The user wants a separate page that renders heart rate, steps, distance, floors, and active-zone minutes at 15-minute resolution across a single day, with workout context overlaid so HR and activity spikes are self-explaining.

This work is mobile-first — the user primarily views FoodLog on a phone — and includes a portrait/landscape switch where landscape becomes a single-chart immersive view.

## Goals

- Render five activity metrics at 15-minute granularity for a single calendar day on a new page.
- Default view is today; navigation is by-day (prev / next / date picker / "Today").
- Provide a deep-link entry from the existing daily dashboard's workout cards: clicking a workout opens the timeline focused on that workout's window.
- Backfill 90 days of historical data on first sync. Never prune.
- Keep the existing `/dashboard` and `workout_hr_samples` integration untouched. This is additive.

## Non-goals

- Week / month aggregate views. Single calendar day is the unit.
- User-configurable window size. Fixed at 15 minutes.
- Replacing `workout_hr_samples`. The per-second-during-workouts table stays for the daily dashboard's workout sparkline.
- Real-time / streaming updates. Same dashboard-load `BackgroundTask` model as the existing sync.
- Renpho cloud-API client for body composition. Tracked separately in `HEALTH_DATA.md` future work.
- Active-minutes (LIGHT / MODERATE / VIGOROUS). AZM (FAT_BURN / CARDIO / PEAK) covers the same intensity story via HR zones; one is enough.

## Empirical foundation

Confirmed against the live Google Health v4 API on 2026-05-01 against the user's account:

| Metric | Endpoint | rollUp at `windowSize=900s`? | Response shape |
|---|---|---|---|
| heart-rate | `/v4/users/me/dataTypes/heart-rate/dataPoints:rollUp` | yes; **omits** empty windows | `heartRate.beatsPerMinuteAvg / Min / Max` |
| steps | `/v4/users/me/dataTypes/steps/dataPoints:rollUp` | yes; emits all windows (empty `{}`) | `steps.countSum` (string-number) |
| distance | `/v4/users/me/dataTypes/distance/dataPoints:rollUp` | yes; emits all windows | `distance.millimetersSum` (string-number) |
| floors | `/v4/users/me/dataTypes/floors/dataPoints:rollUp` | yes; emits all windows | `floors.countSum` (string-number) |
| active-zone-minutes | `/v4/users/me/dataTypes/active-zone-minutes/dataPoints:rollUp` | yes; emits all windows | `activeZoneMinutes.sumInFatBurnHeartZone / sumInCardioHeartZone / sumInPeakHeartZone` |

Heart-rate has a hard **14-day max range per request** (Google docs and API behavior). The other four accept the full 90-day backfill in a single request.

The rollUp request body is:

```json
{
  "range": {"startTime": "RFC3339Z", "endTime": "RFC3339Z"},
  "windowSize": "900s"
}
```

Note this differs from the existing `dailyRollUp` body shape (which uses civil dates).

## User experience

### Route

- **`/dashboard/timeline`** — sub-route of the existing dashboard. Reuses `base.html`, the SSO gate, and the `_sync_state` machinery.
- Query params:
  - `date=YYYY-MM-DD` — the day to render. Defaults to today (server local).
  - `focus=HH:MM-HH:MM` — optional time window to highlight (used by deep-links from workout cards).

### Page layout

#### Portrait (mobile-first default)

A single shared 24-hour time axis runs across five stacked chart panels:

1. **Heart rate** — range bars from min to max BPM with an avg dot. Fixed Y-axis 40–180 BPM. Tallest panel of the five.
2. **Steps** — solid bars, auto-scaled per day.
3. **Distance** — solid bars, auto-scaled per day. Stored in meters. Y-axis label and tooltips show miles with km in parens (matching the weight card's `lbs (kg)` convention). Note: the existing workout card on `/dashboard` still shows `km` only; standardizing units project-wide is a separate, small follow-up tracked in open issues.
4. **Floors** — solid bars, auto-scaled per day.
5. **Active zone minutes** — stacked bars from bottom: fat-burn, cardio, peak. Auto-scaled per day.

Each panel is identified by a small uppercase label following `DESIGN.md` typography rules.

Annotations across all charts:

- **Workout band** — translucent salmon fill spanning the workout's start→end window, plus a label ("Walk · 47m") on the HR panel only.
- **Meal dots** — small Notion-amber dots above the time axis at each `food_entries.logged_at`. Tappable to reveal the meal name.

The page header (replacing the daily dashboard's segmented date-range control) contains:

- Prev-day chevron · day label (taps to open native `<input type="date">`) · next-day chevron · "Today" pill (only shown when `date != today`).

#### Landscape

A single CSS rule (`@media (orientation: landscape)`) swaps to a single-chart immersive layout:

- Pill strip at the top: `Heart Rate · Steps · Distance · Floors · AZM`. Tapping a pill switches the active chart.
- One full-screen chart fills the rest of the viewport.
- Same workout band + meal dot annotations, scaled up.
- The active metric is held in URL hash (`#hr`, `#steps`, etc.) so a refresh persists state.
- Switching back to portrait restores the stacked layout. No JS state coordination required between modes.

### Empty / edge states

- **Empty HR windows** (watch not worn): API omits the window, we render no bar (gap). Honest representation.
- **Empty activity windows** (watch worn but no movement): API returns `{}`; we treat as 0 and render no bar.
- **Future days**: render the empty state "No data for this day yet" — the date arrows still let you navigate back.
- **Days before the 90-day backfill**: empty state "No data for this day". The date picker stays usable.
- **First sync in progress**: render the empty state with a "Syncing…" line; HTMX poll on the partial every 5 s until data appears or the sync surface in `_sync_state` flips to error.

### Deep-link from workout cards

The existing `/dashboard` workout cards (in `movement_partial.html`) gain a small text affordance:

```
→ Timeline
```

Right-aligned in the card footer, links to:

```
/dashboard/timeline?date={workout.start_at:%Y-%m-%d}&focus={start_hhmm}-{end_hhmm}
```

When `focus` is set, the corresponding workout band is highlighted with a darker tint and a thin border. No scroll behavior — the chart is fixed-width.

## Architecture

### Storage — three new tables

Each table maps to one Google rollUp response shape. Following the existing per-domain pattern (`BodyComposition`, `RestingHeartRate`, `SleepSession`).

```python
class IntervalHeartRate(Base):
    __tablename__ = "interval_heart_rate"
    start_at: Mapped[datetime.datetime] = mapped_column(DateTime, primary_key=True)
    bpm_avg: Mapped[int] = mapped_column(Integer, nullable=False)
    bpm_min: Mapped[int] = mapped_column(Integer, nullable=False)
    bpm_max: Mapped[int] = mapped_column(Integer, nullable=False)
    source:  Mapped[str] = mapped_column(String(128), nullable=False)
    fetched_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())

class IntervalActivity(Base):
    __tablename__ = "interval_activity"
    start_at:   Mapped[datetime.datetime] = mapped_column(DateTime, primary_key=True)
    steps:      Mapped[int | None]   = mapped_column(Integer, nullable=True)
    distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    floors:     Mapped[int | None]   = mapped_column(Integer, nullable=True)
    source:     Mapped[str] = mapped_column(String(128), nullable=False)
    fetched_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())

class IntervalAzm(Base):
    __tablename__ = "interval_azm"
    start_at:     Mapped[datetime.datetime] = mapped_column(DateTime, primary_key=True)
    fat_burn_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cardio_min:   Mapped[int | None] = mapped_column(Integer, nullable=True)
    peak_min:     Mapped[int | None] = mapped_column(Integer, nullable=True)
    source:       Mapped[str] = mapped_column(String(128), nullable=False)
    fetched_at:   Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
```

`start_at` is stored UTC, naive (matching existing convention). The 15-minute alignment (:00, :15, :30, :45) is enforced by Google's response, not by us.

No Alembic migrations — schema is created via `Base.metadata.create_all()` at app startup, consistent with the existing pattern.

### Client extension — `foodlog/clients/google_health.py`

Add three new dataclasses + iterators:

```python
@dataclass(slots=True)
class HrIntervalRow:
    start_at: datetime.datetime
    bpm_avg: int
    bpm_min: int
    bpm_max: int
    source: str

@dataclass(slots=True)
class ActivityIntervalRow:
    start_at: datetime.datetime
    steps: int | None
    distance_m: float | None
    floors: int | None
    source: str

@dataclass(slots=True)
class AzmIntervalRow:
    start_at: datetime.datetime
    fat_burn_min: int | None
    cardio_min: int | None
    peak_min: int | None
    source: str
```

Add a private helper `_rollup(data_type, start, end, window_size_s)` that POSTs to `/dataPoints:rollUp` with the correct request body shape (RFC3339 `startTime`/`endTime`, not civil dates). Returns the `rollupDataPoints` list.

Three new public methods:
- `list_hr_intervals(since, until)` — splits the range into ≤14-day chunks, calls `_rollup`, yields `HrIntervalRow`.
- `list_activity_intervals(since, until)` — single rollUp call (90 d fits), yields rows where any of steps/distance/floors is non-empty. Empty `{}` results yield nothing for that window.
- `list_azm_intervals(since, until)` — same shape as activity.

### Sync extension — `foodlog/services/health_sync.py`

Add `_sync_interval_heart_rate`, `_sync_interval_activity`, `_sync_interval_azm`. Each:

1. Drains the async iterator into a list (per the project's "drain before write" rule).
2. Reads the cursor (`max(start_at)` of its table; 90 d default).
3. Upserts keyed on `start_at`.
4. Returns the upserted-rows count for `SyncResult.rows_upserted`.

Wire all three into `sync_all()` alongside the existing types.

### Router — `foodlog/api/routers/timeline.py` (new)

Single GET endpoint `/dashboard/timeline`:

1. SSO gate (reuses dashboard's existing pattern).
2. Parse `date` (defaults today) and optional `focus`.
3. Schedule the existing `_background_health_sync` as a `BackgroundTask` (subject to the shared 30s floor — opening this page also keeps the daily-dashboard data fresh).
4. Query the three interval tables for `WHERE start_at >= start_of_day AND start_at < start_of_day + 1d`.
5. Query existing `workouts` and `food_entries` for the same day → marker data.
6. Render `dashboard/timeline.html`.

The query for the day's metrics is a 3-way LEFT JOIN on `start_at`, returning ≤96 rows.

### Templates

- `foodlog/templates/dashboard/timeline.html` — extends `base.html`, includes the timeline header (date nav) and the partial.
- `foodlog/templates/dashboard/timeline_partial.html` — the five chart panels, the markers, the landscape pill strip.

The chart bars are pure HTML/CSS (no SVG, no JS chart lib). 96 `<span>`s per chart with `style="height:N%"`. This matches the existing project pattern (the workout HR sparkline in `movement_partial.html` is already done this way).

CSS additions co-locate with existing dashboard styles in `base.html` (inline `<style>` block). Existing tokens of relevance: `--accent: #0075de`, `--meal-breakfast: #dd5b00`, `--meal-lunch: #1aae39`, `--meal-dinner: #391c57`, `--meal-snack: #2a9d99`, `--bg-sunk: #f6f5f4`, `--ink-soft`, `--muted`.

Add a new set of metric-specific tokens (so meal colors and metric colors don't collide):

```css
--metric-hr:        #c75e3c;  /* deeper Notion orange/salmon, distinct from meal-breakfast */
--metric-hr-soft:   rgba(199, 94, 60, 0.12);   /* HR range bar fill, workout band */
--metric-steps:     var(--accent);              /* Notion Blue, the existing UI accent */
--metric-distance:  #5a8e7c;                    /* muted teal-green; reads as movement */
--metric-floors:    #b88e54;                    /* warm tan; vertical, earthy */
--metric-azm-light: rgba(199, 94, 60, 0.45);    /* fat-burn */
--metric-azm-mid:   rgba(199, 94, 60, 0.75);    /* cardio */
--metric-azm-peak:  #c75e3c;                    /* peak, full saturation */
--marker-meal:      var(--meal-breakfast);      /* meal dots reuse breakfast orange */
```

Workout band is `--metric-hr-soft` (HR's translucent fill); meal dots use `--marker-meal`.

### Workout card affordance

In `foodlog/templates/dashboard/movement_partial.html`, the workout card gets a footer link:

```html
<a class="mv-card-link" href="/dashboard/timeline?date={{ w.start_at.date() }}&focus={{ w.start_at.strftime('%H:%M') }}-{{ w.end_at.strftime('%H:%M') }}">→ Timeline</a>
```

Right-aligned, small font, tertiary text color.

### Doc update

`doc/HEALTH_DATA.md`'s "What we currently collect" master table gets three new rows:

| Metric | Device | API type | Granularity stored | Look-back per sync | Table |
|---|---|---|---|---|---|
| Heart rate (sub-day) | Pixel Watch | `heart-rate` rollUp `900s` | 15-min avg/min/max | Cursor; chunks 14d slices; 90d on empty | `interval_heart_rate` |
| Activity intervals | Pixel Watch | `steps`/`distance`/`floors` rollUp `900s` | 15-min counters | Cursor; 90d on empty | `interval_activity` |
| AZM intervals | Pixel Watch | `active-zone-minutes` rollUp `900s` | 15-min by HR zone | Cursor; 90d on empty | `interval_azm` |

## Testing

### `tests/test_google_health_client.py` extension

Use existing `respx` pattern with new fixtures in `tests/fixtures/google_health/`:

- `hr_rollup.json`, `activity_rollup.json`, `azm_rollup.json` — minimal but representative responses.
- Test `list_hr_intervals` chunks a 30-day range into three 14-day requests.
- Test that empty windows (`{}`) yield no row from `list_activity_intervals`.
- Test that string-numbers (`"countSum": "251"`) parse to ints.

### `tests/test_health_sync.py` extension

- Mock all three rollUp endpoints with respx.
- Assert `_sync_interval_*` methods upsert idempotently (run twice, row count unchanged).
- Assert syncing one table doesn't mutate the others.
- Assert cursor advances on second run.

### `tests/test_timeline.py` (new)

- Render `/dashboard/timeline` with a seeded day of interval data; assert the markup contains the right number of bar `<span>`s and the correct heights.
- Render with `?focus=12:00-12:45`; assert the workout band markup carries a "focused" class.
- Render an empty day; assert the empty state text appears.
- Render a workout card on `/dashboard/feed`; assert the new "→ Timeline" link is present and points to the correct deep-link URL.

## Risks and open issues

- **Sleep-only HR days look empty in the chart's bottom third** — accepted trade-off for cross-day HR comparability.
- **Initial 90-day backfill** runs in a `BackgroundTask` so the page never blocks, but the user may briefly see an empty state on first connection until the first sync completes (~10–20 s).
- **The 14-day HR chunk boundary** is a pre-existing Google constraint, not a bug. Documented in `HEALTH_DATA.md`.
- **Bar charts as 96 stacked `<span>`s** is fine on mobile but won't degrade gracefully if we ever want hover tooltips with absolute values; that's a paving stone for later.
- **Landscape mode on iOS Safari** — `@media (orientation: landscape)` is well-supported but the user should sanity-check on their actual phone after first deploy.
- **Unit standardization** — weight uses `lbs (kg)`, distance on this page will use `mi (km)`, but the existing workout card still shows `km`. Aligning the workout card is a separate small change; not in scope for this spec.

## Files changed

**New:**
- `foodlog/api/routers/timeline.py`
- `foodlog/templates/dashboard/timeline.html`
- `foodlog/templates/dashboard/timeline_partial.html`
- `tests/test_timeline.py`
- `tests/fixtures/google_health/hr_rollup.json`
- `tests/fixtures/google_health/activity_rollup.json`
- `tests/fixtures/google_health/azm_rollup.json`

**Modified:**
- `foodlog/db/models.py` — three new model classes
- `foodlog/clients/google_health.py` — three new methods, three new dataclasses, `_rollup` helper
- `foodlog/services/health_sync.py` — three new sync methods, wired into `sync_all`
- `foodlog/api/app.py` — register the timeline router
- `foodlog/templates/dashboard/movement_partial.html` — add "→ Timeline" affordance to workout card
- `foodlog/templates/dashboard/styles.css` (or wherever dashboard CSS lives) — new chart classes + landscape media query
- `tests/test_google_health_client.py` — new test cases
- `tests/test_health_sync.py` — new test cases
- `doc/HEALTH_DATA.md` — three new rows in master table
