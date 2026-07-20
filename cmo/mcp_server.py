"""CMO Copilot MCP server — the marketing tool belt over the Model Context Protocol.

Exposes the system's analysis tools as MCP tools, so *any* MCP client — a Qwen agent
via an MCP bridge, Claude, an IDE — can diagnose and plan against the ad account
with the exact same audited, deterministic tools the system's own society and gated
memory use. Group-level rollups keep context O(groups), not O(300 campaigns);
`recommend_portfolio` returns a multi-item plan; every number traces to a tool call.

Run (stdio, for MCP clients):
    python mcp_server.py

The account it serves is deterministic (seed 42). Point `MCP_SCENARIO` at a
scenario id (e.g. M1 for the multi-issue case) to expose that situation; default is
the multi-issue account so the tools return something worth reasoning about.
"""
import os
from typing import Optional

from mcp.server.fastmcp import FastMCP

from cmo.datagen import generate_base
from cmo.scenarios import MULTI_ITEM_SCENARIO, SCENARIOS
from cmo.tools import ScenarioEnv

mcp = FastMCP("cmo-copilot")


def _account():
    sid = os.environ.get("MCP_SCENARIO", "M1")
    scenario = MULTI_ITEM_SCENARIO if sid == "M1" else next(
        (s for s in SCENARIOS if s["id"] == sid),
        {"id": "LIVE", "perturb": lambda rows, meta: None})
    return ScenarioEnv(generate_base(), scenario)


_env = _account()


@mcp.tool()
def get_campaign_metrics(group_id: Optional[str] = None) -> dict:
    """Prior-76-day vs recent-14-day metrics (spend, ROAS, CTR, CVR, flags) per
    campaign GROUP — the unit budget decisions are made in. Returns all 5 groups by
    default; each rolls up dozens of campaigns, so context stays O(groups)."""
    return _env.get_campaign_metrics(group_id)


@mcp.tool()
def get_group_campaigns(group_id: str, sort_by: str = "spend", limit: int = 10) -> dict:
    """Drill into the individual campaigns inside one group (bounded to 25 rows) —
    to see whether a group's move is broad-based or a few campaigns. sort_by:
    'spend' (largest first) or 'roas_change' (worst movers first)."""
    return _env.get_group_campaigns(group_id, sort_by=sort_by, limit=limit)


@mcp.tool()
def diagnose_drivers(group_id: str) -> dict:
    """Decompose a group's recent ROAS move into its causes — creative (CTR),
    targeting (CVR), offer mix (AOV), budget saturation (elasticity) — so you know
    WHICH fix a problem needs. A CTR collapse is a creative problem, not a budget one."""
    return _env.diagnose_drivers(group_id)


@mcp.tool()
def find_opportunities(limit: int = 5) -> dict:
    """Rank audiences by whether they deserve a campaign they don't have — cutting by
    AUDIENCE instead of by group. A segment can be a rounding error inside every group
    and still be the best thing in the account, which the group rollup cannot show."""
    return _env.find_opportunities(limit=limit)


@mcp.tool()
def find_losers(limit: int = 5) -> dict:
    """Rank audiences by whether they're structurally unprofitable — dead weight to
    KILL, not fix. The mirror of find_opportunities: a loser that's a rounding error
    inside every group is still visible when you cut by AUDIENCE."""
    return _env.find_losers(limit=limit)


@mcp.tool()
def recommend_portfolio(limit: int = 5) -> dict:
    """Assemble a MULTI-ITEM plan for the whole account in one call: each group's
    funnel fixes (a group can need both a creative refresh AND a targeting fix),
    budget-cap increases, plus new-campaign launches. Every item cites its evidence;
    a healthy account returns an empty plan."""
    return _env.recommend_portfolio(limit=limit)


@mcp.tool()
def forecast_impact(source_campaign: str, target_campaign: str, shift_pct: float) -> dict:
    """Model-based forecast of moving shift_pct%% of a source group's budget to a
    target group. Fits a response curve (revenue = a·spend^b) per group so saturation
    is priced in — prefer this over average ROAS."""
    return _env.forecast_impact(source_campaign, target_campaign, shift_pct)


@mcp.tool()
def propose_reallocation(source_campaign: str, target_campaign: str, shift_pct: float) -> dict:
    """Validate a reallocation against business constraints (brand floor, max weekly
    shift, learning phase). Returns {valid, violations}; does not execute."""
    return _env.propose_reallocation(source_campaign, target_campaign, shift_pct)


if __name__ == "__main__":
    mcp.run()   # stdio transport
