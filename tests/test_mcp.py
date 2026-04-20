import pytest
from mcp.server.auth.provider import AccessToken
from mcp.server.fastmcp import FastMCP

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
