"""Read-only probe: which Pixel Watch / Health Connect data types does
the v4 REST API actually serve for this account, and what does each
payload look like?

Run inside the foodlog container:

    docker cp scripts/probe_pixel_watch_types.py foodlog:/tmp/
    docker exec foodlog python /tmp/probe_pixel_watch_types.py

Writes a JSON report to stdout. No DB writes, no sync side-effects.

Scope: investigates types listed in beads/foodlog-jav.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import sys
from typing import Any

import httpx
from sqlalchemy.orm import Session

from foodlog.config import settings
from foodlog.db.database import get_engine, get_session_factory
from foodlog.services.google_token import GoogleTokenService

BASE = "https://health.googleapis.com/v4"

LOOKBACK_DAYS = 14  # Look back 14 days to assess coverage (7 nights min)


# Each entry: (label, endpoint-kebab, filter-field-snake, filter-format)
# filter-format: "civil" / "date" / "rfc3339" / None (None = try without filter)
LIST_PROBES: list[tuple[str, str, str | None, str | None]] = [
    # ---- HRV ----
    # Health Connect type docs use HeartRateVariabilityRmssd; the v4 API kebab
    # we have not confirmed — try the obvious one and an alternate.
    ("hrv_interval", "heart-rate-variability",
        "heart_rate_variability.sample_time.physical_time", "rfc3339"),
    ("hrv_daily", "daily-heart-rate-variability",
        "daily_heart_rate_variability.date", "date"),
    ("hrv_rmssd_daily", "daily-heart-rate-variability-rmssd",
        "daily_heart_rate_variability_rmssd.date", "date"),

    # ---- SpO2 ----
    ("spo2_interval", "oxygen-saturation",
        "oxygen_saturation.sample_time.physical_time", "rfc3339"),
    ("spo2_daily", "daily-oxygen-saturation",
        "daily_oxygen_saturation.date", "date"),

    # ---- Respiratory rate ----
    ("resp_rate_daily", "daily-respiratory-rate",
        "daily_respiratory_rate.date", "date"),
    ("resp_rate_sleep", "respiratory-rate-sleep-summary",
        # Best-guess filter member; we'll see the API's complaint if wrong.
        "respiratory_rate_sleep_summary.sleep_session_start_time", "rfc3339"),

    # ---- Skin temperature (sleep) ----
    ("skin_temp_derivations", "daily-sleep-temperature-derivations",
        "daily_sleep_temperature_derivations.date", "date"),

    # ---- VO2 max / cardio fitness ----
    ("vo2_max", "vo2-max",
        "vo2_max.sample_time.physical_time", "rfc3339"),
    ("vo2_max_daily", "daily-vo2-max",
        "daily_vo2_max.date", "date"),
    ("vo2_max_run", "run-vo2-max",
        "run_vo2_max.sample_time.physical_time", "rfc3339"),

    # ---- Hydration (manual) ----
    ("hydration_log", "hydration-log",
        "hydration_log.sample_time.physical_time", "rfc3339"),

    # ---- Sanity checks: types we DO sync (should succeed) ----
    ("known_resting_hr", "daily-resting-heart-rate",
        "daily_resting_heart_rate.date", "date"),
    ("known_weight", "weight",
        "weight.sample_time.civil_time", "civil"),
]

# dailyRollUp probes: extra activity types we don't yet store.
DAILY_ROLLUP_PROBES: list[tuple[str, str]] = [
    ("rollup_distance", "distance"),
    ("rollup_floors", "floors"),
    ("rollup_basal_calories", "basal-energy-burned"),
    ("rollup_active_minutes", "active-minutes"),
    ("rollup_active_zone_minutes", "active-zone-minutes"),
    # Daily aggregates that may be exposed only via rollUp
    ("rollup_hrv", "heart-rate-variability"),
    ("rollup_spo2", "oxygen-saturation"),
    ("rollup_resp_rate", "respiratory-rate"),
]


def _fmt(dt_: dt.datetime, fmt: str) -> str:
    if fmt == "date":
        return dt_.date().isoformat()
    if fmt == "civil":
        return dt_.replace(tzinfo=None).isoformat(timespec="seconds")
    if fmt == "rfc3339":
        return dt_.replace(tzinfo=None).isoformat(timespec="seconds") + "Z"
    raise ValueError(fmt)


async def probe_list(
    http: httpx.AsyncClient,
    label: str,
    data_type: str,
    filter_field: str | None,
    fmt: str | None,
    token: str,
    since: dt.datetime,
) -> dict[str, Any]:
    url = f"{BASE}/users/me/dataTypes/{data_type}/dataPoints"
    headers = {"Authorization": f"Bearer {token}"}
    params: dict[str, Any] = {}
    if filter_field and fmt:
        params["filter"] = f'{filter_field} >= "{_fmt(since, fmt)}"'

    out: dict[str, Any] = {
        "label": label,
        "endpoint": data_type,
        "action": "list",
        "filter": params.get("filter"),
    }
    try:
        resp = await http.get(url, params=params, headers=headers, timeout=30)
    except httpx.HTTPError as e:
        out["http_error"] = str(e)
        return out

    out["status"] = resp.status_code
    body = resp.text
    try:
        parsed = resp.json()
    except json.JSONDecodeError:
        parsed = None

    if resp.status_code >= 400:
        # Capture error message verbatim — Google often hints at the right
        # field name in the error body.
        out["error_body"] = body[:800]
        return out

    points = (parsed or {}).get("dataPoints", []) if parsed else []
    out["point_count"] = len(points)
    if points:
        # First 2 points, redacted of nothing — we want full shape.
        out["sample_points"] = points[:2]
        # Try to infer time field for coverage
        days_seen: set[str] = set()
        for p in points:
            # Heuristic: walk one level deep looking for a date or physicalTime
            for v in p.values():
                if isinstance(v, dict):
                    st = v.get("sampleTime") or {}
                    ph = st.get("physicalTime")
                    if isinstance(ph, str) and len(ph) >= 10:
                        days_seen.add(ph[:10])
                    interval = v.get("interval") or {}
                    s = interval.get("startTime")
                    if isinstance(s, str) and len(s) >= 10:
                        days_seen.add(s[:10])
                    d = v.get("date")
                    if isinstance(d, dict):
                        try:
                            days_seen.add(f"{int(d['year']):04d}-{int(d['month']):02d}-{int(d['day']):02d}")
                        except (KeyError, ValueError, TypeError):
                            pass
        out["distinct_days"] = sorted(days_seen)
        out["coverage_days"] = len(days_seen)
    return out


async def probe_daily_rollup(
    http: httpx.AsyncClient,
    label: str,
    data_type: str,
    token: str,
    start: dt.date,
    end: dt.date,
) -> dict[str, Any]:
    url = f"{BASE}/users/me/dataTypes/{data_type}/dataPoints:dailyRollUp"
    body = {
        "range": {
            "start": {"date": {"year": start.year, "month": start.month, "day": start.day}, "time": {}},
            "end":   {"date": {"year": end.year, "month": end.month, "day": end.day},
                      "time": {"hours": 23, "minutes": 59, "seconds": 59}},
        },
        "windowSizeDays": 1,
    }
    out: dict[str, Any] = {
        "label": label,
        "endpoint": data_type,
        "action": "dailyRollUp",
    }
    try:
        resp = await http.post(url, json=body, headers={"Authorization": f"Bearer {token}"}, timeout=30)
    except httpx.HTTPError as e:
        out["http_error"] = str(e)
        return out

    out["status"] = resp.status_code
    if resp.status_code >= 400:
        out["error_body"] = resp.text[:800]
        return out
    try:
        parsed = resp.json()
    except json.JSONDecodeError:
        out["error_body"] = resp.text[:800]
        return out
    points = parsed.get("rollupDataPoints", []) or []
    out["point_count"] = len(points)
    if points:
        out["sample_points"] = points[:2]
        days = set()
        for p in points:
            cst = (p.get("civilStartTime") or {}).get("date") or {}
            try:
                days.add(f"{int(cst['year']):04d}-{int(cst['month']):02d}-{int(cst['day']):02d}")
            except (KeyError, ValueError, TypeError):
                pass
        out["distinct_days"] = sorted(days)
        out["coverage_days"] = len(days)
    return out


async def main() -> None:
    SessionFactory = get_session_factory(get_engine())
    db: Session = SessionFactory()
    try:
        token_svc = GoogleTokenService(db)
        async with httpx.AsyncClient() as http:
            tok = await token_svc.mint_access_token(http)
            since = dt.datetime.now(dt.UTC).replace(tzinfo=None) - dt.timedelta(days=LOOKBACK_DAYS)
            results: list[dict[str, Any]] = []
            for label, ep, ff, fmt in LIST_PROBES:
                r = await probe_list(http, label, ep, ff, fmt, tok.value, since)
                results.append(r)
            today = dt.date.today()
            start = today - dt.timedelta(days=LOOKBACK_DAYS)
            for label, ep in DAILY_ROLLUP_PROBES:
                r = await probe_daily_rollup(http, label, ep, tok.value, start, today)
                results.append(r)

        report = {
            "generated_at": dt.datetime.now(dt.UTC).isoformat(),
            "lookback_days": LOOKBACK_DAYS,
            "probes": results,
        }
        json.dump(report, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
