"""H3-2 — the human approval gate (Track 4).

An approval request carries a plan summary, expected impact, and a rollback plan.
Channels:
  - interactive CLI: approve / adjust <pct> / reject <reason>
  - --auto-approve: for harness/bench runs (records an auto-approval)
  - post_to_slack(): a webhook stub that appends to runs/approvals.jsonl.
    # SWAP: replace the file append below with a real Slack Incoming Webhook POST.

Expiry: if nobody answers within GATE_TIMEOUT_S (default 300; tests use 2), the
plan expires, is logged, and NOTHING executes. No zombie executions.
"""
import json
import os
from dataclasses import dataclass, field
from typing import Callable, Optional

from cmo.config import RUNS_DIR

GATE_TIMEOUT_S = float(os.environ.get("GATE_TIMEOUT_S", "300"))
APPROVED_STATES = ("approved", "adjusted")


@dataclass
class ApprovalRequest:
    scenario: str
    plan: dict                       # the proposed decision
    expected_impact: dict            # a forecast_roas result
    rollback_plan: str
    alert_id: Optional[str] = None

    def summary(self) -> str:
        p = self.plan
        move = (f"{p.get('action')} {p.get('shift_pct')}% "
                f"{p.get('source_campaign')}→{p.get('target_campaign')}"
                if p.get("action") in ("shift_budget", "increase_budget")
                else p.get("action"))
        impact = self.expected_impact.get("expected_daily_revenue_delta", "n/a")
        return (f"[{self.scenario}] Proposed: {move} (root: {p.get('root_cause')})\n"
                f"  Expected daily revenue delta: {impact}\n"
                f"  Rollback: {self.rollback_plan}")

    def to_payload(self) -> dict:
        return {"type": "approval_request", "scenario": self.scenario,
                "alert_id": self.alert_id, "plan": self.plan,
                "expected_impact": self.expected_impact, "rollback_plan": self.rollback_plan}


@dataclass
class GateDecision:
    status: str                      # approved | adjusted | rejected | expired
    approver: str
    reason: str = ""
    plan: Optional[dict] = None      # final (possibly adjusted) plan
    raw_response: str = ""

    def approves_execution(self) -> bool:
        return self.status in APPROVED_STATES

    def to_payload(self) -> dict:
        return {"type": "approval_decision", "status": self.status,
                "approver": self.approver, "reason": self.reason, "plan": self.plan}


def _approvals_path(path=None):
    RUNS_DIR.mkdir(exist_ok=True)
    return path or (RUNS_DIR / "approvals.jsonl")


def post_to_slack(payload: dict, path=None) -> dict:
    """Webhook stub. Appends the payload to the approvals ledger.
    # SWAP: POST `payload` to a real Slack Incoming Webhook URL here instead."""
    p = _approvals_path(path)
    with open(p, "a") as f:
        f.write(json.dumps(payload) + "\n")
    return {"posted": True, "channel": "stub-file", "path": str(p)}


def parse_response(resp: str, plan: dict):
    """Map a raw human response to (status, reason, final_plan)."""
    r = (resp or "").strip().lower()
    if r.startswith("approve"):
        return "approved", "", dict(plan)
    if r.startswith("adjust"):
        tokens = r.replace("%", " ").split()
        pct = next((float(t) for t in tokens if t.replace(".", "", 1).isdigit()), None)
        adjusted = dict(plan)
        if pct is not None:
            adjusted["shift_pct"] = pct
        return "adjusted", f"shift_pct set to {adjusted.get('shift_pct')}", adjusted
    if r.startswith("reject"):
        reason = resp.strip()[len("reject"):].strip(" :-") or "no reason given"
        return "rejected", reason, None
    return "rejected", f"unrecognized response: {resp!r}", None


def _cli_responder(req: ApprovalRequest, timeout_s: float) -> Optional[str]:  # pragma: no cover
    import select
    import sys
    print("\n=== APPROVAL REQUIRED ===")
    print(req.summary())
    print(f"Respond within {timeout_s:.0f}s [approve / adjust <pct> / reject <reason>]: ", end="", flush=True)
    ready, _, _ = select.select([sys.stdin], [], [], timeout_s)
    if not ready:
        return None
    return sys.stdin.readline().strip()


def request_approval(req: ApprovalRequest, *, auto_approve: bool = False,
                     responder: Optional[Callable] = None,
                     timeout_s: float = None, path=None) -> GateDecision:
    """Run the gate. `responder(req, timeout_s) -> str | None` (None => timed out).
    Defaults to the interactive CLI responder."""
    timeout_s = GATE_TIMEOUT_S if timeout_s is None else timeout_s
    post_to_slack(req.to_payload(), path=path)  # always log the request

    if auto_approve:
        decision = GateDecision("approved", approver="autopilot-auto",
                                reason="auto-approved for unattended run", plan=dict(req.plan))
        post_to_slack(decision.to_payload(), path=path)
        return decision

    responder = responder or _cli_responder
    resp = responder(req, timeout_s)
    if resp is None:
        decision = GateDecision("expired", approver="none",
                                reason=f"no response within {timeout_s:.0f}s; nothing executed")
    else:
        status, reason, final_plan = parse_response(resp, req.plan)
        decision = GateDecision(status, approver="human", reason=reason,
                                plan=final_plan, raw_response=resp)
    post_to_slack(decision.to_payload(), path=path)
    return decision
