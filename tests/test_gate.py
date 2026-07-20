"""H3-2 — gate: expiry kills execution, reject reason persisted, adjust modifies shift."""
import json

import pytest

from tracks.track4.gate import (ApprovalRequest, GateDecision, parse_response,
                         post_to_slack, request_approval)


def _req():
    return ApprovalRequest(
        scenario="S01",
        plan={"root_cause": "creative_fatigue", "action": "shift_budget",
              "source_campaign": "G1", "target_campaign": "G5", "shift_pct": 20},
        expected_impact={"expected_daily_revenue_delta": 42.0},
        rollback_plan="reverse the manifest", alert_id="ALERT-S01")


def _read(path):
    return [json.loads(l) for l in open(path)]


# ------------------------------------------------------------------ expiry

def test_expiry_blocks_execution(tmp_path):
    ledger = tmp_path / "approvals.jsonl"
    d = request_approval(_req(), responder=lambda req, t: None, timeout_s=2, path=ledger)
    assert d.status == "expired"
    assert not d.approves_execution()
    payloads = _read(ledger)
    assert any(p["type"] == "approval_decision" and p["status"] == "expired" for p in payloads)


# ------------------------------------------------------------------ auto approve

def test_auto_approve(tmp_path):
    ledger = tmp_path / "approvals.jsonl"
    d = request_approval(_req(), auto_approve=True, path=ledger)
    assert d.status == "approved" and d.approves_execution()
    assert d.approver == "autopilot-auto"


# ------------------------------------------------------------------ reject

def test_reject_reason_persisted(tmp_path):
    ledger = tmp_path / "approvals.jsonl"
    d = request_approval(_req(), responder=lambda req, t: "reject too risky this week",
                         path=ledger)
    assert d.status == "rejected"
    assert "too risky this week" in d.reason
    assert not d.approves_execution()
    payloads = _read(ledger)
    assert any(p.get("reason", "").find("too risky") >= 0 for p in payloads)


# ------------------------------------------------------------------ adjust

def test_adjust_modifies_shift_pct(tmp_path):
    ledger = tmp_path / "approvals.jsonl"
    d = request_approval(_req(), responder=lambda req, t: "adjust 10", path=ledger)
    assert d.status == "adjusted"
    assert d.approves_execution()
    assert d.plan["shift_pct"] == 10


# ------------------------------------------------------------------ approve

def test_approve_keeps_plan(tmp_path):
    ledger = tmp_path / "approvals.jsonl"
    d = request_approval(_req(), responder=lambda req, t: "approve", path=ledger)
    assert d.status == "approved"
    assert d.plan["shift_pct"] == 20


# ------------------------------------------------------------------ parse unit

@pytest.mark.parametrize("resp,status", [
    ("approve", "approved"), ("APPROVE it", "approved"),
    ("adjust 12%", "adjusted"), ("reject bad idea", "rejected"),
    ("garbage", "rejected"),
])
def test_parse_response(resp, status):
    st, _, _ = parse_response(resp, {"shift_pct": 20})
    assert st == status


def test_request_is_logged_before_decision(tmp_path):
    ledger = tmp_path / "approvals.jsonl"
    request_approval(_req(), auto_approve=True, path=ledger)
    payloads = _read(ledger)
    assert payloads[0]["type"] == "approval_request"
    assert payloads[1]["type"] == "approval_decision"
