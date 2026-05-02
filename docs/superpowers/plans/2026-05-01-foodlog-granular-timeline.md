# Granular Timeline View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a `/dashboard/timeline` page that renders heart rate, steps, distance, floors, and active-zone-minutes at 15-minute resolution for a single calendar day, with workout bands and meal dots overlaid, plus a CSS-only portrait/landscape layout swap.

**Architecture:** Three new SQLAlchemy tables back the rollUp data (one per Google response shape: `interval_heart_rate`, `interval_activity`, `interval_azm`). The existing `GoogleHealthClient` gains a private `_rollup` helper and three public iterators. `HealthSyncService.sync_all()` calls three new sync methods that drain iterators then upsert. A new FastAPI router renders Jinja templates that draw bar charts as 96 inline `<span>` elements per panel — no chart libraries, matching the existing workout-sparkline pattern. Workouts and meals from existing tables overlay as bands and dots. Landscape mode uses `@media (orientation: landscape)` to swap to a single-chart immersive view with metric pills.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0, Pydantic, httpx, Jinja2, HTMX, respx (test mocking), pytest. Schema via `Base.metadata.create_all()` at app startup — no Alembic. Inline CSS in `base.html` (`<style>` block).

**Spec:** `docs/superpowers/specs/2026-05-01-foodlog-granular-timeline-design.md`

---

## File Structure

**Create:**
- `foodlog/api/routers/timeline.py` — single GET route, builds view data, renders template
- `foodlog/templates/dashboard/timeline.html` — extends `base.html`, contains header + chart container
- `foodlog/templates/dashboard/timeline_partial.html` — five panels + markers + landscape pills
- `tests/test_timeline.py` — route + rendering tests
- `tests/fixtures/google_health/hr_rollup.json` — 4-window HR fixture
- `tests/fixtures/google_health/activity_rollup.json` — 4-window activity fixture
- `tests/fixtures/google_health/azm_rollup.json` — 4-window AZM fixture

**Modify:**
- `foodlog/db/models.py` — add `IntervalHeartRate`, `IntervalActivity`, `IntervalAzm`
- `foodlog/clients/google_health.py` — add `_rollup` helper, three dataclasses, three iterators
- `foodlog/services/health_sync.py` — add three `_sync_interval_*` methods, wire into `sync_all`
- `foodlog/api/app.py` — register the new timeline router
- `foodlog/templates/base.html` — new `--metric-*` CSS tokens
- `foodlog/templates/dashboard/movement_partial.html` — add "→ Timeline" link in workout card footer
- `foodlog/api/routers/dashboard.py` — small refactor: expose `schedule_health_sync(background_tasks)` for reuse from timeline.py
- `tests/test_google_health_client.py` — new test cases
- `tests/test_health_sync.py` — new test cases
- `doc/HEALTH_DATA.md` — three new rows in master table

---

## Naming reference (locked in)

| Concept | Name |
|---|---|
| Models | `IntervalHeartRate`, `IntervalActivity`, `IntervalAzm` |
| Tables | `interval_heart_rate`, `interval_activity`, `interval_azm` |
| Dataclasses | `HrIntervalRow`, `ActivityIntervalRow`, `AzmIntervalRow` |
| Client iterators | `list_hr_intervals`, `list_activity_intervals`, `list_azm_intervals` |
| Client helper | `_rollup(data_type, since, until, window_size_s) -> list[dict]` |
| Sync methods | `_sync_interval_heart_rate`, `_sync_interval_activity`, `_sync_interval_azm` |
| Route | `/dashboard/timeline` |

---

### Task 1: Add three SQLAlchemy models

**Files:**
- Modify: `foodlog/db/models.py` (append after the existing `WorkoutHrSample` class)

- [ ] **Step 1: Append model classes**

```python
class IntervalHeartRate(Base):
    __tablename__ = "interval_heart_rate"

    start_at:   Mapped[datetime.datetime] = mapped_column(DateTime, primary_key=True)
    bpm_avg:    Mapped[int] = mapped_column(Integer, nullable=False)
    bpm_min:    Mapped[int] = mapped_column(Integer, nullable=False)
    bpm_max:    Mapped[int] = mapped_column(Integer, nullable=False)
    source:     Mapped[str] = mapped_column(String(128), nullable=False)
    fetched_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )


class IntervalActivity(Base):
    __tablename__ = "interval_activity"

    start_at:   Mapped[datetime.datetime] = mapped_column(DateTime, primary_key=True)
    steps:      Mapped[int | None]   = mapped_column(Integer, nullable=True)
    distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    floors:     Mapped[int | None]   = mapped_column(Integer, nullable=True)
    source:     Mapped[str] = mapped_column(String(128), nullable=False)
    fetched_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )


class IntervalAzm(Base):
    __tablename__ = "interval_azm"

    start_at:     Mapped[datetime.datetime] = mapped_column(DateTime, primary_key=True)
    fat_burn_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cardio_min:   Mapped[int | None] = mapped_column(Integer, nullable=True)
    peak_min:     Mapped[int | None] = mapped_column(Integer, nullable=True)
    source:       Mapped[str] = mapped_column(String(128), nullable=False)
    fetched_at:   Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
```

- [ ] **Step 2: Verify schema creation succeeds**

Run: `pytest tests/conftest.py -v` (the in-memory `Base.metadata.create_all` runs as part of every test fixture setup; if it errors the suite breaks).

Or: `python -c "from foodlog.db.models import Base; from sqlalchemy import create_engine; Base.metadata.create_all(create_engine('sqlite:///:memory:'))"`

Expected: no exception.

- [ ] **Step 3: Commit**

```bash
git add foodlog/db/models.py
git commit -m "feat(db): add IntervalHeartRate / IntervalActivity / IntervalAzm tables"
```

---

### Task 2: Add JSON test fixtures

**Files:**
- Create: `tests/fixtures/google_health/hr_rollup.json`
- Create: `tests/fixtures/google_health/activity_rollup.json`
- Create: `tests/fixtures/google_health/azm_rollup.json`

These mirror the live API response shapes captured in the design spec on 2026-04-12 walk window.

- [ ] **Step 1: Write hr_rollup.json**

```json
{
  "rollupDataPoints": [
    {"startTime": "2026-04-12T11:50:00Z", "endTime": "2026-04-12T12:05:00Z", "heartRate": {"beatsPerMinuteAvg": 102.3, "beatsPerMinuteMax": 121, "beatsPerMinuteMin": 88}},
    {"startTime": "2026-04-12T12:05:00Z", "endTime": "2026-04-12T12:20:00Z", "heartRate": {"beatsPerMinuteAvg": 112.0, "beatsPerMinuteMax": 161, "beatsPerMinuteMin": 89}},
    {"startTime": "2026-04-12T12:20:00Z", "endTime": "2026-04-12T12:35:00Z", "heartRate": {"beatsPerMinuteAvg": 115.4, "beatsPerMinuteMax": 145, "beatsPerMinuteMin": 84}},
    {"startTime": "2026-04-12T12:35:00Z", "endTime": "2026-04-12T12:50:00Z", "heartRate": {"beatsPerMinuteAvg": 118.2, "beatsPerMinuteMax": 143, "beatsPerMinuteMin": 86}}
  ]
}
```

- [ ] **Step 2: Write activity_rollup.json**

Notice the API returns string-numbers for `countSum` / `millimetersSum` and emits empty `{}` blocks for windows with no data — both behaviors must be preserved in the fixture so parsers are tested against reality.

```json
{
  "rollupDataPoints": [
    {"startTime": "2026-04-12T11:50:00Z", "endTime": "2026-04-12T12:05:00Z", "steps": {"countSum": "649"}, "distance": {"millimetersSum": "420268"}, "floors": {}},
    {"startTime": "2026-04-12T12:05:00Z", "endTime": "2026-04-12T12:20:00Z", "steps": {"countSum": "792"}, "distance": {"millimetersSum": "628500"}, "floors": {"countSum": "3"}},
    {"startTime": "2026-04-12T12:20:00Z", "endTime": "2026-04-12T12:35:00Z", "steps": {"countSum": "1215"}, "distance": {"millimetersSum": "854000"}, "floors": {"countSum": "1"}},
    {"startTime": "2026-04-12T12:35:00Z", "endTime": "2026-04-12T12:50:00Z", "steps": {"countSum": "1462"}, "distance": {"millimetersSum": "1133000"}, "floors": {"countSum": "5"}},
    {"startTime": "2026-04-12T13:00:00Z", "endTime": "2026-04-12T13:15:00Z", "steps": {}, "distance": {}, "floors": {}}
  ]
}
```

The fifth element is an "all-empty" window — parser must skip it.

- [ ] **Step 3: Write azm_rollup.json**

```json
{
  "rollupDataPoints": [
    {"startTime": "2026-04-12T11:50:00Z", "endTime": "2026-04-12T12:05:00Z", "activeZoneMinutes": {"sumInFatBurnHeartZone": "3"}},
    {"startTime": "2026-04-12T12:05:00Z", "endTime": "2026-04-12T12:20:00Z", "activeZoneMinutes": {"sumInFatBurnHeartZone": "8"}},
    {"startTime": "2026-04-12T12:20:00Z", "endTime": "2026-04-12T12:35:00Z", "activeZoneMinutes": {"sumInFatBurnHeartZone": "1"}},
    {"startTime": "2026-04-12T12:35:00Z", "endTime": "2026-04-12T12:50:00Z", "activeZoneMinutes": {"sumInFatBurnHeartZone": "12", "sumInCardioHeartZone": "2"}},
    {"startTime": "2026-04-12T13:00:00Z", "endTime": "2026-04-12T13:15:00Z", "activeZoneMinutes": {}}
  ]
}
```

- [ ] **Step 4: Commit**

```bash
git add tests/fixtures/google_health/hr_rollup.json tests/fixtures/google_health/activity_rollup.json tests/fixtures/google_health/azm_rollup.json
git commit -m "test(fixtures): add Google Health rollUp response fixtures"
```

---

### Task 3: Add `_rollup` helper + three dataclasses to GoogleHealthClient

**Files:**
- Modify: `foodlog/clients/google_health.py` (append dataclasses near the existing ones, add `_rollup` method to `GoogleHealthClient`)
- Test: `tests/test_google_health_client.py`

The `_rollup` request body shape is RFC3339 `startTime`/`endTime` (different from `dailyRollUp` which uses civil dates).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_google_health_client.py`:

```python
@pytest.mark.asyncio
async def test_rollup_posts_correct_body_and_returns_points():
    async with httpx.AsyncClient() as http:
        with respx.mock(base_url="https://health.googleapis.com") as mock:
            route = mock.post(
                url__regex=r".*/heart-rate/dataPoints:rollUp.*"
            ).mock(
                return_value=httpx.Response(200, json=_load("hr_rollup.json"))
            )
            client = GoogleHealthClient(http, access_token="test")
            since = datetime.datetime(2026, 4, 12, 11, 50, 0)
            until = datetime.datetime(2026, 4, 12, 12, 50, 0)
            points = await client._rollup("heart-rate", since, until, window_size_s=900)

    assert len(points) == 4
    sent = json.loads(route.calls.last.request.content)
    assert sent["range"]["startTime"] == "2026-04-12T11:50:00Z"
    assert sent["range"]["endTime"]   == "2026-04-12T12:50:00Z"
    assert sent["windowSize"] == "900s"
```

If `json` and `respx` aren't already imported at top of `test_google_health_client.py`, add them.

- [ ] **Step 2: Run test, verify it fails**

```
pytest tests/test_google_health_client.py::test_rollup_posts_correct_body_and_returns_points -v
```
Expected: FAIL with `AttributeError: 'GoogleHealthClient' object has no attribute '_rollup'`.

- [ ] **Step 3: Add the dataclasses + helper**

Append to `foodlog/clients/google_health.py` near the existing dataclasses (after `HrSampleRow`):

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

Then inside the `GoogleHealthClient` class add the helper (a private async method, sibling of `_paginate` and `_daily_rollup`):

```python
    async def _rollup(
        self,
        data_type: str,
        since: datetime.datetime,
        until: datetime.datetime,
        window_size_s: int,
    ) -> list[dict]:
        """POST :rollUp with RFC3339 time range. Returns rollupDataPoints or []."""
        url = (
            f"{BASE_URL}/{API_VERSION}/users/me/dataTypes/{data_type}/"
            f"dataPoints:rollUp"
        )
        body = {
            "range": {
                "startTime": since.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "endTime":   until.strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
            "windowSize": f"{window_size_s}s",
        }
        resp = await self._http.post(url, json=body, headers=self._auth_header)
        if resp.status_code == 429:
            raise RateLimited("Google Health API rate limit")
        if resp.status_code >= 500:
            raise GoogleHealthError(
                f"Google Health 5xx: {resp.status_code} body={resp.text[:500]}"
            )
        if resp.status_code >= 400:
            logger.warning(
                "google-health %s rollUp returned HTTP %d: %s",
                data_type, resp.status_code, resp.text[:500],
            )
            return []
        return resp.json().get("rollupDataPoints", []) or []
```

- [ ] **Step 4: Run test, verify it passes**

```
pytest tests/test_google_health_client.py::test_rollup_posts_correct_body_and_returns_points -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add foodlog/clients/google_health.py tests/test_google_health_client.py
git commit -m "feat(google-health): add _rollup helper and interval dataclasses"
```

---

### Task 4: Add `list_hr_intervals` with 14-day chunking

**Files:**
- Modify: `foodlog/clients/google_health.py`
- Test: `tests/test_google_health_client.py`

Heart-rate has a 14-day max range per request. The iterator must split a longer range into ≤14-day chunks transparently.

- [ ] **Step 1: Write the failing test (chunking + parsing)**

```python
@pytest.mark.asyncio
async def test_list_hr_intervals_chunks_into_14_day_slices():
    async with httpx.AsyncClient() as http:
        with respx.mock(base_url="https://health.googleapis.com") as mock:
            route = mock.post(url__regex=r".*/heart-rate/dataPoints:rollUp.*").mock(
                return_value=httpx.Response(200, json=_load("hr_rollup.json"))
            )
            client = GoogleHealthClient(http, access_token="test")
            # 30-day range -> expect three chunks: [0..14], [14..28], [28..30]
            since = datetime.datetime(2026, 3, 15, 0, 0, 0)
            until = datetime.datetime(2026, 4, 14, 0, 0, 0)
            rows = [r async for r in client.list_hr_intervals(since=since, until=until)]

    assert route.call_count == 3
    # each chunk returns the same 4-row fixture, so total rows = 12
    assert len(rows) == 12
    first = rows[0]
    assert first.bpm_avg == 102  # rounded from 102.3
    assert first.bpm_min == 88
    assert first.bpm_max == 121
    assert first.source == ""  # fixture has no dataSource
    assert first.start_at == datetime.datetime(2026, 4, 12, 11, 50, 0)
```

- [ ] **Step 2: Run test, verify it fails**

```
pytest tests/test_google_health_client.py::test_list_hr_intervals_chunks_into_14_day_slices -v
```
Expected: FAIL with `AttributeError: 'GoogleHealthClient' object has no attribute 'list_hr_intervals'`.

- [ ] **Step 3: Add the method**

Append to `foodlog/clients/google_health.py` inside `GoogleHealthClient`:

```python
    async def list_hr_intervals(
        self,
        since: datetime.datetime,
        until: datetime.datetime | None = None,
    ) -> AsyncIterator[HrIntervalRow]:
        """15-min HR rollup, chunked at 14-day max range per request."""
        end = until or datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
        chunk_start = since
        while chunk_start < end:
            chunk_end = min(chunk_start + datetime.timedelta(days=14), end)
            for pt in await self._rollup(
                "heart-rate", chunk_start, chunk_end, window_size_s=900,
            ):
                hr = pt.get("heartRate") or {}
                start_s = pt.get("startTime")
                if not start_s or hr.get("beatsPerMinuteAvg") is None:
                    continue
                try:
                    yield HrIntervalRow(
                        start_at=_parse_time(start_s),
                        bpm_avg=int(round(float(hr["beatsPerMinuteAvg"]))),
                        bpm_min=int(hr["beatsPerMinuteMin"]),
                        bpm_max=int(hr["beatsPerMinuteMax"]),
                        source=_source_from(pt.get("dataSource")),
                    )
                except (ValueError, TypeError, KeyError):
                    logger.warning("google-health hr rollup malformed: %r", pt)
                    continue
            chunk_start = chunk_end
```

- [ ] **Step 4: Run test, verify it passes**

```
pytest tests/test_google_health_client.py::test_list_hr_intervals_chunks_into_14_day_slices -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add foodlog/clients/google_health.py tests/test_google_health_client.py
git commit -m "feat(google-health): list_hr_intervals with 14-day chunking"
```

---

### Task 5: Add `list_activity_intervals`

**Files:**
- Modify: `foodlog/clients/google_health.py`
- Test: `tests/test_google_health_client.py`

The activity endpoints emit `{}` for empty windows — parser must skip those.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_list_activity_intervals_skips_all_empty_windows():
    async with httpx.AsyncClient() as http:
        with respx.mock(base_url="https://health.googleapis.com") as mock:
            mock.post(url__regex=r".*/activity-intervals/dataPoints:rollUp.*").mock(
                return_value=httpx.Response(200, json=_load("activity_rollup.json"))
            )
            client = GoogleHealthClient(http, access_token="test")
            since = datetime.datetime(2026, 4, 12, 11, 50, 0)
            until = datetime.datetime(2026, 4, 12, 13, 30, 0)
            rows = [r async for r in client.list_activity_intervals(since=since, until=until)]

    # fixture has 5 windows; 5th is all-empty -> should be skipped
    assert len(rows) == 4
    first = rows[0]
    assert first.steps == 649
    assert first.distance_m == 420.268  # mm -> m
    assert first.floors is None  # empty {}
    second = rows[1]
    assert second.floors == 3
```

Wait — the activity endpoint name. There is no single `activity-intervals` endpoint; activity is split across three Google data types (`steps`, `distance`, `floors`). Decision: `list_activity_intervals` issues three rollUp requests in parallel and zips by `startTime`.

Update the test to match this — mock all three endpoints and assert all three were called:

```python
@pytest.mark.asyncio
async def test_list_activity_intervals_zips_three_endpoints_and_skips_empty():
    activity_fix = _load("activity_rollup.json")
    # Synthesize per-endpoint responses by stripping the others.
    def _only(field: str) -> dict:
        return {
            "rollupDataPoints": [
                {"startTime": p["startTime"], "endTime": p["endTime"], field: p.get(field, {})}
                for p in activity_fix["rollupDataPoints"]
            ]
        }
    async with httpx.AsyncClient() as http:
        with respx.mock(base_url="https://health.googleapis.com") as mock:
            r_steps = mock.post(url__regex=r".*/steps/dataPoints:rollUp.*").mock(
                return_value=httpx.Response(200, json=_only("steps"))
            )
            r_dist = mock.post(url__regex=r".*/distance/dataPoints:rollUp.*").mock(
                return_value=httpx.Response(200, json=_only("distance"))
            )
            r_floors = mock.post(url__regex=r".*/floors/dataPoints:rollUp.*").mock(
                return_value=httpx.Response(200, json=_only("floors"))
            )
            client = GoogleHealthClient(http, access_token="test")
            since = datetime.datetime(2026, 4, 12, 11, 50, 0)
            until = datetime.datetime(2026, 4, 12, 13, 30, 0)
            rows = [r async for r in client.list_activity_intervals(since=since, until=until)]

    assert r_steps.called and r_dist.called and r_floors.called
    # 5 windows; 5th (13:00) has all-empty across all three -> dropped
    assert len(rows) == 4
    by_time = {r.start_at: r for r in rows}
    first = by_time[datetime.datetime(2026, 4, 12, 11, 50, 0)]
    assert first.steps == 649
    assert abs(first.distance_m - 420.268) < 1e-6
    assert first.floors is None
```

- [ ] **Step 2: Run test, verify it fails**

```
pytest tests/test_google_health_client.py::test_list_activity_intervals_zips_three_endpoints_and_skips_empty -v
```
Expected: FAIL with attribute error.

- [ ] **Step 3: Add the method**

Append inside `GoogleHealthClient`:

```python
    async def list_activity_intervals(
        self,
        since: datetime.datetime,
        until: datetime.datetime | None = None,
    ) -> AsyncIterator[ActivityIntervalRow]:
        """15-min steps/distance/floors rollup. Single 90-day request fits.
        Issues three parallel calls (one per endpoint) and zips by startTime.
        """
        import asyncio

        end = until or datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
        steps_pts, dist_pts, floors_pts = await asyncio.gather(
            self._rollup("steps", since, end, window_size_s=900),
            self._rollup("distance", since, end, window_size_s=900),
            self._rollup("floors", since, end, window_size_s=900),
        )

        def _index(points: list[dict], inner: str, sum_field: str) -> dict[str, tuple]:
            out: dict[str, tuple] = {}
            for p in points:
                start_s = p.get("startTime")
                value = (p.get(inner) or {}).get(sum_field)
                if start_s and value is not None:
                    try:
                        out[start_s] = (int(value), p.get("dataSource"))
                    except (ValueError, TypeError):
                        continue
            return out

        steps_by   = _index(steps_pts,   "steps",    "countSum")
        floors_by  = _index(floors_pts,  "floors",   "countSum")
        # distance is mm; cast to float, convert to meters
        dist_by: dict[str, tuple[float, dict | None]] = {}
        for p in dist_pts:
            start_s = p.get("startTime")
            mm = (p.get("distance") or {}).get("millimetersSum")
            if start_s and mm is not None:
                try:
                    dist_by[start_s] = (float(mm) / 1000.0, p.get("dataSource"))
                except (ValueError, TypeError):
                    continue

        all_times = sorted(set(steps_by) | set(dist_by) | set(floors_by))
        for ts in all_times:
            steps_v   = steps_by.get(ts, (None, None))
            dist_v    = dist_by.get(ts, (None, None))
            floors_v  = floors_by.get(ts, (None, None))
            ds = steps_v[1] or dist_v[1] or floors_v[1]
            yield ActivityIntervalRow(
                start_at=_parse_time(ts),
                steps=steps_v[0],
                distance_m=dist_v[0],
                floors=floors_v[0],
                source=_source_from(ds),
            )
```

- [ ] **Step 4: Run test, verify it passes**

```
pytest tests/test_google_health_client.py::test_list_activity_intervals_zips_three_endpoints_and_skips_empty -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add foodlog/clients/google_health.py tests/test_google_health_client.py
git commit -m "feat(google-health): list_activity_intervals zipping steps/distance/floors"
```

---

### Task 6: Add `list_azm_intervals`

**Files:**
- Modify: `foodlog/clients/google_health.py`
- Test: `tests/test_google_health_client.py`

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_list_azm_intervals_parses_zone_breakdown():
    async with httpx.AsyncClient() as http:
        with respx.mock(base_url="https://health.googleapis.com") as mock:
            mock.post(url__regex=r".*/active-zone-minutes/dataPoints:rollUp.*").mock(
                return_value=httpx.Response(200, json=_load("azm_rollup.json"))
            )
            client = GoogleHealthClient(http, access_token="test")
            since = datetime.datetime(2026, 4, 12, 11, 50, 0)
            until = datetime.datetime(2026, 4, 12, 13, 30, 0)
            rows = [r async for r in client.list_azm_intervals(since=since, until=until)]

    # 5 windows in fixture; 5th is empty {}
    assert len(rows) == 4
    first = rows[0]
    assert first.fat_burn_min == 3
    assert first.cardio_min is None
    assert first.peak_min is None
    fourth = rows[3]
    assert fourth.fat_burn_min == 12
    assert fourth.cardio_min == 2
    assert fourth.peak_min is None
```

- [ ] **Step 2: Run test, verify it fails**

```
pytest tests/test_google_health_client.py::test_list_azm_intervals_parses_zone_breakdown -v
```
Expected: FAIL.

- [ ] **Step 3: Add the method**

```python
    async def list_azm_intervals(
        self,
        since: datetime.datetime,
        until: datetime.datetime | None = None,
    ) -> AsyncIterator[AzmIntervalRow]:
        """15-min active-zone-minutes rollup with HR-zone breakdown."""
        end = until or datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
        for pt in await self._rollup(
            "active-zone-minutes", since, end, window_size_s=900,
        ):
            azm = pt.get("activeZoneMinutes") or {}
            start_s = pt.get("startTime")
            if not start_s:
                continue
            fb = azm.get("sumInFatBurnHeartZone")
            ca = azm.get("sumInCardioHeartZone")
            pk = azm.get("sumInPeakHeartZone")
            if fb is None and ca is None and pk is None:
                continue
            try:
                yield AzmIntervalRow(
                    start_at=_parse_time(start_s),
                    fat_burn_min=int(fb) if fb is not None else None,
                    cardio_min=int(ca)   if ca is not None else None,
                    peak_min=int(pk)     if pk is not None else None,
                    source=_source_from(pt.get("dataSource")),
                )
            except (ValueError, TypeError):
                logger.warning("google-health azm rollup malformed: %r", pt)
                continue
```

- [ ] **Step 4: Run test, verify it passes**

```
pytest tests/test_google_health_client.py::test_list_azm_intervals_parses_zone_breakdown -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add foodlog/clients/google_health.py tests/test_google_health_client.py
git commit -m "feat(google-health): list_azm_intervals with HR-zone breakdown"
```

---

### Task 7: Add `_sync_interval_heart_rate` to HealthSyncService

**Files:**
- Modify: `foodlog/services/health_sync.py`
- Test: `tests/test_health_sync.py`

Use cursor-based look-back via `cursor_for(db, IntervalHeartRate, "start_at", DEFAULT_BACKFILL_DAYS)`. Drain iterator before opening the SQLite write transaction (existing project rule).

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_sync_interval_heart_rate_upserts_idempotently(db_session, monkeypatch):
    from foodlog.clients.google_health import HrIntervalRow
    from foodlog.db.models import IntervalHeartRate
    from foodlog.services.health_sync import HealthSyncService

    rows = [
        HrIntervalRow(
            start_at=datetime.datetime(2026, 4, 12, 12, 0, 0),
            bpm_avg=110, bpm_min=88, bpm_max=140, source="FITBIT",
        ),
        HrIntervalRow(
            start_at=datetime.datetime(2026, 4, 12, 12, 15, 0),
            bpm_avg=115, bpm_min=92, bpm_max=145, source="FITBIT",
        ),
    ]

    class StubClient:
        async def list_hr_intervals(self, since, until=None):
            for r in rows:
                yield r

    sync = HealthSyncService(db_session, StubClient())
    n1 = await sync._sync_interval_heart_rate()
    n2 = await sync._sync_interval_heart_rate()  # second run: still 2, no duplicates
    assert n1 == 2
    assert n2 == 2
    stored = db_session.query(IntervalHeartRate).all()
    assert len(stored) == 2
    assert stored[0].bpm_avg == 110
```

- [ ] **Step 2: Run test, verify it fails**

```
pytest tests/test_health_sync.py::test_sync_interval_heart_rate_upserts_idempotently -v
```
Expected: FAIL.

- [ ] **Step 3: Add the imports and method**

Top of `foodlog/services/health_sync.py`, add to the existing model imports:

```python
from foodlog.db.models import (
    BodyComposition,
    DailyActivity,
    IntervalActivity,
    IntervalAzm,
    IntervalHeartRate,
    RestingHeartRate,
    SleepSession,
    Workout,
    WorkoutHrSample,
)
```

Then inside `HealthSyncService` add:

```python
    async def _sync_interval_heart_rate(self) -> int:
        since = cursor_for(self._db, IntervalHeartRate, "start_at", DEFAULT_BACKFILL_DAYS)
        rows = [r async for r in self._client.list_hr_intervals(since=since)]
        for row in rows:
            stmt = sqlite_insert(IntervalHeartRate).values(
                start_at=row.start_at,
                bpm_avg=row.bpm_avg,
                bpm_min=row.bpm_min,
                bpm_max=row.bpm_max,
                source=row.source,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["start_at"],
                set_=dict(
                    bpm_avg=row.bpm_avg,
                    bpm_min=row.bpm_min,
                    bpm_max=row.bpm_max,
                    source=row.source,
                ),
            )
            self._db.execute(stmt)
        self._db.commit()
        return len(rows)
```

- [ ] **Step 4: Run test, verify it passes**

```
pytest tests/test_health_sync.py::test_sync_interval_heart_rate_upserts_idempotently -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add foodlog/services/health_sync.py tests/test_health_sync.py
git commit -m "feat(health-sync): _sync_interval_heart_rate with idempotent upsert"
```

---

### Task 8: Add `_sync_interval_activity`

**Files:**
- Modify: `foodlog/services/health_sync.py`
- Test: `tests/test_health_sync.py`

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_sync_interval_activity_upserts_with_nullable_columns(db_session):
    from foodlog.clients.google_health import ActivityIntervalRow
    from foodlog.db.models import IntervalActivity
    from foodlog.services.health_sync import HealthSyncService

    rows = [
        ActivityIntervalRow(
            start_at=datetime.datetime(2026, 4, 12, 12, 0, 0),
            steps=649, distance_m=420.268, floors=None, source="FITBIT",
        ),
        ActivityIntervalRow(
            start_at=datetime.datetime(2026, 4, 12, 12, 15, 0),
            steps=792, distance_m=628.5, floors=3, source="FITBIT",
        ),
    ]

    class StubClient:
        async def list_activity_intervals(self, since, until=None):
            for r in rows:
                yield r

    sync = HealthSyncService(db_session, StubClient())
    n = await sync._sync_interval_activity()
    assert n == 2
    stored = db_session.query(IntervalActivity).all()
    assert len(stored) == 2
    assert stored[0].steps == 649
    assert stored[0].floors is None
    assert stored[1].floors == 3
```

- [ ] **Step 2: Run test, verify it fails**

```
pytest tests/test_health_sync.py::test_sync_interval_activity_upserts_with_nullable_columns -v
```
Expected: FAIL.

- [ ] **Step 3: Add the method**

```python
    async def _sync_interval_activity(self) -> int:
        since = cursor_for(self._db, IntervalActivity, "start_at", DEFAULT_BACKFILL_DAYS)
        rows = [r async for r in self._client.list_activity_intervals(since=since)]
        for row in rows:
            stmt = sqlite_insert(IntervalActivity).values(
                start_at=row.start_at,
                steps=row.steps,
                distance_m=row.distance_m,
                floors=row.floors,
                source=row.source,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["start_at"],
                set_=dict(
                    steps=row.steps,
                    distance_m=row.distance_m,
                    floors=row.floors,
                    source=row.source,
                ),
            )
            self._db.execute(stmt)
        self._db.commit()
        return len(rows)
```

- [ ] **Step 4: Run test, verify it passes**

```
pytest tests/test_health_sync.py::test_sync_interval_activity_upserts_with_nullable_columns -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add foodlog/services/health_sync.py tests/test_health_sync.py
git commit -m "feat(health-sync): _sync_interval_activity"
```

---

### Task 9: Add `_sync_interval_azm`

**Files:**
- Modify: `foodlog/services/health_sync.py`
- Test: `tests/test_health_sync.py`

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_sync_interval_azm_upserts(db_session):
    from foodlog.clients.google_health import AzmIntervalRow
    from foodlog.db.models import IntervalAzm
    from foodlog.services.health_sync import HealthSyncService

    rows = [
        AzmIntervalRow(
            start_at=datetime.datetime(2026, 4, 12, 12, 0, 0),
            fat_burn_min=8, cardio_min=None, peak_min=None, source="FITBIT",
        ),
    ]

    class StubClient:
        async def list_azm_intervals(self, since, until=None):
            for r in rows:
                yield r

    sync = HealthSyncService(db_session, StubClient())
    n = await sync._sync_interval_azm()
    assert n == 1
    stored = db_session.query(IntervalAzm).first()
    assert stored.fat_burn_min == 8
    assert stored.cardio_min is None
```

- [ ] **Step 2: Run test, verify it fails**

```
pytest tests/test_health_sync.py::test_sync_interval_azm_upserts -v
```
Expected: FAIL.

- [ ] **Step 3: Add the method**

```python
    async def _sync_interval_azm(self) -> int:
        since = cursor_for(self._db, IntervalAzm, "start_at", DEFAULT_BACKFILL_DAYS)
        rows = [r async for r in self._client.list_azm_intervals(since=since)]
        for row in rows:
            stmt = sqlite_insert(IntervalAzm).values(
                start_at=row.start_at,
                fat_burn_min=row.fat_burn_min,
                cardio_min=row.cardio_min,
                peak_min=row.peak_min,
                source=row.source,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["start_at"],
                set_=dict(
                    fat_burn_min=row.fat_burn_min,
                    cardio_min=row.cardio_min,
                    peak_min=row.peak_min,
                    source=row.source,
                ),
            )
            self._db.execute(stmt)
        self._db.commit()
        return len(rows)
```

- [ ] **Step 4: Run test, verify it passes**

```
pytest tests/test_health_sync.py::test_sync_interval_azm_upserts -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add foodlog/services/health_sync.py tests/test_health_sync.py
git commit -m "feat(health-sync): _sync_interval_azm"
```

---

### Task 10: Wire interval sync into `sync_all`

**Files:**
- Modify: `foodlog/services/health_sync.py`
- Test: `tests/test_health_sync.py`

The three new sync methods need to run inside `sync_all()` so they're triggered by the existing dashboard background sync.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_sync_all_includes_interval_metrics(db_session):
    from foodlog.clients.google_health import (
        HrIntervalRow, ActivityIntervalRow, AzmIntervalRow,
    )
    from foodlog.services.health_sync import HealthSyncService

    class StubClient:
        async def list_daily_activity(self, since, until=None):
            return; yield  # empty generator
        async def list_body_composition(self, since, until=None):
            return; yield
        async def list_resting_heart_rate(self, since, until=None):
            return; yield
        async def list_sleep_sessions(self, since, until=None):
            return; yield
        async def list_workouts(self, since, until=None):
            return; yield
        async def list_workout_hr_samples(self, workout_id, start_at, end_at):
            return; yield
        async def list_hr_intervals(self, since, until=None):
            yield HrIntervalRow(
                start_at=datetime.datetime(2026, 4, 12, 12, 0, 0),
                bpm_avg=110, bpm_min=88, bpm_max=140, source="FITBIT",
            )
        async def list_activity_intervals(self, since, until=None):
            yield ActivityIntervalRow(
                start_at=datetime.datetime(2026, 4, 12, 12, 0, 0),
                steps=600, distance_m=400.0, floors=None, source="FITBIT",
            )
        async def list_azm_intervals(self, since, until=None):
            yield AzmIntervalRow(
                start_at=datetime.datetime(2026, 4, 12, 12, 0, 0),
                fat_burn_min=5, cardio_min=None, peak_min=None, source="FITBIT",
            )

    sync = HealthSyncService(db_session, StubClient())
    result = await sync.sync_all()
    assert result.ok is True
    assert result.rows_upserted.get("interval_heart_rate") == 1
    assert result.rows_upserted.get("interval_activity") == 1
    assert result.rows_upserted.get("interval_azm") == 1
```

- [ ] **Step 2: Run test, verify it fails**

```
pytest tests/test_health_sync.py::test_sync_all_includes_interval_metrics -v
```
Expected: FAIL — keys not in `rows_upserted`.

- [ ] **Step 3: Wire into sync_all**

In `foodlog/services/health_sync.py`, inside `sync_all`, append to the `_run` calls list (after the existing entries, before the workouts block):

```python
        await _run("interval_heart_rate", self._sync_interval_heart_rate)
        await _run("interval_activity", self._sync_interval_activity)
        await _run("interval_azm", self._sync_interval_azm)
```

- [ ] **Step 4: Run test, verify it passes**

```
pytest tests/test_health_sync.py::test_sync_all_includes_interval_metrics -v
pytest tests/test_health_sync.py -v   # ensure nothing else broke
```
Expected: PASS for both.

- [ ] **Step 5: Commit**

```bash
git add foodlog/services/health_sync.py tests/test_health_sync.py
git commit -m "feat(health-sync): include interval metrics in sync_all"
```

---

### Task 11: Add `--metric-*` CSS tokens to base.html

**Files:**
- Modify: `foodlog/templates/base.html`

- [ ] **Step 1: Add tokens inside the `:root` block**

Find the `:root { ... }` block (starts around line 25 of `base.html`) and append after the existing `--meal-snack` line:

```css
            --metric-hr:        #c75e3c;
            --metric-hr-soft:   rgba(199, 94, 60, 0.12);
            --metric-steps:     var(--accent);
            --metric-distance:  #5a8e7c;
            --metric-floors:    #b88e54;
            --metric-azm-light: rgba(199, 94, 60, 0.45);
            --metric-azm-mid:   rgba(199, 94, 60, 0.75);
            --metric-azm-peak:  #c75e3c;
            --marker-meal:      var(--meal-breakfast);
```

- [ ] **Step 2: Verify the page still loads**

Container does not need rebuild yet — templates are baked into the image. Skip verification until Task 12 wires up the timeline page.

- [ ] **Step 3: Commit**

```bash
git add foodlog/templates/base.html
git commit -m "style(tokens): add --metric-* and --marker-meal CSS variables"
```

---

### Task 12: Timeline router skeleton + minimal template

**Files:**
- Create: `foodlog/api/routers/timeline.py`
- Create: `foodlog/templates/dashboard/timeline.html`
- Modify: `foodlog/api/app.py`
- Test: `tests/test_timeline.py`

This task gets `/dashboard/timeline` returning a 200 with a stub page. Real chart rendering follows in subsequent tasks.

- [ ] **Step 1: Write the failing test**

Create `tests/test_timeline.py`:

```python
import datetime

import pytest
from fastapi.testclient import TestClient


def test_timeline_returns_200_for_today(db_session):
    # The fixture in conftest.py already disables Google SSO so /dashboard/* is open in tests.
    from foodlog.api.app import create_app
    client = TestClient(create_app())
    r = client.get("/dashboard/timeline")
    assert r.status_code == 200
    # Stub assertion — refined in later tasks.
    assert "timeline" in r.text.lower()


def test_timeline_accepts_date_param(db_session):
    from foodlog.api.app import create_app
    client = TestClient(create_app())
    r = client.get("/dashboard/timeline?date=2026-04-12")
    assert r.status_code == 200
    assert "2026" in r.text  # date is rendered somewhere
```

- [ ] **Step 2: Run tests, verify they fail**

```
pytest tests/test_timeline.py -v
```
Expected: 404 from FastAPI.

- [ ] **Step 3: Create the router**

`foodlog/api/routers/timeline.py`:

```python
import datetime
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from foodlog.api.dependencies import get_db
from foodlog.api.routers.dashboard import (
    _background_health_sync,
    _sync_due,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/dashboard", tags=["dashboard"])
templates = Jinja2Templates(directory="foodlog/templates")


def _parse_date(s: str | None) -> datetime.date:
    if not s:
        return datetime.date.today()
    try:
        return datetime.date.fromisoformat(s)
    except ValueError:
        return datetime.date.today()


@router.get("/timeline", response_class=HTMLResponse)
def timeline(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    date: str | None = None,
    focus: str | None = None,
) -> HTMLResponse:
    day = _parse_date(date)
    today = datetime.date.today()

    if _sync_due():
        background_tasks.add_task(_background_health_sync)

    return templates.TemplateResponse(
        "dashboard/timeline.html",
        {
            "request": request,
            "day": day,
            "today": today,
            "is_today": day == today,
            "focus": focus,
        },
    )
```

`foodlog/templates/dashboard/timeline.html`:

```jinja
{% extends "base.html" %}

{% block content %}
<header class="topbar">
  <div class="brand">
    <span class="mark"><span class="dot"></span>FoodLog</span>
    <span class="date">Timeline · {{ day.strftime('%A, %b %-d') }}</span>
  </div>
</header>

<div id="timeline-content">
  <p>{{ day.isoformat() }}</p>
</div>
{% endblock %}
```

Then in `foodlog/api/app.py` register the router. Find where the existing dashboard router is included and add the timeline import + include alongside it. Example (adjust to match existing import pattern):

```python
from foodlog.api.routers import timeline as timeline_router
# ...
app.include_router(timeline_router.router)
```

- [ ] **Step 4: Run tests, verify they pass**

```
pytest tests/test_timeline.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add foodlog/api/routers/timeline.py foodlog/templates/dashboard/timeline.html foodlog/api/app.py tests/test_timeline.py
git commit -m "feat(timeline): add /dashboard/timeline route with stub template"
```

---

### Task 13: Render the HR chart panel

**Files:**
- Create: `foodlog/templates/dashboard/timeline_partial.html`
- Modify: `foodlog/templates/dashboard/timeline.html` — include the partial
- Modify: `foodlog/api/routers/timeline.py` — build view data from `IntervalHeartRate`
- Modify: `tests/test_timeline.py`

Each chart renders 96 fifteen-minute slots as `<span>` columns. HR uses a `range bar + avg dot` shape, fixed Y-axis 40–180 BPM. Empty windows render as no column at that index.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_timeline.py`:

```python
def test_timeline_renders_hr_panel_with_data(db_session):
    from foodlog.api.app import create_app
    from foodlog.db.models import IntervalHeartRate

    # Seed three windows on 2026-04-12 between 12:00 and 12:30
    for hr_avg, m in [(110, 0), (115, 15), (108, 30)]:
        db_session.add(IntervalHeartRate(
            start_at=datetime.datetime(2026, 4, 12, 12, m, 0),
            bpm_avg=hr_avg, bpm_min=hr_avg - 20, bpm_max=hr_avg + 30,
            source="FITBIT",
        ))
    db_session.commit()

    client = TestClient(create_app())
    r = client.get("/dashboard/timeline?date=2026-04-12")
    assert r.status_code == 200
    # The partial uses class="hr-col" per slot with data
    assert r.text.count('class="hr-col"') == 3
    # Min and max BPM should be reflected in the inline style
    assert "data-bpm-avg=\"110\"" in r.text or "data-bpm-avg='110'" in r.text
```

- [ ] **Step 2: Run test, verify it fails**

```
pytest tests/test_timeline.py::test_timeline_renders_hr_panel_with_data -v
```
Expected: FAIL.

- [ ] **Step 3: Build view data in the router**

Replace the `timeline` function body in `foodlog/api/routers/timeline.py`:

```python
@router.get("/timeline", response_class=HTMLResponse)
def timeline(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    date: str | None = None,
    focus: str | None = None,
) -> HTMLResponse:
    from foodlog.db.models import IntervalHeartRate
    day = _parse_date(date)
    today = datetime.date.today()

    if _sync_due():
        background_tasks.add_task(_background_health_sync)

    start_dt = datetime.datetime.combine(day, datetime.time.min)
    end_dt = start_dt + datetime.timedelta(days=1)

    hr_rows = db.query(IntervalHeartRate).filter(
        IntervalHeartRate.start_at >= start_dt,
        IntervalHeartRate.start_at < end_dt,
    ).all()
    # Build a 96-slot list indexed by minute_of_day // 15. None means no data.
    HR_MIN, HR_MAX = 40, 180
    hr_slots: list[dict | None] = [None] * 96
    for r in hr_rows:
        idx = (r.start_at.hour * 60 + r.start_at.minute) // 15
        if 0 <= idx < 96:
            hr_slots[idx] = {
                "avg": r.bpm_avg,
                "min": r.bpm_min,
                "max": r.bpm_max,
                "avg_pct":   _pct(r.bpm_avg, HR_MIN, HR_MAX),
                "range_bottom_pct": _pct(r.bpm_min, HR_MIN, HR_MAX),
                "range_height_pct": _pct(r.bpm_max, HR_MIN, HR_MAX) - _pct(r.bpm_min, HR_MIN, HR_MAX),
            }

    return templates.TemplateResponse(
        "dashboard/timeline.html",
        {
            "request": request,
            "day": day,
            "today": today,
            "is_today": day == today,
            "focus": focus,
            "hr_slots": hr_slots,
        },
    )


def _pct(value: int, lo: int, hi: int) -> float:
    return max(0.0, min(100.0, (value - lo) / (hi - lo) * 100.0))
```

- [ ] **Step 4: Create the partial and update the template**

Create `foodlog/templates/dashboard/timeline_partial.html`:

```jinja
<section class="timeline-section">
  <div class="tl-panel tl-panel-hr">
    <div class="tl-panel-label">Heart rate</div>
    <div class="tl-chart">
      {% for slot in hr_slots %}
        {% if slot is none %}
          <div class="tl-col tl-col-empty"></div>
        {% else %}
          <div class="tl-col hr-col"
               data-bpm-avg="{{ slot.avg }}"
               data-bpm-min="{{ slot.min }}"
               data-bpm-max="{{ slot.max }}">
            <span class="hr-range" style="bottom: {{ '%.2f' % slot.range_bottom_pct }}%; height: {{ '%.2f' % slot.range_height_pct }}%"></span>
            <span class="hr-dot"   style="bottom: {{ '%.2f' % slot.avg_pct }}%"></span>
          </div>
        {% endif %}
      {% endfor %}
    </div>
  </div>
</section>
```

Update `foodlog/templates/dashboard/timeline.html` to include the partial:

```jinja
{% extends "base.html" %}

{% block content %}
<header class="topbar">
  <div class="brand">
    <span class="mark"><span class="dot"></span>FoodLog</span>
    <span class="date">Timeline · {{ day.strftime('%A, %b %-d') }}</span>
  </div>
</header>

<div id="timeline-content">
  {% include "dashboard/timeline_partial.html" %}
</div>
{% endblock %}
```

Add the relevant CSS to the `<style>` block in `foodlog/templates/base.html` (append, near the end of the existing rules):

```css
        /* ── Timeline ───────────────────────────────────────── */
        .timeline-section { padding: 1rem 0; }
        .tl-panel { margin-bottom: 1rem; }
        .tl-panel-label {
            font-size: 0.7rem;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            color: var(--muted);
            margin-bottom: 0.4rem;
        }
        .tl-chart {
            position: relative;
            display: grid;
            grid-template-columns: repeat(96, 1fr);
            gap: 1px;
            height: 110px;
            background: var(--bg-sunk);
            padding: 4px;
            border-radius: 4px;
        }
        .tl-col {
            position: relative;
            min-height: 0;
        }
        .tl-col-empty { background: transparent; }
        .hr-col .hr-range {
            position: absolute;
            left: 0; right: 0;
            background: var(--metric-hr-soft);
            border-radius: 1px;
        }
        .hr-col .hr-dot {
            position: absolute;
            left: 50%;
            transform: translate(-50%, 50%);
            width: 3px; height: 3px;
            background: var(--metric-hr);
            border-radius: 50%;
        }
```

- [ ] **Step 5: Run test, verify it passes**

```
pytest tests/test_timeline.py -v
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add foodlog/api/routers/timeline.py foodlog/templates/dashboard/timeline.html foodlog/templates/dashboard/timeline_partial.html foodlog/templates/base.html tests/test_timeline.py
git commit -m "feat(timeline): render HR panel with range-bar+avg-dot bars"
```

---

### Task 14: Render steps / distance / floors panels

**Files:**
- Modify: `foodlog/api/routers/timeline.py`
- Modify: `foodlog/templates/dashboard/timeline_partial.html`
- Modify: `foodlog/templates/base.html`
- Modify: `tests/test_timeline.py`

These three panels use simple solid bars with auto Y-axis (per chart, max value = 100% height).

- [ ] **Step 1: Write the failing test**

```python
def test_timeline_renders_activity_panels(db_session):
    from foodlog.api.app import create_app
    from foodlog.db.models import IntervalActivity

    db_session.add_all([
        IntervalActivity(
            start_at=datetime.datetime(2026, 4, 12, 12, 0, 0),
            steps=649, distance_m=420.268, floors=None, source="FITBIT",
        ),
        IntervalActivity(
            start_at=datetime.datetime(2026, 4, 12, 12, 15, 0),
            steps=1462, distance_m=1133.0, floors=5, source="FITBIT",
        ),
    ])
    db_session.commit()

    client = TestClient(create_app())
    r = client.get("/dashboard/timeline?date=2026-04-12")
    assert r.status_code == 200
    assert r.text.count('class="steps-col"') == 2
    assert r.text.count('class="dist-col"') == 2
    # Only one floors data point (the other has floors=None)
    assert r.text.count('class="floors-col"') == 1
```

- [ ] **Step 2: Run test, verify it fails**

```
pytest tests/test_timeline.py::test_timeline_renders_activity_panels -v
```
Expected: FAIL.

- [ ] **Step 3: Build activity slots in the router**

In the timeline view function, after the HR slots block, add:

```python
    from foodlog.db.models import IntervalActivity

    activity_rows = db.query(IntervalActivity).filter(
        IntervalActivity.start_at >= start_dt,
        IntervalActivity.start_at < end_dt,
    ).all()
    steps_slots: list[int | None]   = [None] * 96
    dist_slots:  list[float | None] = [None] * 96
    floors_slots: list[int | None]  = [None] * 96
    for r in activity_rows:
        idx = (r.start_at.hour * 60 + r.start_at.minute) // 15
        if 0 <= idx < 96:
            steps_slots[idx]  = r.steps
            dist_slots[idx]   = r.distance_m
            floors_slots[idx] = r.floors

    def _scale(slots, none_to_zero=False):
        nonempty = [v for v in slots if v not in (None, 0)]
        peak = max(nonempty) if nonempty else 1
        return [
            (None if v is None else (v / peak * 100.0))
            for v in slots
        ]

    steps_pct  = _scale(steps_slots)
    dist_pct   = _scale(dist_slots)
    floors_pct = _scale(floors_slots)
```

Add these to the template context dict:

```python
            "steps_slots": steps_slots,
            "dist_slots": dist_slots,
            "floors_slots": floors_slots,
            "steps_pct": steps_pct,
            "dist_pct": dist_pct,
            "floors_pct": floors_pct,
```

- [ ] **Step 4: Add the three panels to the partial**

Append inside `<section class="timeline-section">` in `timeline_partial.html`, after the HR panel:

```jinja
  <div class="tl-panel tl-panel-steps">
    <div class="tl-panel-label">Steps</div>
    <div class="tl-chart">
      {% for v in steps_slots %}
        {% if v is none or v == 0 %}
          <div class="tl-col tl-col-empty"></div>
        {% else %}
          <div class="tl-col steps-col" data-steps="{{ v }}">
            <span class="bar-fill bar-steps" style="height: {{ '%.2f' % steps_pct[loop.index0] }}%"></span>
          </div>
        {% endif %}
      {% endfor %}
    </div>
  </div>

  <div class="tl-panel tl-panel-distance">
    <div class="tl-panel-label">Distance</div>
    <div class="tl-chart">
      {% for v in dist_slots %}
        {% if v is none or v == 0 %}
          <div class="tl-col tl-col-empty"></div>
        {% else %}
          <div class="tl-col dist-col" data-meters="{{ v }}">
            <span class="bar-fill bar-distance" style="height: {{ '%.2f' % dist_pct[loop.index0] }}%"></span>
          </div>
        {% endif %}
      {% endfor %}
    </div>
  </div>

  <div class="tl-panel tl-panel-floors">
    <div class="tl-panel-label">Floors</div>
    <div class="tl-chart">
      {% for v in floors_slots %}
        {% if v is none or v == 0 %}
          <div class="tl-col tl-col-empty"></div>
        {% else %}
          <div class="tl-col floors-col" data-floors="{{ v }}">
            <span class="bar-fill bar-floors" style="height: {{ '%.2f' % floors_pct[loop.index0] }}%"></span>
          </div>
        {% endif %}
      {% endfor %}
    </div>
  </div>
```

Add CSS to `base.html`:

```css
        .bar-fill {
            position: absolute;
            left: 0; right: 0; bottom: 0;
            border-radius: 1px 1px 0 0;
        }
        .bar-steps    { background: var(--metric-steps); }
        .bar-distance { background: var(--metric-distance); }
        .bar-floors   { background: var(--metric-floors); }
```

- [ ] **Step 5: Run test, verify it passes**

```
pytest tests/test_timeline.py -v
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add foodlog/api/routers/timeline.py foodlog/templates/dashboard/timeline_partial.html foodlog/templates/base.html tests/test_timeline.py
git commit -m "feat(timeline): render steps / distance / floors panels"
```

---

### Task 15: Render the AZM stacked panel

**Files:**
- Modify: `foodlog/api/routers/timeline.py`
- Modify: `foodlog/templates/dashboard/timeline_partial.html`
- Modify: `foodlog/templates/base.html`
- Modify: `tests/test_timeline.py`

Stacked from the bottom: fat-burn (lightest tint), cardio (mid), peak (full saturation).

- [ ] **Step 1: Write the failing test**

```python
def test_timeline_renders_azm_stacked_panel(db_session):
    from foodlog.api.app import create_app
    from foodlog.db.models import IntervalAzm

    db_session.add(IntervalAzm(
        start_at=datetime.datetime(2026, 4, 12, 12, 35, 0),
        fat_burn_min=12, cardio_min=2, peak_min=None, source="FITBIT",
    ))
    db_session.commit()

    client = TestClient(create_app())
    r = client.get("/dashboard/timeline?date=2026-04-12")
    assert r.status_code == 200
    assert 'class="azm-col"' in r.text
    assert 'azm-fat-burn' in r.text
    assert 'azm-cardio' in r.text
```

- [ ] **Step 2: Run test, verify it fails**

```
pytest tests/test_timeline.py::test_timeline_renders_azm_stacked_panel -v
```
Expected: FAIL.

- [ ] **Step 3: Build AZM slots in the router**

After the activity block, add:

```python
    from foodlog.db.models import IntervalAzm

    azm_rows = db.query(IntervalAzm).filter(
        IntervalAzm.start_at >= start_dt,
        IntervalAzm.start_at < end_dt,
    ).all()
    azm_slots: list[dict | None] = [None] * 96
    for r in azm_rows:
        idx = (r.start_at.hour * 60 + r.start_at.minute) // 15
        if 0 <= idx < 96:
            azm_slots[idx] = {
                "fat_burn": r.fat_burn_min or 0,
                "cardio":   r.cardio_min or 0,
                "peak":     r.peak_min or 0,
            }
    azm_peak_total = max(
        (s["fat_burn"] + s["cardio"] + s["peak"]) for s in azm_slots if s is not None
    ) if any(azm_slots) else 1
    for s in azm_slots:
        if s is None:
            continue
        total = s["fat_burn"] + s["cardio"] + s["peak"]
        s["fb_pct"]  = (s["fat_burn"] / azm_peak_total * 100.0) if azm_peak_total else 0
        s["ca_pct"]  = (s["cardio"]   / azm_peak_total * 100.0) if azm_peak_total else 0
        s["pk_pct"]  = (s["peak"]     / azm_peak_total * 100.0) if azm_peak_total else 0
```

Add `"azm_slots": azm_slots,` to the template context.

- [ ] **Step 4: Add the panel to the partial**

Append:

```jinja
  <div class="tl-panel tl-panel-azm">
    <div class="tl-panel-label">Active zone minutes</div>
    <div class="tl-chart">
      {% for s in azm_slots %}
        {% if s is none or (s.fat_burn == 0 and s.cardio == 0 and s.peak == 0) %}
          <div class="tl-col tl-col-empty"></div>
        {% else %}
          <div class="tl-col azm-col"
               data-fat-burn="{{ s.fat_burn }}" data-cardio="{{ s.cardio }}" data-peak="{{ s.peak }}">
            <span class="bar-fill azm-fat-burn" style="bottom: 0; height: {{ '%.2f' % s.fb_pct }}%"></span>
            <span class="bar-fill azm-cardio"   style="bottom: {{ '%.2f' % s.fb_pct }}%; height: {{ '%.2f' % s.ca_pct }}%"></span>
            <span class="bar-fill azm-peak"     style="bottom: {{ '%.2f' % (s.fb_pct + s.ca_pct) }}%; height: {{ '%.2f' % s.pk_pct }}%"></span>
          </div>
        {% endif %}
      {% endfor %}
    </div>
  </div>
```

Add CSS:

```css
        .azm-fat-burn { background: var(--metric-azm-light); }
        .azm-cardio   { background: var(--metric-azm-mid); }
        .azm-peak     { background: var(--metric-azm-peak); }
```

- [ ] **Step 5: Run test, verify it passes**

```
pytest tests/test_timeline.py -v
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add foodlog/api/routers/timeline.py foodlog/templates/dashboard/timeline_partial.html foodlog/templates/base.html tests/test_timeline.py
git commit -m "feat(timeline): render AZM stacked panel"
```

---

### Task 16: Workout band overlay + meal dots

**Files:**
- Modify: `foodlog/api/routers/timeline.py`
- Modify: `foodlog/templates/dashboard/timeline_partial.html`
- Modify: `foodlog/templates/base.html`
- Modify: `tests/test_timeline.py`

A workout's band sits absolute-positioned across all charts. Meal dots sit above the time axis (not currently rendered — added here).

- [ ] **Step 1: Write the failing test**

```python
def test_timeline_overlays_workouts_and_meal_dots(db_session):
    from foodlog.api.app import create_app
    from foodlog.db.models import Workout, FoodEntry

    db_session.add(Workout(
        external_id="walk-1",
        start_at=datetime.datetime(2026, 4, 12, 12, 0, 0),
        end_at=datetime.datetime(2026, 4, 12, 12, 47, 0),
        activity_type="Walk",
        duration_min=47,
        calories_kcal=300.0, distance_m=3500.0,
        avg_hr=112, max_hr=145, source="FITBIT",
    ))
    db_session.add(FoodEntry(
        meal_type="lunch", food_name="salad",
        quantity=1, unit="bowl",
        calories=400, protein_g=20, carbs_g=30, fat_g=10,
        source="manual", raw_input="salad",
        logged_at=datetime.datetime(2026, 4, 12, 13, 0, 0),
    ))
    db_session.commit()

    client = TestClient(create_app())
    r = client.get("/dashboard/timeline?date=2026-04-12")
    assert r.status_code == 200
    assert 'class="tl-workout-band"' in r.text
    assert 'Walk' in r.text
    assert 'class="tl-meal-dot"' in r.text
```

- [ ] **Step 2: Run test, verify it fails**

```
pytest tests/test_timeline.py::test_timeline_overlays_workouts_and_meal_dots -v
```
Expected: FAIL.

- [ ] **Step 3: Build markers in the router**

After AZM block:

```python
    from foodlog.db.models import Workout, FoodEntry

    def _pct_of_day(dt: datetime.datetime) -> float:
        secs = (dt - start_dt).total_seconds()
        return max(0.0, min(100.0, secs / 86400.0 * 100.0))

    workouts = db.query(Workout).filter(
        Workout.start_at >= start_dt,
        Workout.start_at < end_dt,
    ).all()
    workout_views = []
    for w in workouts:
        left = _pct_of_day(w.start_at)
        right = 100.0 - _pct_of_day(w.end_at)
        workout_views.append({
            "label": w.activity_type,
            "duration_min": w.duration_min,
            "left_pct":  left,
            "right_pct": right,
            "start_hhmm": w.start_at.strftime("%H:%M"),
            "end_hhmm":   w.end_at.strftime("%H:%M"),
            "is_focused": _is_focused(focus, w.start_at, w.end_at),
        })

    meals = db.query(FoodEntry).filter(
        FoodEntry.logged_at >= start_dt,
        FoodEntry.logged_at < end_dt,
    ).all()
    meal_views = [
        {
            "name": m.food_name,
            "meal_type": m.meal_type,
            "left_pct": _pct_of_day(m.logged_at),
        }
        for m in meals
    ]
```

Add a helper function near the bottom of the file:

```python
def _is_focused(focus: str | None, start: datetime.datetime, end: datetime.datetime) -> bool:
    if not focus:
        return False
    try:
        a, b = focus.split("-")
        ah, am = (int(x) for x in a.split(":"))
        bh, bm = (int(x) for x in b.split(":"))
    except (ValueError, AttributeError):
        return False
    return (start.hour == ah and start.minute == am
            and end.hour == bh and end.minute == bm)
```

Add to template context:

```python
            "workout_views": workout_views,
            "meal_views": meal_views,
```

- [ ] **Step 4: Add markers to the partial**

Wrap each `tl-chart` in the partial inside a `tl-chart-wrap` that also receives the workout band overlay (workout bands span all chart panels, so the simplest approach is to add a band overlay at the section level using absolute positioning across the entire stacked group). For mobile layout simplicity, render the workout band inside *each* chart so vertical alignment doesn't depend on JS.

Replace the partial's section opener with:

```jinja
<section class="timeline-section" data-day="{{ day.isoformat() }}">
  <div class="tl-meal-strip">
    {% for m in meal_views %}
      <span class="tl-meal-dot tl-meal-{{ m.meal_type }}"
            style="left: {{ '%.2f' % m.left_pct }}%"
            title="{{ m.name }}"></span>
    {% endfor %}
  </div>
```

Inside each `<div class="tl-chart">`, before the {% for %} loop, prepend:

```jinja
      {% for w in workout_views %}
        <div class="tl-workout-band {% if w.is_focused %}tl-workout-focused{% endif %}"
             style="left: {{ '%.2f' % w.left_pct }}%; right: {{ '%.2f' % w.right_pct }}%"></div>
      {% endfor %}
```

Inside the HR panel's `<div class="tl-chart">` only (it gets the labels), also add:

```jinja
      {% for w in workout_views %}
        <div class="tl-workout-label" style="left: {{ '%.2f' % w.left_pct }}%">{{ w.label }} · {{ w.duration_min }}m</div>
      {% endfor %}
```

Add CSS:

```css
        .tl-meal-strip {
            position: relative;
            height: 18px;
            margin-bottom: 6px;
        }
        .tl-meal-dot {
            position: absolute;
            top: 4px;
            width: 9px; height: 9px;
            border-radius: 50%;
            transform: translateX(-50%);
            background: var(--marker-meal);
            box-shadow: 0 0 0 2px var(--bg);
        }
        .tl-meal-breakfast { background: var(--meal-breakfast); }
        .tl-meal-lunch     { background: var(--meal-lunch); }
        .tl-meal-dinner    { background: var(--meal-dinner); }
        .tl-meal-snack     { background: var(--meal-snack); }

        .tl-workout-band {
            position: absolute;
            top: 0; bottom: 0;
            background: var(--metric-hr-soft);
            border-left: 1px solid rgba(199, 94, 60, 0.35);
            border-right: 1px solid rgba(199, 94, 60, 0.35);
            z-index: 1;
            pointer-events: none;
        }
        .tl-workout-focused {
            background: rgba(199, 94, 60, 0.22);
            border-left: 2px solid var(--metric-hr);
            border-right: 2px solid var(--metric-hr);
        }
        .tl-workout-label {
            position: absolute;
            top: 4px;
            font-size: 10px;
            font-weight: 500;
            color: var(--metric-hr);
            background: rgba(255, 255, 255, 0.92);
            padding: 1px 6px;
            border-radius: 3px;
            z-index: 3;
            white-space: nowrap;
        }
        .tl-col, .hr-col, .steps-col, .dist-col, .floors-col, .azm-col {
            position: relative;
            z-index: 2;  /* on top of workout band */
        }
```

- [ ] **Step 5: Run test, verify it passes**

```
pytest tests/test_timeline.py -v
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add foodlog/api/routers/timeline.py foodlog/templates/dashboard/timeline_partial.html foodlog/templates/base.html tests/test_timeline.py
git commit -m "feat(timeline): overlay workout bands and meal dots"
```

---

### Task 17: Date navigation header

**Files:**
- Modify: `foodlog/templates/dashboard/timeline.html`
- Modify: `foodlog/templates/base.html`
- Modify: `tests/test_timeline.py`

Header gets prev arrow, day label (which is also the date picker), next arrow, conditional "Today" pill.

- [ ] **Step 1: Write the failing test**

```python
def test_timeline_header_has_date_navigation(db_session):
    from foodlog.api.app import create_app
    client = TestClient(create_app())
    r = client.get("/dashboard/timeline?date=2026-04-12")
    assert r.status_code == 200
    assert 'class="tl-nav-prev"' in r.text
    assert 'class="tl-nav-next"' in r.text
    # Today is shown only when not on today
    assert 'class="tl-nav-today"' in r.text
    # Date picker form
    assert 'name="date"' in r.text


def test_timeline_header_hides_today_when_on_today(db_session):
    from foodlog.api.app import create_app
    client = TestClient(create_app())
    r = client.get("/dashboard/timeline")  # defaults to today
    assert 'class="tl-nav-today"' not in r.text
```

- [ ] **Step 2: Run tests, verify they fail**

```
pytest tests/test_timeline.py::test_timeline_header_has_date_navigation tests/test_timeline.py::test_timeline_header_hides_today_when_on_today -v
```
Expected: FAIL.

- [ ] **Step 3: Update the timeline template**

Replace the `<header>` block in `timeline.html`:

```jinja
{% set prev_day = day - one_day %}
{% set next_day = day + one_day %}

<header class="topbar tl-topbar">
  <div class="brand">
    <span class="mark"><span class="dot"></span>FoodLog</span>
  </div>

  <nav class="tl-nav">
    <a class="tl-nav-prev" href="/dashboard/timeline?date={{ prev_day.isoformat() }}" aria-label="Previous day">‹</a>

    <form class="tl-nav-picker" method="get" action="/dashboard/timeline">
      <label class="tl-nav-day">{{ day.strftime('%a, %b %-d') }}</label>
      <input type="date" name="date" value="{{ day.isoformat() }}" onchange="this.form.submit()">
    </form>

    <a class="tl-nav-next" href="/dashboard/timeline?date={{ next_day.isoformat() }}" aria-label="Next day">›</a>

    {% if not is_today %}
      <a class="tl-nav-today" href="/dashboard/timeline">Today</a>
    {% endif %}
  </nav>
</header>
```

- [ ] **Step 4: Pass `one_day` to the template**

In `foodlog/api/routers/timeline.py`, add to the context dict:

```python
            "one_day": datetime.timedelta(days=1),
```

- [ ] **Step 5: Add CSS**

```css
        .tl-topbar {
            justify-content: space-between;
        }
        .tl-nav {
            display: flex;
            align-items: center;
            gap: 0.6rem;
        }
        .tl-nav a {
            color: var(--ink-soft);
            text-decoration: none;
            padding: 0.3rem 0.6rem;
            border-radius: 4px;
        }
        .tl-nav a:hover { background: var(--bg-sunk); }
        .tl-nav-prev, .tl-nav-next {
            font-size: 1.4rem;
            line-height: 1;
        }
        .tl-nav-picker {
            position: relative;
        }
        .tl-nav-day {
            font-weight: 500;
            font-size: 0.95rem;
            padding: 0.2rem 0.4rem;
        }
        .tl-nav-picker input[type="date"] {
            position: absolute;
            inset: 0;
            opacity: 0;
            cursor: pointer;
            font-family: inherit;
        }
        .tl-nav-today {
            font-size: 0.85rem;
            color: var(--accent);
            border: 1px solid var(--accent);
            border-radius: 999px;
            padding: 0.15rem 0.7rem;
        }
```

- [ ] **Step 6: Run tests, verify they pass**

```
pytest tests/test_timeline.py -v
```
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add foodlog/templates/dashboard/timeline.html foodlog/templates/base.html foodlog/api/routers/timeline.py tests/test_timeline.py
git commit -m "feat(timeline): date navigation header (prev / picker / next / Today)"
```

---

### Task 18: `?focus=` highlights the workout band

**Files:**
- Test: `tests/test_timeline.py`

`_is_focused` is already wired up in Task 16 — this task adds an explicit test confirming the focused class actually appears when the param matches.

- [ ] **Step 1: Write the focused-class test**

```python
def test_timeline_focus_param_highlights_matching_workout(db_session):
    from foodlog.api.app import create_app
    from foodlog.db.models import Workout

    db_session.add(Workout(
        external_id="walk-2",
        start_at=datetime.datetime(2026, 4, 12, 12, 0, 0),
        end_at=datetime.datetime(2026, 4, 12, 12, 47, 0),
        activity_type="Walk", duration_min=47,
        calories_kcal=300.0, distance_m=3500.0,
        avg_hr=112, max_hr=145, source="FITBIT",
    ))
    db_session.commit()

    client = TestClient(create_app())

    # Without focus → standard band, no focused class
    r1 = client.get("/dashboard/timeline?date=2026-04-12")
    assert 'class="tl-workout-band"' in r1.text
    assert 'tl-workout-focused' not in r1.text

    # With matching focus → focused class
    r2 = client.get("/dashboard/timeline?date=2026-04-12&focus=12:00-12:47")
    assert 'tl-workout-focused' in r2.text

    # With mismatched focus → no focused class
    r3 = client.get("/dashboard/timeline?date=2026-04-12&focus=09:00-10:00")
    assert 'tl-workout-focused' not in r3.text
```

- [ ] **Step 2: Run test, verify it passes (no implementation change needed)**

```
pytest tests/test_timeline.py::test_timeline_focus_param_highlights_matching_workout -v
```
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_timeline.py
git commit -m "test(timeline): cover focus query param highlighting"
```

---

### Task 19: Landscape `@media` rule + pill switcher

**Files:**
- Modify: `foodlog/templates/dashboard/timeline_partial.html`
- Modify: `foodlog/templates/base.html`
- Modify: `tests/test_timeline.py`

CSS-only swap to single-chart immersive mode in landscape. Default active metric = HR via `:target`-style hash routing.

- [ ] **Step 1: Write the failing test**

```python
def test_timeline_renders_landscape_pill_strip(db_session):
    from foodlog.api.app import create_app
    client = TestClient(create_app())
    r = client.get("/dashboard/timeline")
    assert r.status_code == 200
    # Pills have anchor links for hash routing; HR is default
    assert 'class="tl-pill"' in r.text
    assert 'href="#tl-hr"' in r.text
    assert 'href="#tl-steps"' in r.text
    assert 'href="#tl-azm"' in r.text
```

- [ ] **Step 2: Run test, verify it fails**

```
pytest tests/test_timeline.py::test_timeline_renders_landscape_pill_strip -v
```
Expected: FAIL.

- [ ] **Step 3: Wrap each panel in an id and add the pill strip**

In `timeline_partial.html`, wrap each panel's outer `div` with an `id`. Replace the existing `<div class="tl-panel tl-panel-hr">` opening with:

```jinja
  <div id="tl-hr" class="tl-panel tl-panel-hr">
```

Same pattern for steps/distance/floors/azm: ids `tl-steps`, `tl-distance`, `tl-floors`, `tl-azm`.

At the **top** of `<section class="timeline-section" ...>`, immediately after the meal-strip, add:

```jinja
  <nav class="tl-pill-strip" aria-label="Switch metric (landscape)">
    <a class="tl-pill" href="#tl-hr">Heart rate</a>
    <a class="tl-pill" href="#tl-steps">Steps</a>
    <a class="tl-pill" href="#tl-distance">Distance</a>
    <a class="tl-pill" href="#tl-floors">Floors</a>
    <a class="tl-pill" href="#tl-azm">AZM</a>
  </nav>
```

- [ ] **Step 4: Add CSS**

In `base.html` `<style>`:

```css
        /* Pills hidden in portrait */
        .tl-pill-strip { display: none; }

        @media (orientation: landscape) and (max-width: 1024px) {
            .tl-pill-strip {
                display: flex;
                gap: 0.4rem;
                padding: 0.4rem 0;
                overflow-x: auto;
                margin-bottom: 0.5rem;
            }
            .tl-pill {
                font-size: 0.8rem;
                padding: 0.3rem 0.7rem;
                border-radius: 999px;
                background: var(--bg-sunk);
                color: var(--ink-soft);
                text-decoration: none;
                white-space: nowrap;
            }
            .tl-pill:focus,
            .tl-pill:hover {
                background: var(--accent);
                color: white;
            }
            /* In landscape, hide all panels by default; show the targeted one */
            .timeline-section .tl-panel { display: none; }
            .timeline-section .tl-panel:target { display: block; }
            /* Default to HR when no hash */
            .timeline-section:not(:has(.tl-panel:target)) #tl-hr { display: block; }
            /* The targeted panel takes the full viewport */
            .tl-panel:target .tl-chart { height: 60vh; }
        }
```

- [ ] **Step 5: Run test, verify it passes**

```
pytest tests/test_timeline.py -v
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add foodlog/templates/dashboard/timeline_partial.html foodlog/templates/base.html tests/test_timeline.py
git commit -m "feat(timeline): landscape single-chart mode with pill switcher"
```

---

### Task 20: "→ Timeline" deep-link on workout cards

**Files:**
- Modify: `foodlog/templates/dashboard/movement_partial.html`
- Modify: `tests/test_dashboard.py` (or whichever existing dashboard test file covers movement_partial)

- [ ] **Step 1: Find the relevant test file**

Run `grep -l "mv-card\|movement_partial\|workout_views" tests/`. The hits identify the test file to extend.

- [ ] **Step 2: Write the failing test**

In the appropriate test file, add:

```python
def test_workout_card_has_timeline_deep_link(db_session):
    from foodlog.api.app import create_app
    from foodlog.db.models import Workout

    db_session.add(Workout(
        external_id="walk-3",
        start_at=datetime.datetime(2026, 4, 12, 12, 0, 0),
        end_at=datetime.datetime(2026, 4, 12, 12, 47, 0),
        activity_type="Walk", duration_min=47,
        calories_kcal=300.0, distance_m=3500.0,
        avg_hr=112, max_hr=145, source="FITBIT",
    ))
    db_session.commit()

    client = TestClient(create_app())
    r = client.get("/dashboard/feed?date_range=today")
    # The link points to the timeline with the right deep-link params
    assert "/dashboard/timeline?date=2026-04-12&amp;focus=12:00-12:47" in r.text
    assert ">→ Timeline<" in r.text or ">→ Timeline </" in r.text
```

(Adjust `date_range` value if the existing fixture date is different — read the existing test pattern.)

- [ ] **Step 3: Run test, verify it fails**

```
pytest tests/test_dashboard.py::test_workout_card_has_timeline_deep_link -v
```
Expected: FAIL.

- [ ] **Step 4: Add the link to the workout card**

In `foodlog/templates/dashboard/movement_partial.html`, find the closing `</div>` of the workout card (after the `<div class="mv-card-sub">` line that ends "peak X"). Just before that closing `</div>` add:

```jinja
          <a class="mv-card-link"
             href="/dashboard/timeline?date={{ w.start_at_date }}&focus={{ w.start_hhmm }}-{{ w.end_hhmm }}">→ Timeline</a>
```

In `foodlog/api/routers/dashboard.py`, where workout_views are built (currently around line 145–160), add the three new fields to each view dict:

```python
            "start_at_date": w.start_at.date().isoformat(),
            "start_hhmm":    w.start_at.strftime("%H:%M"),
            "end_hhmm":      w.end_at.strftime("%H:%M"),
```

- [ ] **Step 5: Add CSS**

```css
        .mv-card-link {
            display: block;
            text-align: right;
            font-size: 0.8rem;
            color: var(--accent);
            text-decoration: none;
            margin-top: 0.4rem;
        }
        .mv-card-link:hover { text-decoration: underline; }
```

- [ ] **Step 6: Run test, verify it passes**

```
pytest tests/test_dashboard.py -v
```
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add foodlog/templates/dashboard/movement_partial.html foodlog/api/routers/dashboard.py foodlog/templates/base.html tests/test_dashboard.py
git commit -m "feat(dashboard): add → Timeline deep-link on workout cards"
```

---

### Task 21: Empty / future-day states

**Files:**
- Modify: `foodlog/templates/dashboard/timeline_partial.html`
- Modify: `foodlog/api/routers/timeline.py`
- Modify: `tests/test_timeline.py`

If no data for the day, show an empty-state card instead of five empty charts.

- [ ] **Step 1: Write the failing test**

```python
def test_timeline_empty_state_when_no_data(db_session):
    from foodlog.api.app import create_app
    client = TestClient(create_app())
    r = client.get("/dashboard/timeline?date=2024-01-01")
    assert r.status_code == 200
    assert "no data" in r.text.lower()
    # Charts should not render
    assert 'class="tl-chart"' not in r.text


def test_timeline_future_day_shows_empty_state(db_session):
    from foodlog.api.app import create_app
    future = datetime.date.today() + datetime.timedelta(days=2)
    client = TestClient(create_app())
    r = client.get(f"/dashboard/timeline?date={future.isoformat()}")
    assert r.status_code == 200
    assert "no data" in r.text.lower()
```

- [ ] **Step 2: Run tests, verify they fail**

```
pytest tests/test_timeline.py::test_timeline_empty_state_when_no_data tests/test_timeline.py::test_timeline_future_day_shows_empty_state -v
```
Expected: FAIL.

- [ ] **Step 3: Compute `has_data` in the router**

In `foodlog/api/routers/timeline.py`, after building all the slot lists, add:

```python
    has_data = (
        any(s is not None for s in hr_slots)
        or any(s is not None for s in steps_slots)
        or any(s is not None for s in dist_slots)
        or any(s is not None for s in floors_slots)
        or any(s is not None for s in azm_slots)
        or bool(workout_views)
        or bool(meal_views)
    )
```

Add `"has_data": has_data,` to the template context.

- [ ] **Step 4: Wrap the section in a conditional**

In `timeline_partial.html`, wrap the existing `<section class="timeline-section" ...>` block. At the very top of the file, replace the section opener with:

```jinja
{% if not has_data %}
  <section class="timeline-section">
    <div class="tl-empty">
      <p>No data for this day.</p>
      <p class="tl-empty-sub">If this is today, give the sync a moment and refresh.</p>
    </div>
  </section>
{% else %}
<section class="timeline-section" data-day="{{ day.isoformat() }}">
{% endif %}
```

And at the bottom of the partial, before the final `</section>`, close the conditional:

```jinja
{% if has_data %}
</section>
{% endif %}
```

(You'll need to remove the original `</section>` and add it inside the conditional. Re-read the file to make sure tags are balanced.)

- [ ] **Step 5: Add CSS**

```css
        .tl-empty {
            text-align: center;
            padding: 4rem 1rem;
            color: var(--muted);
        }
        .tl-empty p { margin: 0.4rem 0; }
        .tl-empty-sub { font-size: 0.85rem; }
```

- [ ] **Step 6: Run tests, verify they pass**

```
pytest tests/test_timeline.py -v
```
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add foodlog/templates/dashboard/timeline_partial.html foodlog/api/routers/timeline.py foodlog/templates/base.html tests/test_timeline.py
git commit -m "feat(timeline): empty state for days with no data"
```

---

### Task 22: Update `doc/HEALTH_DATA.md` master table

**Files:**
- Modify: `doc/HEALTH_DATA.md`

- [ ] **Step 1: Add three rows to the "What we currently collect" table**

Find the table under `## What we currently collect` and append (preserving alignment):

```
| Heart rate (sub-day) | Pixel Watch | `heart-rate` rollUp `900s` | 15-min avg/min/max | Cursor; chunks 14d slices; 90d on empty | `interval_heart_rate` |
| Activity intervals | Pixel Watch | `steps`/`distance`/`floors` rollUp `900s` | 15-min counters | Cursor; 90d on empty | `interval_activity` |
| AZM intervals | Pixel Watch | `active-zone-minutes` rollUp `900s` | 15-min by HR zone | Cursor; 90d on empty | `interval_azm` |
```

- [ ] **Step 2: Commit**

```bash
git add doc/HEALTH_DATA.md
git commit -m "docs(health): document granular interval metrics in master table"
```

---

### Task 23: End-to-end manual smoke test

**Files:**
- None — runtime verification only.

- [ ] **Step 1: Rebuild the container**

```bash
docker compose build foodlog && docker compose up -d foodlog
until curl -sf http://127.0.0.1:3474/healthz >/dev/null; do sleep 2; done
```

- [ ] **Step 2: Trigger a sync and check rows landed**

```bash
docker exec foodlog python -c "
import asyncio, httpx
from foodlog.api.dependencies import get_session_factory_cached
from foodlog.services.google_token import GoogleTokenService
from foodlog.clients.google_health import GoogleHealthClient
from foodlog.services.health_sync import HealthSyncService

async def main():
    factory = get_session_factory_cached()
    db = factory()
    try:
        async with httpx.AsyncClient(timeout=60.0) as http:
            tok = await GoogleTokenService(db).mint_access_token(http)
            client = GoogleHealthClient(http, access_token=tok.value)
            result = await HealthSyncService(db, client).sync_all()
            print('rows_upserted:', result.rows_upserted)
    finally:
        db.close()

asyncio.run(main())
"
```

Expected: nonzero counts for `interval_heart_rate`, `interval_activity`, `interval_azm`.

- [ ] **Step 3: Visit `/dashboard/timeline` and verify the page renders**

Open `https://foodlog.ryanckelly.ca/dashboard/timeline?date=2026-04-12` (a known walk-day from the spec).

Expected:
- HR panel shows range bars with avg dots
- Steps / distance / floors / AZM panels render
- Workout band overlays during the walk window
- Meal dots appear above the time axis
- Date navigation (prev / picker / next) works
- Rotating phone to landscape swaps to single-chart mode with pills

- [ ] **Step 4: Visit a deep-link from a workout card**

Click the "→ Timeline" link on a workout card on `/dashboard`. The destination should highlight that workout's band with the focused style.

- [ ] **Step 5: Optional commit**

If any small adjustments are needed (CSS tweaks, copy fixes), commit them under their own descriptive message.

---

## Self-Review Checklist

**Spec coverage (every spec section maps to one or more tasks):**

- ✅ Route `/dashboard/timeline?date=&focus=` — Task 12, 17, 18
- ✅ Portrait layout (5 stacked panels, shared time axis) — Tasks 13–15
- ✅ Landscape layout (single chart, pill switcher) — Task 19
- ✅ HR range bars + avg dot, fixed 40–180 BPM — Task 13
- ✅ Steps / distance / floors auto-scaled — Task 14
- ✅ AZM stacked — Task 15
- ✅ Workout bands + meal dots — Task 16
- ✅ Empty / future / pre-backfill empty states — Task 21
- ✅ Three storage tables — Task 1
- ✅ rollUp client (chunked 14-day for HR) — Tasks 3–6
- ✅ Three sync methods + sync_all wiring — Tasks 7–10
- ✅ "→ Timeline" workout card affordance — Task 20
- ✅ Doc update — Task 22
- ✅ End-to-end smoke — Task 23

**Type / name consistency:**

- Models, dataclasses, methods all reference the names locked in the "Naming reference" table.
- Slot-list shape `list[T | None]` of length 96 used consistently across HR / steps / distance / floors / AZM.
- `_pct(value, lo, hi)` helper introduced in Task 13, reused for HR Y-axis throughout.
- `_pct_of_day(dt)` helper introduced in Task 16, used for workout bands and meal dots.

**Placeholder scan:** None — every step has either runnable code or a precise file/line instruction.

**Out-of-scope correctly excluded:** Week / month views, replacing `workout_hr_samples`, configurable window size, Renpho cloud client, active-minutes endpoint.
