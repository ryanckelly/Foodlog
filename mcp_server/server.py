import datetime

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import (
    AuthSettings,
    ClientRegistrationOptions,
    RevocationOptions,
)
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import AnyHttpUrl

from foodlog.api.dependencies import (
    get_fatsecret_client,
    get_session_factory_cached,
    get_usda_client,
)
from foodlog.config import settings
from foodlog.db.models import (
    BodyComposition,
    DailyActivity,
    DailyHrv,
    DailySleepTemperature,
    RestingHeartRate,
    SleepSession,
    Workout,
)
from foodlog.models.schemas import (
    FoodEntryCreate,
    FoodEntryResponse,
    FoodEntryUpdate,
)
from foodlog.services.logging import EntryService
from foodlog.services.nutrition import SummaryService
from foodlog.services.search import SearchService

TOOL_REQUIRED_SCOPES = {
    "search_food": ["foodlog.read"],
    "get_entries": ["foodlog.read"],
    "get_daily_summary": ["foodlog.read"],
    "log_food": ["foodlog.write"],
    "edit_entry": ["foodlog.write"],
    "delete_entry": ["foodlog.write"],
    "get_daily_activity": ["foodlog.read"],
    "get_sleep": ["foodlog.read"],
    "get_resting_heart_rate": ["foodlog.read"],
    "get_workouts": ["foodlog.read"],
    "get_body_weight": ["foodlog.read"],
    "get_daily_hrv": ["foodlog.read"],
    "get_daily_sleep_temperature": ["foodlog.read"],
}

MAX_RANGE_DAYS = 90


def _resolve_range(
    start_date: str | None,
    end_date: str | None,
    default_lookback_days: int,
) -> tuple[datetime.date, datetime.date]:
    today = datetime.date.today()
    end = datetime.date.fromisoformat(end_date) if end_date else today
    if start_date:
        start = datetime.date.fromisoformat(start_date)
    else:
        start = end - datetime.timedelta(days=default_lookback_days)
    if start > end:
        raise ValueError("start_date must be on or before end_date")
    span = (end - start).days
    if span > MAX_RANGE_DAYS:
        raise ValueError(f"Range exceeds {MAX_RANGE_DAYS} days (got {span})")
    return start, end


def _require_scope(scope: str) -> None:
    access_token = get_access_token()
    if access_token is None:
        return
    if scope not in access_token.scopes:
        raise PermissionError(f"Missing required scope: {scope}")


def _default_transport_security() -> TransportSecuritySettings:
    """Allow local, test, and public Cloudflare host headers."""
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[
            "127.0.0.1:*",
            "localhost:*",
            "[::1]:*",
            "foodlog",
            "foodlog:*",
            "foodlog.ryanckelly.ca",
            "foodlog.ryanckelly.ca:*",
            "foodlog.example.com",
            "foodlog.example.com:*",
            "testserver",  # for pytest TestClient
        ],
        allowed_origins=[
            "http://127.0.0.1:*",
            "http://localhost:*",
            "http://[::1]:*",
            "https://foodlog.ryanckelly.ca",
            "https://foodlog.ryanckelly.ca:*",
            "https://foodlog.example.com",
            "https://foodlog.example.com:*",
        ],
    )


def _auth_settings() -> AuthSettings:
    return AuthSettings(
        issuer_url=AnyHttpUrl(settings.public_base_url),
        resource_server_url=AnyHttpUrl(settings.public_mcp_resource_url),
        client_registration_options=ClientRegistrationOptions(
            enabled=True,
            valid_scopes=["foodlog.read", "foodlog.write"],
            default_scopes=["foodlog.read", "foodlog.write"],
        ),
        revocation_options=RevocationOptions(enabled=True),
        required_scopes=["foodlog.read", "foodlog.write"],
    )


def create_mcp_server(auth_server_provider=None, token_verifier=None) -> FastMCP:
    """Create the MCP server with tools that call services directly.

    Uses streamable_http_path='/mcp' so its routes can be composed at the
    FastAPI root alongside OAuth discovery endpoints.
    """
    auth_settings = None
    auth_kwargs = {}
    if auth_server_provider is not None or token_verifier is not None:
        auth_settings = _auth_settings()
        # FastMCP currently supports either authorization-server provider OR
        # resource-server verifier in one instance. FoodLog exposes auth-server
        # routes from FastAPI and uses FastMCP for protected /mcp resource routes.
        if token_verifier is not None:
            auth_kwargs["token_verifier"] = token_verifier
        else:
            auth_kwargs["auth_server_provider"] = auth_server_provider

    mcp = FastMCP(
        "FoodLog",
        instructions=(
            "Food logging assistant. Use search_food to find nutrition data, "
            "then log_food to record meals. Use get_daily_summary to show totals. "
            "Always search before logging to get accurate nutrition values. "
            "Synced health data is also available read-only: get_daily_activity "
            "(steps + active calories), get_sleep (sleep sessions with stage "
            "breakdown when available), get_resting_heart_rate (daily resting "
            "HR), get_daily_hrv (overnight HRV stats), get_daily_sleep_temperature "
            "(skin-temp deviations from personal baseline — useful for flagging "
            "illness/alcohol days), get_workouts (workouts with optional HR "
            "samples), and get_body_weight (body weight readings in kg)."
        ),
        streamable_http_path="/mcp",
        auth=auth_settings,
        **auth_kwargs,
        transport_security=_default_transport_security(),
    )

    @mcp.tool()
    async def search_food(query: str) -> dict:
        """Search the nutrition database for a food item.

        Returns matches with calories and macros per serving.
        Use this to find the right database match before logging.

        Args:
            query: Food name to search for (e.g. "chicken breast", "oat milk latte")
        """
        _require_scope("foodlog.read")
        svc = SearchService(
            fatsecret=get_fatsecret_client(),
            usda=get_usda_client(),
        )
        results = await svc.search(query)
        return {"items": [r.model_dump() for r in results]}

    @mcp.tool()
    def log_food(entries: list[dict]) -> dict:
        """Log one or more food items to the diary.

        Use after searching to include accurate nutrition data.
        Include the original user description in raw_input.

        Args:
            entries: Array of food entry objects. Each must include:
                meal_type (breakfast/lunch/dinner/snack), food_name, quantity,
                unit, calories, protein_g, carbs_g, fat_g, source, raw_input.
                Optional: weight_g, source_id, fiber_g, sugar_g, sodium_mg.
        """
        _require_scope("foodlog.write")
        session_factory = get_session_factory_cached()
        models = [FoodEntryCreate.model_validate(e) for e in entries]
        with session_factory() as session:
            svc = EntryService(session)
            results = svc.create_many(models)
            return {
                "items": [
                    FoodEntryResponse.model_validate(r).model_dump(mode="json")
                    for r in results
                ]
            }

    @mcp.tool()
    def get_entries(
        date: str | None = None, meal_type: str | None = None
    ) -> dict:
        """Get food diary entries. Defaults to today.

        Use to show the user what they've logged or to check before adding duplicates.

        Args:
            date: Date in YYYY-MM-DD format (default: today)
            meal_type: Filter by meal type (breakfast/lunch/dinner/snack)
        """
        _require_scope("foodlog.read")
        target_date = (
            datetime.date.fromisoformat(date) if date else datetime.date.today()
        )
        session_factory = get_session_factory_cached()
        with session_factory() as session:
            svc = EntryService(session)
            results = svc.get_by_date(target_date, meal_type=meal_type)
            return {
                "items": [
                    FoodEntryResponse.model_validate(r).model_dump(mode="json")
                    for r in results
                ]
            }

    @mcp.tool()
    def edit_entry(entry_id: int, updates: dict) -> dict:
        """Update a previously logged entry.

        Fix quantity, swap to a better match, change meal type.

        Args:
            entry_id: ID of the entry to update
            updates: Fields to update (e.g. {"quantity": 2.0, "calories": 495.0})
        """
        _require_scope("foodlog.write")
        session_factory = get_session_factory_cached()
        with session_factory() as session:
            svc = EntryService(session)
            update_model = FoodEntryUpdate.model_validate(updates)
            result = svc.update(entry_id, update_model)
            if result is None:
                raise ValueError(f"Entry {entry_id} not found")
            return FoodEntryResponse.model_validate(result).model_dump(mode="json")

    @mcp.tool()
    def delete_entry(entry_id: int) -> str:
        """Remove a food entry from the diary.

        Args:
            entry_id: ID of the entry to delete
        """
        _require_scope("foodlog.write")
        session_factory = get_session_factory_cached()
        with session_factory() as session:
            svc = EntryService(session)
            if not svc.delete(entry_id):
                raise ValueError(f"Entry {entry_id} not found")
            return f"Entry {entry_id} deleted"

    @mcp.tool()
    def get_daily_summary(date: str | None = None) -> dict:
        """Get total calories, protein, carbs, and fat for a day, broken down by meal.

        Defaults to today.

        Args:
            date: Date in YYYY-MM-DD format (default: today)
        """
        _require_scope("foodlog.read")
        target_date = (
            datetime.date.fromisoformat(date) if date else datetime.date.today()
        )
        session_factory = get_session_factory_cached()
        with session_factory() as session:
            svc = SummaryService(session)
            result = svc.daily(target_date)
            return result.model_dump(mode="json")

    @mcp.tool()
    def get_daily_activity(
        start_date: str | None = None, end_date: str | None = None
    ) -> dict:
        """Get daily step counts and active calories burned from synced health data.

        Sourced from Google Health (Fitbit, Wear OS, etc.). Defaults to today only.

        Args:
            start_date: Inclusive start date YYYY-MM-DD (default: end_date)
            end_date: Inclusive end date YYYY-MM-DD (default: today)
        """
        _require_scope("foodlog.read")
        start, end = _resolve_range(start_date, end_date, default_lookback_days=0)
        session_factory = get_session_factory_cached()
        with session_factory() as session:
            rows = (
                session.query(DailyActivity)
                .filter(DailyActivity.date >= start, DailyActivity.date <= end)
                .order_by(DailyActivity.date.asc())
                .all()
            )
            return {
                "items": [
                    {
                        "date": r.date.isoformat(),
                        "steps": r.steps,
                        "active_calories_kcal": r.active_calories_kcal,
                        "source": r.source,
                    }
                    for r in rows
                ]
            }

    @mcp.tool()
    def get_sleep(
        start_date: str | None = None, end_date: str | None = None
    ) -> dict:
        """Get sleep sessions for a date range.

        Filters by the session's start date. Defaults to the last 7 days.

        Each item includes session envelope (start_at, end_at, duration_min,
        source) and — when available — stage breakdown from Pixel Watch's
        STAGES sessions: sleep_type (STAGES/CLASSIC), nap, stages_status,
        and per-stage minute totals (awake_min, light_min, deep_min, rem_min,
        restless_min, asleep_min, in_period_min). Older rows and CLASSIC
        sessions return null for the stage fields.

        Args:
            start_date: Inclusive start date YYYY-MM-DD (default: 7 days before end_date)
            end_date: Inclusive end date YYYY-MM-DD (default: today)
        """
        _require_scope("foodlog.read")
        start, end = _resolve_range(start_date, end_date, default_lookback_days=7)
        start_dt = datetime.datetime.combine(start, datetime.time.min)
        end_dt = datetime.datetime.combine(
            end + datetime.timedelta(days=1), datetime.time.min
        )
        session_factory = get_session_factory_cached()
        with session_factory() as session:
            rows = (
                session.query(SleepSession)
                .filter(
                    SleepSession.start_at >= start_dt,
                    SleepSession.start_at < end_dt,
                )
                .order_by(SleepSession.start_at.asc())
                .all()
            )
            return {
                "items": [
                    {
                        "start_at": r.start_at.isoformat(),
                        "end_at": r.end_at.isoformat(),
                        "duration_min": r.duration_min,
                        "source": r.source,
                        "sleep_type": r.sleep_type,
                        "nap": r.nap,
                        "stages_status": r.stages_status,
                        "awake_min": r.awake_min,
                        "light_min": r.light_min,
                        "deep_min": r.deep_min,
                        "rem_min": r.rem_min,
                        "restless_min": r.restless_min,
                        "asleep_min": r.asleep_min,
                        "in_period_min": r.in_period_min,
                    }
                    for r in rows
                ]
            }

    @mcp.tool()
    def get_resting_heart_rate(
        start_date: str | None = None, end_date: str | None = None
    ) -> dict:
        """Get daily resting heart rate readings (BPM) for a date range.

        Defaults to the last 7 days.

        Args:
            start_date: Inclusive start date YYYY-MM-DD (default: 7 days before end_date)
            end_date: Inclusive end date YYYY-MM-DD (default: today)
        """
        _require_scope("foodlog.read")
        start, end = _resolve_range(start_date, end_date, default_lookback_days=7)
        start_dt = datetime.datetime.combine(start, datetime.time.min)
        end_dt = datetime.datetime.combine(
            end + datetime.timedelta(days=1), datetime.time.min
        )
        session_factory = get_session_factory_cached()
        with session_factory() as session:
            rows = (
                session.query(RestingHeartRate)
                .filter(
                    RestingHeartRate.measured_at >= start_dt,
                    RestingHeartRate.measured_at < end_dt,
                )
                .order_by(RestingHeartRate.measured_at.asc())
                .all()
            )
            return {
                "items": [
                    {
                        "measured_at": r.measured_at.isoformat(),
                        "bpm": r.bpm,
                        "source": r.source,
                    }
                    for r in rows
                ]
            }

    @mcp.tool()
    def get_daily_hrv(
        start_date: str | None = None, end_date: str | None = None
    ) -> dict:
        """Get overnight heart rate variability stats for a date range.

        Each item is one civil date with up to four metric fields populated
        from the Pixel Watch's daily-heart-rate-variability stream:
        - avg_hrv_ms: average HRV (RMSSD method) across the night, milliseconds
        - deep_sleep_rmssd_ms: RMSSD during deep sleep specifically
        - non_rem_hr_bpm: non-REM heart rate, beats per minute
        - entropy: Shannon entropy of heartbeat intervals (~2.8-3.4 typical)

        Defaults to the last 7 days. Any individual metric may be None on a
        given night when Google didn't compute it.

        Args:
            start_date: Inclusive start date YYYY-MM-DD (default: 7 days before end_date)
            end_date: Inclusive end date YYYY-MM-DD (default: today)
        """
        _require_scope("foodlog.read")
        start, end = _resolve_range(start_date, end_date, default_lookback_days=7)
        session_factory = get_session_factory_cached()
        with session_factory() as session:
            rows = (
                session.query(DailyHrv)
                .filter(DailyHrv.date >= start, DailyHrv.date <= end)
                .order_by(DailyHrv.date.asc())
                .all()
            )
            return {
                "items": [
                    {
                        "date": r.date.isoformat(),
                        "avg_hrv_ms": r.avg_hrv_ms,
                        "deep_sleep_rmssd_ms": r.deep_sleep_rmssd_ms,
                        "non_rem_hr_bpm": r.non_rem_hr_bpm,
                        "entropy": r.entropy,
                        "source": r.source,
                    }
                    for r in rows
                ]
            }

    @mcp.tool()
    def get_daily_sleep_temperature(
        start_date: str | None = None, end_date: str | None = None
    ) -> dict:
        """Get overnight skin-temperature stats for a date range.

        Per-night Pixel Watch readings (skin temp, not core body temp):
        - nightly_temp_c: tonight's measured skin temp during sleep
        - baseline_temp_c: user's 30-day baseline (computed by Google)
        - relative_stddev_30d_c: tonight's deviation from baseline expressed
          in units of the user's 30-day stddev — the headline 'unusual day'
          signal for illness (rises 2-3 days pre-symptom) and alcohol
          (raises baseline ~0.3-0.8 C).

        Defaults to the last 7 days.

        Args:
            start_date: Inclusive start date YYYY-MM-DD (default: 7 days before end_date)
            end_date: Inclusive end date YYYY-MM-DD (default: today)
        """
        _require_scope("foodlog.read")
        start, end = _resolve_range(start_date, end_date, default_lookback_days=7)
        session_factory = get_session_factory_cached()
        with session_factory() as session:
            rows = (
                session.query(DailySleepTemperature)
                .filter(DailySleepTemperature.date >= start,
                        DailySleepTemperature.date <= end)
                .order_by(DailySleepTemperature.date.asc())
                .all()
            )
            return {
                "items": [
                    {
                        "date": r.date.isoformat(),
                        "nightly_temp_c": r.nightly_temp_c,
                        "baseline_temp_c": r.baseline_temp_c,
                        "relative_stddev_30d_c": r.relative_stddev_30d_c,
                        "source": r.source,
                    }
                    for r in rows
                ]
            }

    @mcp.tool()
    def get_workouts(
        start_date: str | None = None,
        end_date: str | None = None,
        include_hr_samples: bool = False,
    ) -> dict:
        """Get workouts (type, duration, distance, calories, avg/max HR) for a date range.

        Filters by the workout's start date. Defaults to the last 7 days.
        Heart-rate sample arrays are excluded by default since they can be large
        (one reading per minute or so) — pass include_hr_samples=true to include them.

        Args:
            start_date: Inclusive start date YYYY-MM-DD (default: 7 days before end_date)
            end_date: Inclusive end date YYYY-MM-DD (default: today)
            include_hr_samples: Include per-minute HR samples for each workout (default: false)
        """
        _require_scope("foodlog.read")
        start, end = _resolve_range(start_date, end_date, default_lookback_days=7)
        start_dt = datetime.datetime.combine(start, datetime.time.min)
        end_dt = datetime.datetime.combine(
            end + datetime.timedelta(days=1), datetime.time.min
        )
        session_factory = get_session_factory_cached()
        with session_factory() as session:
            rows = (
                session.query(Workout)
                .filter(
                    Workout.start_at >= start_dt,
                    Workout.start_at < end_dt,
                )
                .order_by(Workout.start_at.asc())
                .all()
            )
            results = []
            for w in rows:
                item = {
                    "start_at": w.start_at.isoformat(),
                    "end_at": w.end_at.isoformat(),
                    "activity_type": w.activity_type,
                    "duration_min": w.duration_min,
                    "calories_kcal": w.calories_kcal,
                    "distance_m": w.distance_m,
                    "avg_hr": w.avg_hr,
                    "max_hr": w.max_hr,
                    "source": w.source,
                }
                if include_hr_samples:
                    item["hr_samples"] = [
                        {"sample_at": s.sample_at.isoformat(), "bpm": s.bpm}
                        for s in w.hr_samples
                    ]
                results.append(item)
            return {"items": results}

    @mcp.tool()
    def get_body_weight(
        start_date: str | None = None, end_date: str | None = None
    ) -> dict:
        """Get body weight readings (in kilograms) for a date range.

        Sourced from Google Health (smart scales, manual entries, etc.).
        Defaults to the last 90 days. Readings without a recorded weight
        value (body-fat-only entries) are omitted.

        Args:
            start_date: Inclusive start date YYYY-MM-DD (default: 90 days before end_date)
            end_date: Inclusive end date YYYY-MM-DD (default: today)
        """
        _require_scope("foodlog.read")
        start, end = _resolve_range(start_date, end_date, default_lookback_days=90)
        start_dt = datetime.datetime.combine(start, datetime.time.min)
        end_dt = datetime.datetime.combine(
            end + datetime.timedelta(days=1), datetime.time.min
        )
        session_factory = get_session_factory_cached()
        with session_factory() as session:
            rows = (
                session.query(BodyComposition)
                .filter(
                    BodyComposition.measured_at >= start_dt,
                    BodyComposition.measured_at < end_dt,
                    BodyComposition.weight_kg.isnot(None),
                )
                .order_by(BodyComposition.measured_at.asc())
                .all()
            )
            return {
                "items": [
                    {
                        "measured_at": r.measured_at.isoformat(),
                        "weight_kg": r.weight_kg,
                        "source": r.source,
                    }
                    for r in rows
                ]
            }

    return mcp


if __name__ == "__main__":
    # Kept for legacy compatibility — running as stdio no longer used in production
    # (MCP is mounted on FastAPI). This path remains for ad-hoc debugging.
    mcp = create_mcp_server()
    mcp.run(transport="stdio")
