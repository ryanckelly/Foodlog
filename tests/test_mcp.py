import datetime

import pytest
from mcp.server.auth.provider import AccessToken
from mcp.server.fastmcp import FastMCP

from foodlog.db.models import (
    BodyComposition,
    DailyActivity,
    RestingHeartRate,
    SleepSession,
    Workout,
    WorkoutHrSample,
)
from foodlog.services.oauth import FoodLogOAuthProvider, FoodLogTokenVerifier
from mcp_server.server import create_mcp_server


def test_mcp_server_has_tools():
    mcp = create_mcp_server()
    assert isinstance(mcp, FastMCP)
    tool_names = [t.name for t in mcp._tool_manager.list_tools()]
    assert "search_food" in tool_names
    assert "log_food" in tool_names
    assert "get_entries" in tool_names
    assert "edit_entry" in tool_names
    assert "delete_entry" in tool_names
    assert "get_daily_summary" in tool_names
    assert "get_daily_activity" in tool_names
    assert "get_sleep" in tool_names
    assert "get_resting_heart_rate" in tool_names
    assert "get_workouts" in tool_names
    assert "get_body_weight" in tool_names


def test_mcp_server_can_enable_oauth(db_session):
    mcp = create_mcp_server(
        auth_server_provider=FoodLogOAuthProvider(lambda: db_session),
        token_verifier=FoodLogTokenVerifier(lambda: db_session),
    )

    assert mcp.settings.auth is not None
    assert str(mcp.settings.auth.resource_server_url) == "https://foodlog.example.com/mcp"


def test_mcp_protected_resource_advertises_read_write_scopes(db_session):
    mcp = create_mcp_server(
        auth_server_provider=FoodLogOAuthProvider(lambda: db_session),
        token_verifier=FoodLogTokenVerifier(lambda: db_session),
    )

    assert mcp.settings.auth is not None
    assert mcp.settings.auth.required_scopes == ["foodlog.read", "foodlog.write"]


def test_mcp_tool_scope_policy_is_declared():
    from mcp_server.server import TOOL_REQUIRED_SCOPES

    assert TOOL_REQUIRED_SCOPES["search_food"] == ["foodlog.read"]
    assert TOOL_REQUIRED_SCOPES["get_entries"] == ["foodlog.read"]
    assert TOOL_REQUIRED_SCOPES["get_daily_summary"] == ["foodlog.read"]
    assert TOOL_REQUIRED_SCOPES["log_food"] == ["foodlog.write"]
    assert TOOL_REQUIRED_SCOPES["edit_entry"] == ["foodlog.write"]
    assert TOOL_REQUIRED_SCOPES["delete_entry"] == ["foodlog.write"]
    assert TOOL_REQUIRED_SCOPES["get_daily_activity"] == ["foodlog.read"]
    assert TOOL_REQUIRED_SCOPES["get_sleep"] == ["foodlog.read"]
    assert TOOL_REQUIRED_SCOPES["get_resting_heart_rate"] == ["foodlog.read"]
    assert TOOL_REQUIRED_SCOPES["get_workouts"] == ["foodlog.read"]
    assert TOOL_REQUIRED_SCOPES["get_body_weight"] == ["foodlog.read"]


def test_require_scope_allows_matching_scope(monkeypatch):
    from mcp_server import server

    monkeypatch.setattr(
        server,
        "get_access_token",
        lambda: AccessToken(
            token="token",
            client_id="client",
            scopes=["foodlog.read"],
            expires_at=9999999999,
            resource="https://foodlog.example.com/mcp",
        ),
    )

    server._require_scope("foodlog.read")


def test_require_scope_rejects_missing_scope(monkeypatch):
    from mcp_server import server

    monkeypatch.setattr(
        server,
        "get_access_token",
        lambda: AccessToken(
            token="token",
            client_id="client",
            scopes=["foodlog.read"],
            expires_at=9999999999,
            resource="https://foodlog.example.com/mcp",
        ),
    )

    with pytest.raises(PermissionError, match="Missing required scope"):
        server._require_scope("foodlog.write")


def _get_tool(mcp, name):
    for t in mcp._tool_manager.list_tools():
        if t.name == name:
            return t.fn
    raise AssertionError(f"tool {name} not registered")


def test_get_daily_activity_returns_rows_in_range(db_session):
    db_session.add_all([
        DailyActivity(
            date=datetime.date(2026, 5, 1),
            steps=8000,
            active_calories_kcal=300.0,
            source="watch",
            external_id="da-1",
        ),
        DailyActivity(
            date=datetime.date(2026, 5, 2),
            steps=12000,
            active_calories_kcal=520.0,
            source="watch",
            external_id="da-2",
        ),
        DailyActivity(
            date=datetime.date(2026, 5, 3),
            steps=4000,
            active_calories_kcal=150.0,
            source="watch",
            external_id="da-3",
        ),
    ])
    db_session.commit()

    mcp = create_mcp_server()
    fn = _get_tool(mcp, "get_daily_activity")
    result = fn(start_date="2026-05-01", end_date="2026-05-02")
    rows = result["items"]
    assert [r["date"] for r in rows] == ["2026-05-01", "2026-05-02"]
    assert rows[0]["steps"] == 8000
    assert rows[1]["active_calories_kcal"] == 520.0


def test_get_sleep_filters_by_start_at(db_session):
    db_session.add_all([
        SleepSession(
            external_id="s-1",
            start_at=datetime.datetime(2026, 5, 1, 23, 0),
            end_at=datetime.datetime(2026, 5, 2, 7, 0),
            duration_min=480,
            source="watch",
        ),
        SleepSession(
            external_id="s-2",
            start_at=datetime.datetime(2026, 5, 5, 23, 30),
            end_at=datetime.datetime(2026, 5, 6, 6, 30),
            duration_min=420,
            source="watch",
        ),
    ])
    db_session.commit()

    mcp = create_mcp_server()
    fn = _get_tool(mcp, "get_sleep")
    result = fn(start_date="2026-05-01", end_date="2026-05-01")
    rows = result["items"]
    assert len(rows) == 1
    assert rows[0]["duration_min"] == 480


def test_get_sleep_returns_stage_breakdown_when_present(db_session):
    """STAGES session exposes per-stage minute totals + metadata through MCP;
    CLASSIC/legacy rows return null for those fields so consumers can branch
    on `sleep_type` instead of guessing from missing keys."""
    db_session.add_all([
        SleepSession(
            external_id="s-stages",
            start_at=datetime.datetime(2026, 5, 18, 2, 17),
            end_at=datetime.datetime(2026, 5, 18, 9, 44, 30),
            duration_min=447,
            source="Pixel Watch 3",
            sleep_type="STAGES",
            nap=False,
            stages_status="SUCCEEDED",
            awake_min=42, light_min=245, deep_min=101, rem_min=59,
            asleep_min=405, in_period_min=447,
        ),
        SleepSession(
            external_id="s-legacy",
            start_at=datetime.datetime(2026, 5, 18, 23, 0),
            end_at=datetime.datetime(2026, 5, 19, 6, 30),
            duration_min=450,
            source="watch",
            # All stage fields default None — represents pre-foodlog-aul rows
        ),
    ])
    db_session.commit()

    mcp = create_mcp_server()
    fn = _get_tool(mcp, "get_sleep")
    result = fn(start_date="2026-05-18", end_date="2026-05-18")
    by_id = {r.get("sleep_type") or "legacy": r for r in result["items"]}

    s = by_id["STAGES"]
    assert s["nap"] is False
    assert s["stages_status"] == "SUCCEEDED"
    assert (s["awake_min"], s["light_min"], s["deep_min"], s["rem_min"]) == (42, 245, 101, 59)
    assert s["asleep_min"] == 405
    assert s["in_period_min"] == 447

    legacy = by_id["legacy"]
    assert legacy["sleep_type"] is None
    assert legacy["nap"] is None
    assert legacy["deep_min"] is None


def test_get_resting_heart_rate_returns_in_range(db_session):
    db_session.add_all([
        RestingHeartRate(
            external_id="r-1",
            measured_at=datetime.datetime(2026, 5, 1, 6, 0),
            bpm=58,
            source="watch",
        ),
        RestingHeartRate(
            external_id="r-2",
            measured_at=datetime.datetime(2026, 5, 9, 6, 0),
            bpm=61,
            source="watch",
        ),
    ])
    db_session.commit()

    mcp = create_mcp_server()
    fn = _get_tool(mcp, "get_resting_heart_rate")
    result = fn(start_date="2026-05-01", end_date="2026-05-02")
    rows = result["items"]
    assert len(rows) == 1
    assert rows[0]["bpm"] == 58


def test_get_workouts_excludes_hr_samples_by_default(db_session):
    workout = Workout(
        external_id="w-1",
        start_at=datetime.datetime(2026, 5, 2, 17, 0),
        end_at=datetime.datetime(2026, 5, 2, 17, 42),
        activity_type="run",
        duration_min=42,
        calories_kcal=410.0,
        distance_m=6800.0,
        avg_hr=152,
        max_hr=174,
        source="watch",
    )
    db_session.add(workout)
    db_session.flush()
    db_session.add_all([
        WorkoutHrSample(workout_id="w-1", sample_at=datetime.datetime(2026, 5, 2, 17, 5), bpm=148),
        WorkoutHrSample(workout_id="w-1", sample_at=datetime.datetime(2026, 5, 2, 17, 6), bpm=149),
    ])
    db_session.commit()

    mcp = create_mcp_server()
    fn = _get_tool(mcp, "get_workouts")
    rows = fn(start_date="2026-05-02", end_date="2026-05-02")["items"]
    assert len(rows) == 1
    assert rows[0]["activity_type"] == "run"
    assert rows[0]["distance_m"] == 6800.0
    assert "hr_samples" not in rows[0]

    rows_with = fn(
        start_date="2026-05-02", end_date="2026-05-02", include_hr_samples=True
    )["items"]
    assert len(rows_with[0]["hr_samples"]) == 2
    assert rows_with[0]["hr_samples"][0]["bpm"] == 148


def test_get_body_weight_returns_rows_in_range_ordered(db_session):
    db_session.add_all([
        BodyComposition(
            external_id="bw-2",
            measured_at=datetime.datetime(2026, 5, 2, 7, 30),
            weight_kg=78.4,
            body_fat_pct=None,
            source="scale",
        ),
        BodyComposition(
            external_id="bw-1",
            measured_at=datetime.datetime(2026, 5, 1, 7, 15),
            weight_kg=78.7,
            body_fat_pct=21.0,
            source="scale",
        ),
        BodyComposition(
            external_id="bw-out",
            measured_at=datetime.datetime(2026, 5, 9, 7, 0),
            weight_kg=78.1,
            body_fat_pct=None,
            source="scale",
        ),
    ])
    db_session.commit()

    mcp = create_mcp_server()
    fn = _get_tool(mcp, "get_body_weight")
    rows = fn(start_date="2026-05-01", end_date="2026-05-02")["items"]
    assert [r["measured_at"] for r in rows] == [
        "2026-05-01T07:15:00",
        "2026-05-02T07:30:00",
    ]
    assert rows[0]["weight_kg"] == 78.7
    assert rows[0]["source"] == "scale"
    assert "body_fat_pct" not in rows[0]


def test_get_body_weight_omits_null_weight(db_session):
    db_session.add_all([
        BodyComposition(
            external_id="bw-fat-only",
            measured_at=datetime.datetime(2026, 5, 1, 7, 0),
            weight_kg=None,
            body_fat_pct=22.5,
            source="scale",
        ),
        BodyComposition(
            external_id="bw-real",
            measured_at=datetime.datetime(2026, 5, 1, 7, 1),
            weight_kg=78.2,
            body_fat_pct=None,
            source="scale",
        ),
    ])
    db_session.commit()

    mcp = create_mcp_server()
    fn = _get_tool(mcp, "get_body_weight")
    rows = fn(start_date="2026-05-01", end_date="2026-05-01")["items"]
    assert len(rows) == 1
    assert rows[0]["weight_kg"] == 78.2


def test_resolve_range_rejects_inverted_dates():
    from mcp_server.server import _resolve_range

    with pytest.raises(ValueError, match="start_date must be on or before"):
        _resolve_range("2026-05-10", "2026-05-01", default_lookback_days=7)


def test_resolve_range_caps_max_window():
    from mcp_server.server import _resolve_range

    with pytest.raises(ValueError, match="Range exceeds"):
        _resolve_range("2025-01-01", "2026-05-01", default_lookback_days=7)
