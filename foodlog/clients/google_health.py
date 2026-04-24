"""Thin async HTTP client for the Google Health API (v4).

One method per logical data category. Each returns an async iterator
of normalized dataclasses so the sync service can upsert row-by-row
without loading full pages into memory.

Two request styles are used:
    list           GET  /v4/users/me/dataTypes/{type}/dataPoints?filter=...
    daily-rollup   POST /v4/users/me/dataTypes/{type}/dataPoints:dailyRollUp
                   with a civil-time range body. Used for ``steps`` and
                   ``total-calories`` where we want per-day totals and the
                   ``list`` granularity is minute-level (steps) or
                   unsupported (total-calories).

Filter grammar quirk (bit us hard during first-sync exploration): the
filter path uses the **snake_case** form of the data type name even though
most JSON fields are camelCase and the URL path is kebab-case. So the
correct filter path for heart-rate is ``heart_rate.sample_time.physical_time``,
NOT ``heartRate...``. ``FILTER_FIELDS`` below is the single source of truth.
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

# Endpoint data-type segments (kebab-case).
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

# Per-endpoint filter grammar for the `list` action. Each entry:
# (filter field path, timestamp format).
#
# Filter field path uses the **snake_case** data-type name as the prefix
# (see module docstring). Value field under that prefix is camelCase in
# JSON responses but snake_case in the filter expression.
#
# "civil"   → naive ISO8601 date-time, quoted: "2026-04-22T00:00:00"
# "date"    → ISO date only, quoted:          "2026-04-22"
# "rfc3339" → UTC RFC3339 with Z, quoted:     "2026-04-22T00:00:00Z"
FILTER_FIELDS: dict[str, tuple[str, str]] = {
    "steps":                    ("steps.interval.civil_start_time",               "civil"),
    "weight":                   ("weight.sample_time.civil_time",                 "civil"),
    "body-fat":                 ("body_fat.sample_time.civil_time",               "civil"),
    "daily-resting-heart-rate": ("daily_resting_heart_rate.date",                 "date"),
    "heart-rate":               ("heart_rate.sample_time.physical_time",          "rfc3339"),
    # Sleep's only valid filter member is civil_end_time (Google rejects
    # civil_start_time with INVALID_DATA_POINT_FILTER_DATA_TYPE_MEMBER). The
    # 500 we saw on civil_end_time was transient Google-side, not a grammar
    # issue — it reoccurs intermittently.
    "sleep":                    ("sleep.interval.civil_end_time",                 "civil"),
    "exercise":                 ("exercise.interval.civil_start_time",            "civil"),
    # total-calories `list` is unsupported by Google; we use dailyRollUp.
    # No filter entry needed.
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


def _parse_civil_date(d: dict) -> datetime.date:
    # {"year": 2026, "month": 4, "day": 23}
    return datetime.date(int(d["year"]), int(d["month"]), int(d["day"]))


def _source_from(data_source: dict | None) -> str:
    """Extract a human-readable source label from Google's nested dataSource.

    Prefers the device display name ("Pixel Watch 3"), falls back to platform
    ("FITBIT"), then empty string. Google stopped emitting `originDataSource`
    at the top level of each point in the v4 shape.
    """
    data_source = data_source or {}
    device = (data_source.get("device") or {})
    return device.get("displayName") or data_source.get("platform") or ""


def _synth_id(prefix: str, *parts: str) -> str:
    """Stable synthetic id for types where Google doesn't emit top-level `name`."""
    return prefix + "|" + "|".join(p for p in parts if p)


class GoogleHealthClient:
    def __init__(self, http: httpx.AsyncClient, access_token: str):
        self._http = http
        self._token = access_token

    @property
    def _auth_header(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

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
        page_token = None
        while True:
            if page_token:
                params["pageToken"] = page_token
            resp = await self._http.get(url, params=params, headers=self._auth_header)
            if resp.status_code == 429:
                raise RateLimited("Google Health API rate limit")
            if resp.status_code >= 500:
                raise GoogleHealthError(
                    f"Google Health 5xx: {resp.status_code} body={resp.text[:500]}"
                )
            if resp.status_code >= 400:
                # Log and stop for this type — don't crash the whole sync.
                logger.warning(
                    "google-health %s list returned HTTP %d: %s",
                    data_type, resp.status_code, resp.text[:500],
                )
                return
            body = resp.json()
            for point in body.get("dataPoints", []):
                yield point
            page_token = body.get("nextPageToken") or None
            if not page_token:
                return

    async def _daily_rollup(
        self,
        data_type: str,
        start_date: datetime.date,
        end_date: datetime.date,
    ) -> list[dict]:
        """POST :dailyRollUp. Returns rollupDataPoints list or [] on error."""
        url = (
            f"{BASE_URL}/{API_VERSION}/users/me/dataTypes/{data_type}/"
            f"dataPoints:dailyRollUp"
        )
        body = {
            "range": {
                "start": {
                    "date": {
                        "year": start_date.year,
                        "month": start_date.month,
                        "day": start_date.day,
                    },
                    "time": {},
                },
                "end": {
                    "date": {
                        "year": end_date.year,
                        "month": end_date.month,
                        "day": end_date.day,
                    },
                    "time": {"hours": 23, "minutes": 59, "seconds": 59},
                },
            },
            "windowSizeDays": 1,
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
                "google-health %s dailyRollUp returned HTTP %d: %s",
                data_type, resp.status_code, resp.text[:500],
            )
            return []
        return resp.json().get("rollupDataPoints", []) or []

    async def list_daily_activity(
        self, since: datetime.datetime, until: datetime.datetime | None = None,
    ) -> AsyncIterator[DailyActivityRow]:
        """Per-day steps and active calories via the dailyRollUp endpoint.

        `list` on `steps` returns minute-level samples (summing them would
        miss any daily-aggregated series Google pre-computes), and `list` on
        `total-calories` is rejected outright. dailyRollUp is the only
        endpoint that gives us per-civil-day totals for both.
        """
        start_date = since.date()
        end_date = (until.date() if until else datetime.date.today())

        steps_by_date: dict[datetime.date, tuple[int, str]] = {}
        calories_by_date: dict[datetime.date, float] = {}

        for pt in await self._daily_rollup(
            DATA_TYPES["daily_steps"], start_date, end_date,
        ):
            try:
                d = _parse_civil_date((pt.get("civilStartTime") or {}).get("date") or {})
                count = int((pt.get("steps") or {}).get("countSum", 0))
            except (KeyError, ValueError, TypeError):
                logger.warning("google-health steps rollup malformed: %r", pt)
                continue
            steps_by_date[d] = (count, _source_from(pt.get("dataSource")))

        for pt in await self._daily_rollup(
            DATA_TYPES["daily_active_calories"], start_date, end_date,
        ):
            try:
                d = _parse_civil_date((pt.get("civilStartTime") or {}).get("date") or {})
                # Field name under totalCalories isn't explicitly documented;
                # try several candidates observed in the rollup schema family.
                tc = pt.get("totalCalories") or {}
                # Confirmed against live API 2026-04-24: the field is `kcalSum`.
                # Other names kept as defensive fallbacks.
                kcal = (
                    tc.get("kcalSum")
                    or tc.get("energyKcalSum")
                    or tc.get("caloriesKcalSum")
                    or tc.get("kcal")
                    or 0.0
                )
                calories_by_date[d] = float(kcal)
            except (KeyError, ValueError, TypeError):
                logger.warning("google-health total-calories rollup malformed: %r", pt)
                continue

        for d in sorted(steps_by_date.keys() | calories_by_date.keys()):
            steps_val, source = steps_by_date.get(d, (0, ""))
            yield DailyActivityRow(
                external_id=_synth_id("daily-activity", d.isoformat()),
                date=d,
                steps=steps_val,
                active_calories_kcal=calories_by_date.get(d, 0.0),
                source=source,
            )

    async def list_body_composition(
        self, since: datetime.datetime, until: datetime.datetime | None = None,
    ) -> AsyncIterator[BodyCompositionRow]:
        # Weight: pt["weight"]["sampleTime"]["physicalTime"], pt["weight"]["weightGrams"]
        async for pt in self._paginate(DATA_TYPES["body_weight"], since, until):
            w = pt.get("weight") or {}
            sample = w.get("sampleTime") or {}
            phys = sample.get("physicalTime")
            grams = w.get("weightGrams")
            if not phys or grams is None:
                logger.warning("google-health weight point malformed: %r", pt)
                continue
            try:
                measured_at = _parse_time(phys)
                kg = float(grams) / 1000.0
            except (ValueError, TypeError):
                logger.warning("google-health weight value malformed: %r", pt)
                continue
            name = pt.get("name") or _synth_id(
                "weight", _source_from(pt.get("dataSource")), phys,
            )
            yield BodyCompositionRow(
                external_id=name,
                measured_at=measured_at,
                weight_kg=kg,
                body_fat_pct=None,
                source=_source_from(pt.get("dataSource")),
            )

        # Body fat: pt["bodyFat"]["sampleTime"]["physicalTime"], pt["bodyFat"]["percentage"]
        async for pt in self._paginate(DATA_TYPES["body_fat"], since, until):
            bf = pt.get("bodyFat") or {}
            sample = bf.get("sampleTime") or {}
            phys = sample.get("physicalTime")
            pct = bf.get("percentage")
            if not phys or pct is None:
                logger.warning("google-health body-fat point malformed: %r", pt)
                continue
            try:
                measured_at = _parse_time(phys)
                pct_f = float(pct)
            except (ValueError, TypeError):
                logger.warning("google-health body-fat value malformed: %r", pt)
                continue
            name = pt.get("name") or _synth_id(
                "body-fat", _source_from(pt.get("dataSource")), phys,
            )
            yield BodyCompositionRow(
                external_id=name,
                measured_at=measured_at,
                weight_kg=None,
                body_fat_pct=pct_f,
                source=_source_from(pt.get("dataSource")),
            )

    async def list_resting_heart_rate(
        self, since: datetime.datetime, until: datetime.datetime | None = None,
    ) -> AsyncIterator[RestingHeartRateRow]:
        # pt["dailyRestingHeartRate"]["date"] is a civil Date, beatsPerMinute is int64
        async for pt in self._paginate(DATA_TYPES["resting_heart_rate"], since, until):
            drhr = pt.get("dailyRestingHeartRate") or {}
            date_obj = drhr.get("date") or {}
            bpm = drhr.get("beatsPerMinute")
            if not date_obj or bpm is None:
                logger.warning("google-health resting-hr point malformed: %r", pt)
                continue
            try:
                d = _parse_civil_date(date_obj)
                bpm_i = int(bpm)
            except (KeyError, ValueError, TypeError):
                logger.warning("google-health resting-hr value malformed: %r", pt)
                continue
            # Anchor to UTC midnight of the civil date for a stable timestamp.
            measured_at = datetime.datetime.combine(d, datetime.time.min)
            name = pt.get("name") or _synth_id(
                "resting-hr", _source_from(pt.get("dataSource")), d.isoformat(),
            )
            yield RestingHeartRateRow(
                external_id=name,
                measured_at=measured_at,
                bpm=bpm_i,
                source=_source_from(pt.get("dataSource")),
            )

    async def list_sleep_sessions(
        self, since: datetime.datetime, until: datetime.datetime | None = None,
    ) -> AsyncIterator[SleepSessionRow]:
        # v4 shape: pt["sleep"]["interval"] = {"startTime", "endTime", ...}
        # `name` is present at top level for session types.
        async for pt in self._paginate(DATA_TYPES["sleep_session"], since, until):
            sleep = pt.get("sleep") or {}
            interval = sleep.get("interval") or {}
            start_s = interval.get("startTime")
            end_s = interval.get("endTime")
            if not (start_s and end_s):
                logger.warning("google-health sleep point missing interval: %r", pt)
                continue
            try:
                start = _parse_time(start_s)
                end = _parse_time(end_s)
            except (ValueError, TypeError):
                logger.warning("google-health sleep timestamps malformed: %r", pt)
                continue
            name = pt.get("name") or _synth_id(
                "sleep", _source_from(pt.get("dataSource")), start_s,
            )
            yield SleepSessionRow(
                external_id=name,
                start_at=start,
                end_at=end,
                duration_min=int((end - start).total_seconds() // 60),
                source=_source_from(pt.get("dataSource")),
            )

    async def list_workouts(
        self, since: datetime.datetime, until: datetime.datetime | None = None,
    ) -> AsyncIterator[WorkoutRow]:
        # v4 shape observed on live API 2026-04-24: pt["exercise"] = {
        #   "interval": {"startTime", "endTime", "startUtcOffset", ...},
        #   "exerciseType": "WALKING", "displayName": "Walk",
        #   "metricsSummary": {"caloriesKcal": 342, "distanceMillimeters",
        #                      "averageHeartRateBeatsPerMinute": "114" (STRING!),
        #                      "steps", "heartRateZoneDurations": {...}, ...}
        # }
        # Notably absent: maxHeartRateBeatsPerMinute. Google does not emit a
        # max-HR aggregate on the exercise record. Caller derives max_hr
        # from the workout's HR samples (see HealthSyncService).
        async for pt in self._paginate(DATA_TYPES["workout"], since, until):
            ex = pt.get("exercise") or {}
            interval = ex.get("interval") or {}
            start_s = interval.get("startTime")
            end_s = interval.get("endTime")
            if not (start_s and end_s):
                logger.warning("google-health exercise point missing interval: %r", pt)
                continue
            try:
                start = _parse_time(start_s)
                end = _parse_time(end_s)
            except (ValueError, TypeError):
                logger.warning("google-health exercise timestamps malformed: %r", pt)
                continue
            metrics = ex.get("metricsSummary") or {}
            distance_mm = metrics.get("distanceMillimeters")
            distance_m = None
            if distance_mm is not None:
                try:
                    distance_m = float(distance_mm) / 1000.0
                except (ValueError, TypeError):
                    distance_m = None
            try:
                cals = metrics.get("caloriesKcal")
                cals_f = float(cals) if cals is not None else None
            except (ValueError, TypeError):
                cals_f = None
            try:
                avg_hr = metrics.get("averageHeartRateBeatsPerMinute")
                avg_hr_i = int(avg_hr) if avg_hr is not None else None
            except (ValueError, TypeError):
                avg_hr_i = None
            # Google does not emit a max-HR aggregate; sync service derives
            # it from HR samples and upserts it back on the workout row.
            max_hr_i = None
            activity_type = (
                ex.get("displayName")
                or ex.get("exerciseType")
                or "unknown"
            )
            name = pt.get("name") or _synth_id(
                "exercise", _source_from(pt.get("dataSource")), start_s,
            )
            yield WorkoutRow(
                external_id=name,
                start_at=start,
                end_at=end,
                activity_type=activity_type,
                duration_min=int((end - start).total_seconds() // 60),
                calories_kcal=cals_f,
                distance_m=distance_m,
                avg_hr=avg_hr_i,
                max_hr=max_hr_i,
                source=_source_from(pt.get("dataSource")),
            )

    async def list_workout_hr_samples(
        self,
        workout_id: str,
        start_at: datetime.datetime,
        end_at: datetime.datetime,
    ) -> AsyncIterator[HrSampleRow]:
        # heart-rate shape: pt["heartRate"] = {
        #   "sampleTime": {"physicalTime": "...Z", "utcOffset": "..."},
        #   "beatsPerMinute": 148
        # }
        async for pt in self._paginate(DATA_TYPES["heart_rate_sample"], start_at, end_at):
            hr = pt.get("heartRate") or {}
            sample = hr.get("sampleTime") or {}
            phys = sample.get("physicalTime")
            bpm = hr.get("beatsPerMinute")
            if not phys or bpm is None:
                logger.warning("google-health heart-rate point malformed: %r", pt)
                continue
            try:
                sample_at = _parse_time(phys)
                bpm_i = int(bpm)
            except (ValueError, TypeError):
                logger.warning("google-health heart-rate value malformed: %r", pt)
                continue
            yield HrSampleRow(
                workout_id=workout_id,
                sample_at=sample_at,
                bpm=bpm_i,
            )
