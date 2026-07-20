"""H3-3 — the autopilot pipeline (Track 4).

alert -> triage -> diagnose -> propose (validate + replan) -> human gate ->
execute (with fault handling) -> monitor -> guardrail rollback -> closing report.

Nobody asked the agent anything: an alert fires and the pipeline carries it to a
sandboxed execution, pausing only at the human gate. Every terminal state is
safe — completed, held, not-approved, expired, rolled-back, or failed_safe —
never a silent half-execution.

    python -m track4.autopilot --all --mock --auto-approve
    python -m track4.autopilot --scenario S01 --mock --auto-approve --inject-fault api500
"""
import argparse
import json
from dataclasses import dataclass, field
from typing import List, Optional

from cmo.config import RUNS_DIR
from cmo.datagen import generate_base
from cmo.scenarios import SCENARIOS
from cmo.tools import ScenarioEnv
from tracks.track4.alerts import Alert, all_alerts, make_scenario_alerts, triage
from tracks.track4.faults import ExecutionFailed, Fault, execute_with_retries
from tracks.track4.gate import ApprovalRequest, request_approval
from tracks.track4.monitor import monitor_outcome, notify, reverse_manifest

MAX_REPLANS = 2
# Terminal states that count as a clean/safe outcome
SAFE_STATES = ("completed", "rolled_back", "held", "ignored", "not_approved",
               "expired", "failed_safe")


@dataclass
class RunResult:
    scenario: str
    alert_id: str
    status: str
    decision: dict = field(default_factory=dict)
    triage: dict = field(default_factory=dict)
    gate_status: Optional[str] = None
    executed: bool = False
    manifest_id: Optional[str] = None
    forecast_delta: Optional[float] = None
    realized_delta: Optional[float] = None
    rolled_back: bool = False
    replans: int = 0
    fault_mode: Optional[str] = None
    notifications: List[dict] = field(default_factory=list)
    report_path: Optional[str] = None
    tool_calls: int = 0
    steps: List[dict] = field(default_factory=list)
    tool_log: List[dict] = field(default_factory=list)

    @property
    def safe(self):
        return self.status in SAFE_STATES

    def to_dict(self):
        return {
            "scenario": self.scenario, "alert_id": self.alert_id, "status": self.status,
            "safe": self.safe, "decision": self.decision, "triage": self.triage,
            "gate_status": self.gate_status, "executed": self.executed,
            "manifest_id": self.manifest_id, "forecast_delta": self.forecast_delta,
            "realized_delta": self.realized_delta, "rolled_back": self.rolled_back,
            "replans": self.replans, "fault_mode": self.fault_mode,
            "notifications": self.notifications, "tool_calls": self.tool_calls,
            "steps": self.steps, "tool_log": self.tool_log,
        }


def _scenario(sid):
    return next(s for s in SCENARIOS if s["id"] == sid)


class Autopilot:
    def __init__(self, mock=True, auto_approve=False, inject_fault=None,
                 out_dir=None, responder=None, diagnose_agent=None, seed=42):
        self.mock = mock
        self.auto_approve = auto_approve
        self.fault = Fault(inject_fault)
        self.out_dir = out_dir or RUNS_DIR
        self.responder = responder
        self.seed = seed
        self.base_rows = generate_base(seed)
        if diagnose_agent is None:
            from tracks.track3.society import SocietyAgent
            diagnose_agent = SocietyAgent(mock=mock, transcripts_dir=self.out_dir / "transcripts")
        self.diagnose_agent = diagnose_agent
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.approvals_path = self.out_dir / "approvals.jsonl"
        self.notifications_path = self.out_dir / "notifications.jsonl"

    # ---------------------------------------------------------------- helpers

    def _notify(self, scenario, kind, message):
        return notify(self.out_dir, scenario, kind, message, path=self.notifications_path)

    def _validate_replan(self, env, decision):
        """Ensure the plan clears constraints; shrink the shift up to MAX_REPLANS
        times, else give up (caller holds)."""
        source = decision.get("source_campaign")
        target = decision.get("target_campaign")
        shift = decision.get("shift_pct") or 15
        replans = 0
        for candidate in (shift, 10, 5):
            res = env.call("propose_reallocation", {"source_campaign": source,
                           "target_campaign": target, "shift_pct": candidate})
            if res["valid"]:
                plan = dict(decision)
                plan["shift_pct"] = candidate
                return plan, replans, True
            replans += 1
            if replans > MAX_REPLANS:
                break
        return dict(decision), replans, False

    # ---------------------------------------------------------------- pipeline

    def run_one(self, alert: Alert) -> RunResult:
        env = ScenarioEnv(self.base_rows, _scenario(alert.scenario_id))
        res = RunResult(scenario=alert.scenario_id, alert_id=alert.id,
                        status="init", fault_mode=self.fault.mode)

        # 1) triage
        metrics = env.call("get_campaign_metrics", {})
        res.triage = triage(alert, metrics=metrics)
        if res.triage["severity"] == "ignore":
            res.status = "ignored"
            self._notify(alert.scenario_id, "triage_ignore", res.triage["reason"])
            res.report_path = self._write_report(env, res, [("triage", res.triage)])
            res.tool_calls = len(env.tool_log)
            return res

        # 2) diagnose
        decision = self.diagnose_agent.decide(env)
        res.decision = decision
        steps = [("triage", res.triage), ("diagnose", decision)]

        # tracking outage / patience / seasonality -> no budget move
        if decision["action"] in ("no_action", "fix_tracking"):
            res.status = "held"
            self._notify(alert.scenario_id, "no_execution",
                         f"diagnosis {decision['root_cause']} -> {decision['action']}; no budget moved")
            res.report_path = self._write_report(env, res, steps)
            res.tool_calls = len(env.tool_log)
            return res

        # 3) propose + validate (+ replan)
        plan, replans, valid = self._validate_replan(env, decision)
        res.replans = replans
        steps.append(("propose", {"plan": plan, "replans": replans, "valid": valid}))
        if not valid:
            res.status = "held"
            self._notify(alert.scenario_id, "no_compliant_plan",
                         "no constraint-compliant reallocation found; holding")
            res.report_path = self._write_report(env, res, steps)
            res.tool_calls = len(env.tool_log)
            return res

        forecast = env.call("forecast_roas", {
            "source_campaign": plan["source_campaign"],
            "target_campaign": plan["target_campaign"], "shift_pct": plan["shift_pct"]})
        res.forecast_delta = forecast.get("expected_daily_revenue_delta")

        # 4) human gate
        req = ApprovalRequest(scenario=alert.scenario_id, plan=plan, expected_impact=forecast,
                              rollback_plan="reverse the reallocation manifest (auto)",
                              alert_id=alert.id)
        gate = request_approval(req, auto_approve=self.auto_approve, responder=self.responder,
                                path=self.approvals_path)
        res.gate_status = gate.status
        steps.append(("gate", gate.to_payload()))
        if not gate.approves_execution():
            res.status = "expired" if gate.status == "expired" else "not_approved"
            self._notify(alert.scenario_id, "gate_" + gate.status,
                         f"plan {gate.status}: {gate.reason}")
            res.report_path = self._write_report(env, res, steps)
            res.tool_calls = len(env.tool_log)
            return res
        plan = gate.plan  # possibly adjusted
        res.decision = plan

        # 5) execute (idempotent, retried, fault-safe)
        try:
            manifest, attempts = execute_with_retries(
                env.apply_reallocation,
                {"source_campaign": plan["source_campaign"], "target_campaign": plan["target_campaign"],
                 "shift_pct": plan["shift_pct"], "approved_by": gate.approver},
                fault=self.fault)
        except ExecutionFailed as e:
            res.status = "failed_safe"
            note = self._notify(alert.scenario_id, "execution_failed",
                                f"{e.cause} after {e.attempts} attempts; partial rollback — "
                                f"verified no budget moved. failed_safe.")
            res.notifications.append(note)
            steps.append(("execute_failed", {"attempts": e.attempts, "cause": str(e.cause)}))
            res.report_path = self._write_report(env, res, steps)
            res.tool_calls = len(env.tool_log)
            return res

        res.executed = True
        res.manifest_id = manifest["manifest_id"]
        steps.append(("execute", {"manifest_id": manifest["manifest_id"], "attempts": attempts}))

        # 6) monitor + guardrail rollback
        mon = monitor_outcome(env, plan, forecast, seed=int(alert.scenario_id[1:]))
        res.realized_delta = mon["realized_delta"]
        steps.append(("monitor", mon))
        if mon["breached"]:
            rb = reverse_manifest(env, manifest)
            res.rolled_back = True
            res.status = "rolled_back"
            note = self._notify(alert.scenario_id, "guardrail_rollback",
                                f"realized {mon['realized_delta']} < 70% of forecast "
                                f"{mon['forecast_delta']}; reversed {manifest['manifest_id']} "
                                f"via {rb['manifest_id']}.")
            res.notifications.append(note)
            steps.append(("rollback", rb))
        else:
            res.status = "completed"

        res.report_path = self._write_report(env, res, steps)
        res.tool_calls = len(env.tool_log)
        return res

    def run_all(self, alerts=None) -> List[RunResult]:
        alerts = alerts if alerts is not None else make_scenario_alerts()
        return [self.run_one(a) for a in alerts]

    # ---------------------------------------------------------------- report

    def _write_report(self, env, res: RunResult, steps) -> str:
        # capture a JSON-friendly copy of the pipeline for the API/UI
        res.steps = [{"step": name, "data": json.loads(json.dumps(data, default=str))}
                     for name, data in steps]
        res.tool_log = [{"tool": e["tool"], "args": e.get("args", {})} for e in env.tool_log]
        path = self.out_dir / f"track4_report_{res.scenario}.md"
        lines = [f"# Autopilot run — {res.scenario} ({res.alert_id})", ""]
        lines.append(f"**Final status:** `{res.status}`  ")
        lines.append(f"**Executed:** {res.executed}"
                     + (f" (manifest `{res.manifest_id}`)" if res.manifest_id else "")
                     + (f"  ·  fault injected: `{res.fault_mode}`" if res.fault_mode else ""))
        if res.forecast_delta is not None:
            realized = res.realized_delta if res.realized_delta is not None else "—"
            lines.append(f"**Forecast vs realized daily Δrev:** {res.forecast_delta} → {realized}")
        if res.rolled_back:
            lines.append("**Rolled back:** yes (guardrail breach)")
        lines += ["", "## Pipeline steps"]
        for name, data in steps:
            lines.append(f"- **{name}**: `{json.dumps(data, default=str)[:300]}`")
        lines += ["", "## Tool-call audit trail (every number traces here)"]
        for i, e in enumerate(env.tool_log, 1):
            lines.append(f"{i}. `{e['tool']}` {json.dumps(e.get('args', {}))}")
        if res.notifications:
            lines += ["", "## Notifications"]
            for n in res.notifications:
                lines.append(f"- [{n['type']}] {n['message']}")
        path.write_text("\n".join(lines) + "\n")
        return str(path)


def _print_summary(results):
    print(f"\n{'ID':<5}{'Status':<16}{'Exec':<6}{'Fcast→Real':<16}Notes")
    for r in results:
        fr = (f"{r.forecast_delta}→{r.realized_delta}"
              if r.forecast_delta is not None else "—")
        note = "rolled back" if r.rolled_back else (r.gate_status or "")
        print(f"{r.scenario:<5}{r.status:<16}{str(r.executed):<6}{fr:<16}{note}")
    n_safe = sum(r.safe for r in results)
    n_exec = sum(r.executed for r in results)
    print(f"\n{n_safe}/{len(results)} ended in a safe state; {n_exec} executed. "
          f"S02 action = {next((r.decision.get('action') for r in results if r.scenario=='S02'), 'n/a')}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", help="run one scenario, e.g. S01")
    ap.add_argument("--all", action="store_true", help="run all 10 scenarios")
    ap.add_argument("--mock", action="store_true", help="offline mock brains")
    ap.add_argument("--auto-approve", action="store_true", help="skip the interactive gate")
    ap.add_argument("--inject-fault", choices=["api500", "timeout"], default=None)
    args = ap.parse_args()

    pilot = Autopilot(mock=args.mock, auto_approve=args.auto_approve,
                      inject_fault=args.inject_fault)
    if args.scenario:
        alerts = [next(a for a in all_alerts() if a.scenario_id == args.scenario)]
    else:
        alerts = make_scenario_alerts()
    results = pilot.run_all(alerts)
    _print_summary(results)
    print(f"reports + ledgers in {pilot.out_dir}")


if __name__ == "__main__":
    main()
