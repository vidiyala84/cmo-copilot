"""The CMO Copilot MCP server exposes the tool belt over the Model Context Protocol."""
import asyncio
import json

import pytest

mcp_server = pytest.importorskip("cmo.mcp_server", reason="mcp SDK not installed")

EXPECTED_TOOLS = {"get_campaign_metrics", "get_group_campaigns", "diagnose_drivers",
                  "find_opportunities", "find_losers", "recommend_portfolio",
                  "forecast_impact", "propose_reallocation"}


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


def test_all_tools_are_registered():
    tools = _run(mcp_server.mcp.list_tools())
    assert {t.name for t in tools} == EXPECTED_TOOLS
    # every tool carries a description (its schema for the client)
    assert all(t.description for t in tools)


def test_recommend_portfolio_call_returns_a_plan():
    result = _run(mcp_server.mcp.call_tool("recommend_portfolio", {}))
    content = result[0] if isinstance(result, tuple) else result
    payload = json.loads(content[0].text)
    pairs = {(it.get("group"), it["action"]) for it in payload["items"]}
    # default account (M1) — a group with two fixes plus a launch
    assert ("G1", "refresh_creative") in pairs
    assert ("G1", "fix_targeting") in pairs
    assert (None, "launch_campaign") in pairs


def test_diagnose_drivers_call_is_structured():
    result = _run(mcp_server.mcp.call_tool("diagnose_drivers", {"group_id": "G1"}))
    content = result[0] if isinstance(result, tuple) else result
    payload = json.loads(content[0].text)
    assert "drivers" in payload and "creative" in payload["drivers"]
