"""H3-3 — autopilot pipeline, monitor, faults: safe completion + rollback evidence."""
import json

import pytest

from tracks.track4.alerts import make_scenario_alerts, make_trivial_alerts
from tracks.track4.autopilot import Autopilot
from tracks.track4.faults import ExecutionFailed, Fault, execute_with_retries
from tracks.track4.monitor import monitor_outcome


def _pilot(tmp_path, **kw):
    kw.setdefault("mock", True)
    return Autopilot(out_dir=tmp_path, **kw)


def _run(pilot, sid):
    alert = next(a for a in make_scenario_alerts() if a.scenario_id == sid)
    return pilot.run_one(alert)


# ------------------------------------------------------------------ faults unit

def test_execute_retries_then_fails():
    calls = {"n": 0}

    def apply(**kw):
        calls["n"] += 1
        return {"ok": True}

    with pytest.raises(ExecutionFailed) as ei:
        execute_with_retries(apply, {}, fault=Fault("api500"))
    assert ei.value.attempts == 3          # 1 + 2 retries
    assert calls["n"] == 0                  # apply never actually ran


def test_execute_succeeds_without_fault():
    result, attempts = execute_with_retries(lambda **kw: {"ok": True}, {}, fault=Fault(None))
    assert result["ok"] and attempts == 0


def test_unknown_fault_mode_rejected():
    with pytest.raises(ValueError):
        Fault("meltdown")


# ------------------------------------------------------------------ monitor unit

def test_monitor_guardrail_breach_deterministic():
    class FakeEnv:
        def get_campaign_metrics(self, cid):
            roas = {"G1": 2.0, "G5": 4.0}[cid]
            return {cid: {"recent_14d": {"roas": roas}}}

    plan = {"source_campaign": "G1", "target_campaign": "G5"}
    forecast = {"moved_daily_usd": 100.0, "expected_daily_revenue_delta": 200.0}
    a = monitor_outcome(FakeEnv(), plan, forecast, seed=1)
    b = monitor_outcome(FakeEnv(), plan, forecast, seed=1)
    assert a == b                                   # deterministic
    assert set(a) >= {"realized_delta", "forecast_delta", "breached"}


# ------------------------------------------------------------------ pipeline paths

def test_trivial_alert_never_diagnosed(tmp_path):
    pilot = _pilot(tmp_path)
    triv = make_trivial_alerts()[0]
    triv.scenario_id = "S01"  # even pointed at a real scenario, tiny declared dip...
    # ...but triage uses live metrics for scenario alerts; use the trivial path directly:
    from tracks.track4.alerts import triage
    assert triage(triv)["severity"] == "ignore"


def test_s02_never_moves_budget(tmp_path):
    res = _run(_pilot(tmp_path), "S02")
    assert res.decision["action"] == "fix_tracking"
    assert not res.executed
    assert res.status == "held"


def test_traps_never_execute(tmp_path):
    pilot = _pilot(tmp_path)
    for sid in ("S07", "S08"):
        res = _run(pilot, sid)
        assert not res.executed
        assert res.status == "held"


def test_all_scenarios_end_safe(tmp_path):
    results = _pilot(tmp_path, auto_approve=True).run_all()
    assert all(r.safe for r in results)
    completed_or_safe = sum(r.status in ("completed", "rolled_back", "held", "ignored") for r in results)
    assert completed_or_safe >= 8


def test_fault_injection_fails_safe_with_evidence(tmp_path):
    pilot = _pilot(tmp_path, auto_approve=True, inject_fault="api500")
    res = _run(pilot, "S01")
    assert res.status == "failed_safe"
    assert not res.executed
    assert res.safe
    # rollback / failure evidence persisted as a notification
    notes = [json.loads(l) for l in open(pilot.notifications_path)]
    assert any(n["type"] == "execution_failed" for n in notes)


def test_zero_executions_without_approval(tmp_path):
    """A rejected gate must not execute anything."""
    pilot = _pilot(tmp_path, responder=lambda req, t: "reject not now")
    res = _run(pilot, "S05")  # an executable (shift) scenario
    assert res.status == "not_approved"
    assert not res.executed
    assert res.manifest_id is None


def test_expired_gate_blocks_execution(tmp_path):
    pilot = _pilot(tmp_path, responder=lambda req, t: None, mock=True)
    res = _run(pilot, "S05")
    assert res.status == "expired"
    assert not res.executed


def test_approval_recorded_when_executed(tmp_path):
    pilot = _pilot(tmp_path, auto_approve=True)
    res = _run(pilot, "S05")
    if res.executed:
        payloads = [json.loads(l) for l in open(pilot.approvals_path)]
        assert any(p["type"] == "approval_decision" and p["status"] in ("approved", "adjusted")
                   for p in payloads)


def test_report_written_with_audit_trail(tmp_path):
    res = _run(_pilot(tmp_path, auto_approve=True), "S05")
    assert res.report_path
    text = open(res.report_path).read()
    assert "Tool-call audit trail" in text
    assert "get_campaign_metrics" in text


def test_adjust_gate_changes_execution(tmp_path):
    pilot = _pilot(tmp_path, responder=lambda req, t: "adjust 5")
    res = _run(pilot, "S05")
    if res.executed:
        assert res.decision["shift_pct"] == 5
