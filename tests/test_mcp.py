from mcp.server.fastmcp import FastMCP

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
