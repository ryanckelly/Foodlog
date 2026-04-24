"""Thin async HTTP client for the Google Health API (v4).

One method per logical data category. Each returns an async iterator
of normalized dataclasses so the sync service can upsert row-by-row
without loading full pages into memory.

Status per data type (as of first-sync exploration against live API):
    sleep               — ✓ implemented against real response shape
    steps               — ⚠ API returns minute-level samples (needs daily aggregation);
                           current parser assumes shape the API doesn't emit
    total-calories      — ✗ API rejects `list` action (requires `rollup` / `dailyRollup`);
                           different endpoint path than other types
    heart-rate, daily-resting-heart-rate
                        — ✗ filter field paths per Google docs return
                           "does not match any data type"; filter grammar
                           for these types is undocumented / needs probing
    weight, body-fat    — ? response shape unconfirmed (no data in test account);
                           parser follows same assumptions as steps
    exercise            — ? response shape unconfirmed (no workouts in test window)

All uncertain / known-broken endpoints are wrapped so a per-type failure
does NOT tank the whole sync — see `_paginate` (logs + empty) and
`HealthSyncService._sync_*` (per-type try/except + log + continue).
"""
from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass
from typing import AsyncIterator

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://health.googleapis.com"
API_VERSION = "v4"

# Verified against https://developers.google.com/health/data-types — endpoints use
# kebab-case in the URL path. Filters use camelCase field names with one of three
# timestamp shapes; see FILTER_FIELDS below.
DATA_TYPES = {
    "daily_steps": "steps",
    "daily_active_calories": "total-calories",
    "body_weight": "weight",
    "body_fat": "body-fat",
    "resting_heart_rate": "daily-resting-heart-rate",
    "heart_rate_sample": "heart-rate",
    "sleep_session": "sleep",
    "workout": "exercise",
}

# Per-endpoint filter grammar. Each entry: (filter field path, timestamp format).
# "civil"   → naive ISO8601 date-time, quoted: "2026-04-22T00:00:00"
# "date"    → ISO date only, quoted:          "2026-04-22"
# "rfc3339" → UTC RFC3339 with Z, quoted:     "2026-04-22T00:00:00Z"
FILTER_FIELDS: dict[str, tuple[str, str]] = {
    "steps":                    ("steps.interval.civil_start_time",             "civil"),
    "total-calories":           ("totalCalories.interval.civil_start_time",     "civil"),
    "weight":                   ("weight.sample_time.civil_time",               "civil"),
    "body-fat":                 ("bodyFat.sample_time.civil_time",              "civil"),
    "daily-resting-heart-rate": ("dailyRestingHeartRate.date",                  "date"),
    "heart-rate":               ("heartRate.sample_time.physical_time",         "rfc3339"),
    "sleep":                    ("sleep.interval.civil_end_time",               "civil"),
    "exercise":                 ("exercise.interval.civil_start_time",          "civil"),
}


def _fmt_filter_ts(dt: datetime.datetime, fmt: str) -> str:
    if fmt == "date":
        return dt.date().isoformat()
    if fmt == "civil":
        return dt.replace(tzinfo=None).isoformat(timespec="seconds")
    if fmt == "rfc3339":
        return dt.replace(tzinfo=None).isoformat(timespec="seconds") + "Z"
    raise ValueError(f"unknown filter timestamp format: {fmt}")


class GoogleHealthError(Exception):
    pass


class RateLimited(GoogleHealthError):
    pass


@dataclass(slots=True)
class DailyActivityRow:
    external_id: str
    date: datetime.date
    steps: int
    active_calories_kcal: float
    source: str


@dataclass(slots=True)
class BodyCompositionRow:
    external_id: str
    measured_at: datetime.datetime
    weight_kg: float | None
    body_fat_pct: float | None
    source: str


@dataclass(slots=True)
class RestingHeartRateRow:
    external_id: str
    measured_at: datetime.datetime
    bpm: int
    source: str


@dataclass(slots=True)
class SleepSessionRow:
    external_id: str
    start_at: datetime.datetime
    end_at: datetime.datetime
    duration_min: int
    source: str


@dataclass(slots=True)
class WorkoutRow:
    external_id: str
    start_at: datetime.datetime
    end_at: datetime.datetime
    activity_type: str
    duration_min: int
    calories_kcal: float | None
    distance_m: float | None
    avg_hr: int | None
    max_hr: int | None
    source: str


@dataclass(slots=True)
class HrSampleRow:
    workout_id: str
    sample_at: datetime.datetime
    bpm: int


def _parse_time(s: str) -> datetime.datetime:
    # Google returns RFC3339 UTC. Strip 'Z' so we store naive UTC.
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(datetime.UTC).replace(tzinfo=None)


def _source_from(data_source: dict) -> str:
    """Extract a human-readable source label from Google's nested dataSource.

    Prefers the device display name ("Pixel Watch 3"), falls back to platform
    ("FITBIT"), then empty string. Google stopped emitting `originDataSource`
    at the top level of each point in the v4 shape.
    """
    device = (data_source.get("device") or {})
    return device.get("displayName") or data_source.get("platform") or ""


class GoogleHealthClient:
    def __init__(self, http: httpx.AsyncClient, access_token: str):
        self._http = http
        self._token = access_token

    async def _paginate(
        self,
        data_type: str,
        since: datetime.datetime,
        until: datetime.datetime | None = None,
    ) -> AsyncIterator[dict]:
        url = f"{BASE_URL}/{API_VERSION}/users/me/dataTypes/{data_type}/dataPoints"
        field, fmt = FILTER_FIELDS[data_type]
        filter_parts = [f'{field} >= "{_fmt_filter_ts(since, fmt)}"']
        if until is not None:
            filter_parts.append(f'{field} < "{_fmt_filter_ts(until, fmt)}"')
        params = {"filter": " AND ".join(filter_parts)}
        headers = {"Authorization": f"Bearer {self._token}"}
        page_token = None
        while True:
            if page_token:
                params["pageToken"] = page_token
            resp = await self._http.get(url, params=params, headers=headers)
            if resp.status_code == 429:
                raise RateLimited("Google Health API rate limit")
            if resp.status_code >= 500:
                raise GoogleHealthError(
                    f"Google Health 5xx: {resp.status_code} body={resp.text[:500]}"
                )
            if resp.status_code >= 400:
                # Log and stop for this type — don't crash the whole sync.
                # Caller gets an empty iterator so other types can still run.
                logger.warning(
                    "google-health %s returned HTTP %d: %s",
                    data_type, resp.status_code, resp.text[:500],
                )
                return
            body = resp.json()
            for point in body.get("dataPoints", []):
                yield point
            page_token = body.get("nextPageToken") or None
            if not page_token:
                return

    async def list_daily_activity(
        self, since: datetime.datetime, until: datetime.datetime | None = None,
    ) -> AsyncIterator[DailyActivityRow]:
        # Daily activity comes from two data types; we'll fetch steps and
        # active-calories and join on date.
        steps_by_date: dict[datetime.date, tuple[int, str, str]] = {}
        async for pt in self._paginate(DATA_TYPES["daily_steps"], since, until):
            d = _parse_time(pt["startTime"]).date()
            steps_by_date[d] = (
                int(pt["value"]["intValue"]),
                pt.get("originDataSource", ""),
                pt["name"],
            )
        calories_by_date: dict[datetime.date, float] = {}
        async for pt in self._paginate(DATA_TYPES["daily_active_calories"], since, until):
            d = _parse_time(pt["startTime"]).date()
            calories_by_date[d] = float(pt["value"].get("floatValue", 0.0))
        for d, (steps, source, external_id) in sorted(steps_by_date.items()):
            yield DailyActivityRow(
                external_id=external_id,
                date=d,
                steps=steps,
                active_calories_kcal=calories_by_date.get(d, 0.0),
                source=source,
            )

    async def list_body_composition(
        self, since: datetime.datetime, until: datetime.datetime | None = None,
    ) -> AsyncIterator[BodyCompositionRow]:
        async for pt in self._paginate(DATA_TYPES["body_weight"], since, until):
            yield BodyCompositionRow(
                external_id=pt["name"],
                measured_at=_parse_time(pt["startTime"]),
                weight_kg=float(pt["value"]["floatValue"]),
                body_fat_pct=None,
                source=pt.get("originDataSource", ""),
            )
        async for pt in self._paginate(DATA_TYPES["body_fat"], since, until):
            yield BodyCompositionRow(
                external_id=pt["name"],
                measured_at=_parse_time(pt["startTime"]),
                weight_kg=None,
                body_fat_pct=float(pt["value"]["floatValue"]),
                source=pt.get("originDataSource", ""),
            )

    async def list_resting_heart_rate(
        self, since: datetime.datetime, until: datetime.datetime | None = None,
    ) -> AsyncIterator[RestingHeartRateRow]:
        async for pt in self._paginate(DATA_TYPES["resting_heart_rate"], since, until):
            yield RestingHeartRateRow(
                external_id=pt["name"],
                measured_at=_parse_time(pt["startTime"]),
                bpm=int(pt["value"]["intValue"]),
                source=pt.get("originDataSource", ""),
            )

    async def list_sleep_sessions(
        self, since: datetime.datetime, until: datetime.datetime | None = None,
    ) -> AsyncIterator[SleepSessionRow]:
        # Real shape (v4): pt = {
        #   "name": "users/.../dataPoints/<id>",
        #   "dataSource": {"device": {"displayName": "Pixel Watch 3"}, "platform": "FITBIT"},
        #   "sleep": {"interval": {"startTime": "...Z", "endTime": "...Z"}, "stages": [...]}
        # }
        async for pt in self._paginate(DATA_TYPES["sleep_session"], since, until):
            sleep = pt.get("sleep") or {}
            interval = sleep.get("interval") or {}
            start_s = interval.get("startTime")
            end_s = interval.get("endTime")
            name = pt.get("name")
            if not (start_s and end_s and name):
                logger.warning("google-health sleep point missing fields: %r", pt)
                continue
            start = _parse_time(start_s)
            end = _parse_time(end_s)
            yield SleepSessionRow(
                external_id=name,
                start_at=start,
                end_at=end,
                duration_min=int((end - start).total_seconds() // 60),
                source=_source_from(pt.get("dataSource") or {}),
            )

    async def list_workouts(
        self, since: datetime.datetime, until: datetime.datetime | None = None,
    ) -> AsyncIterator[WorkoutRow]:
        async for pt in self._paginate(DATA_TYPES["workout"], since, until):
            start = _parse_time(pt["startTime"])
            end = _parse_time(pt["endTime"])
            v = pt.get("value", {}) or {}
            extras = pt.get("aggregates", {}) or {}
            yield WorkoutRow(
                external_id=pt["name"],
                start_at=start,
                end_at=end,
                activity_type=v.get("activityType") or pt.get("activityType", "unknown"),
                duration_min=int((end - start).total_seconds() // 60),
                calories_kcal=extras.get("caloriesKcal"),
                distance_m=extras.get("distanceMeters"),
                avg_hr=extras.get("avgHeartRateBpm"),
                max_hr=extras.get("maxHeartRateBpm"),
                source=pt.get("originDataSource", ""),
            )

    async def list_workout_hr_samples(
        self,
        workout_id: str,
        start_at: datetime.datetime,
        end_at: datetime.datetime,
    ) -> AsyncIterator[HrSampleRow]:
        async for pt in self._paginate(DATA_TYPES["heart_rate_sample"], start_at, end_at):
            yield HrSampleRow(
                workout_id=workout_id,
                sample_at=_parse_time(pt["startTime"]),
                bpm=int(pt["value"]["intValue"]),
            )
