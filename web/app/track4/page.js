"use client";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { Spinner, Button, ScorePill, Badge, ErrorBox } from "../components/ui";

const ICON = {
  triage: "🔍", diagnose: "🩺", propose: "📋", gate: "🔑", execute: "⚙",
  execute_failed: "✖", monitor: "📈", rollback: "↩",
};
const STATUS_TONE = {
  completed: "green", rolled_back: "amber", held: "blue", ignored: "blue",
  not_approved: "amber", expired: "amber", failed_safe: "red",
};

// Plain-English "what is happening and why" for each pipeline step.
const PLAIN = {
  triage: "First, a cheap gut-check: is this dip actually big enough to act on? Trivial wobbles are ignored, so the agent never chases noise.",
  diagnose: "Before touching any budget, work out WHY performance moved — creative fatigue? a tracking bug? seasonality? The right fix depends entirely on the cause.",
  propose: "Draft a specific budget move and check it against the business rules (brand-spend floor, max 20%/week, campaigns still in their learning phase) before a human ever sees it.",
  gate: "A human decides: approve, adjust the amount, or reject with a reason. This is the ONLY human touchpoint — and nothing executes without a recorded approval.",
  execute: "The approved move is applied in the sandbox ad platform and stamped with a manifest id, so every change can be traced and reversed.",
  execute_failed: "The ad platform errored mid-change. The agent retried twice, then backed all the way out — it never leaves budget half-moved.",
  monitor: "Fast-forward ~14 simulated days and compare what actually happened against what was forecast.",
  rollback: "Real results came in below the safety guardrail (under 70% of forecast), so the move was automatically reversed and a human was notified.",
};

const STATUS_PLAIN = {
  completed: "The move was approved, executed, and held up against its forecast — done.",
  rolled_back: "Executed, but results disappointed, so the agent undid it automatically. No harm done.",
  held: "The diagnosis said don't move money (e.g. it's a tracking bug or just seasonality), so nothing was executed.",
  ignored: "The alert was too trivial to be worth investigating — logged and dropped.",
  not_approved: "A human rejected the plan, so nothing executed.",
  expired: "Nobody answered the approval request in time, so the plan expired and nothing executed.",
  failed_safe: "Something broke mid-execution; the agent aborted cleanly and left the account untouched.",
};

function summarize(step, data) {
  try {
    if (step === "triage") return `${data.severity} · ${data.reason}`;
    if (step === "diagnose") return `${data.root_cause} → ${data.action}`;
    if (step === "propose") return `valid=${data.valid} · replans=${data.replans} · shift ${data.plan?.shift_pct}%`;
    if (step === "gate") return `${data.status} by ${data.approver}${data.reason ? " · " + data.reason : ""}`;
    if (step === "execute") return `manifest ${data.manifest_id} (attempts: ${data.attempts})`;
    if (step === "execute_failed") return `${data.cause} after ${data.attempts} attempts → failed_safe`;
    if (step === "monitor") return `forecast ${data.forecast_delta} → realized ${data.realized_delta} (${Math.round((data.realized_vs_forecast || 0) * 100)}% of forecast)${data.breached ? " · GUARDRAIL BREACHED" : " · within guardrail"}`;
    if (step === "rollback") return `reversed via ${data.manifest_id}`;
    return JSON.stringify(data).slice(0, 140);
  } catch { return ""; }
}
function stepClass(step, data) {
  if (step === "execute_failed") return "fail";
  if (step === "rollback") return "warn";
  if (step === "monitor" && data?.breached) return "warn";
  if (step === "gate" && !["approved", "adjusted"].includes(data?.status)) return "warn";
  return "done";
}

export default function Track4() {
  const [scen, setScen] = useState([]);
  const [sid, setSid] = useState("S01");
  const [fault, setFault] = useState(null);
  const [gate, setGate] = useState("auto");
  const [res, setRes] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState(null);
  const [live, setLive] = useState(false);
  const [liveAvail, setLiveAvail] = useState(false);

  useEffect(() => {
    api.scenarios().then(setScen).catch(setErr);
    api.health().then((h) => { setLiveAvail(h.live_available); setLive(h.live_available); }).catch(() => {});
  }, []);

  const run = () => {
    setLoading(true); setErr(null); setRes(null);
    api.track4({ scenario: sid, fault, gate, live }).then(setRes).catch(setErr).finally(() => setLoading(false));
  };

  return (
    <div>
      <div className="page-head">
        <div className="eyebrow" style={{ color: "var(--green)" }}>Track 4 · Autopilot</div>
        <h2>From alert to executed reallocation</h2>
        <p>
          Nobody asked the agent anything. An alert fires and the pipeline carries it — triage →
          diagnose → propose → <strong>human gate</strong> → sandbox execute → monitor → guardrail
          rollback — pausing only at the gate. Every terminal state is safe; inject a fault and watch
          it fail <span className="mono">failed_safe</span>.
        </p>
      </div>

      <div className="card" style={{ marginBottom: 20 }}>
        <div className="row" style={{ gap: 22 }}>
          <div>
            <div className="muted" style={{ fontSize: 11, marginBottom: 6, textTransform: "uppercase", letterSpacing: .5 }}>Scenario</div>
            <select className="seg" style={{ padding: 8 }} value={sid} onChange={(e) => setSid(e.target.value)}>
              {scen.map((s) => <option key={s.id} value={s.id}>{s.id} · {s.name}</option>)}
            </select>
          </div>
          <div>
            <div className="muted" style={{ fontSize: 11, marginBottom: 6, textTransform: "uppercase", letterSpacing: .5 }}>Inject fault</div>
            <div className="seg">
              {[["none", null], ["api500", "api500"], ["timeout", "timeout"]].map(([l, v]) => (
                <button key={l} className={fault === v ? "on" : ""} onClick={() => setFault(v)}>{l}</button>
              ))}
            </div>
          </div>
          <div>
            <div className="muted" style={{ fontSize: 11, marginBottom: 6, textTransform: "uppercase", letterSpacing: .5 }}>Human gate</div>
            <div className="seg">
              {["auto", "approve", "adjust", "reject", "expire"].map((g) => (
                <button key={g} className={gate === g ? "on" : ""} onClick={() => setGate(g)}>{g}</button>
              ))}
            </div>
          </div>
          <div>
            <div className="muted" style={{ fontSize: 11, marginBottom: 6, textTransform: "uppercase", letterSpacing: .5 }}>Diagnosis brain</div>
            <div className="seg">
              <button className={!live ? "on" : ""} onClick={() => setLive(false)}>mock</button>
              <button className={live ? "on" : ""} onClick={() => liveAvail && setLive(true)}
                      disabled={!liveAvail} title={liveAvail ? "" : "add DASHSCOPE_API_KEY to .env"}>⚡ live</button>
            </div>
          </div>
          <div style={{ marginLeft: "auto", alignSelf: "flex-end" }}>
            <Button onClick={run} loading={loading}>▶ Run pipeline</Button>
          </div>
        </div>
      </div>

      <ErrorBox error={err} />
      {loading && <Spinner label="Driving the autopilot pipeline…" />}

      {res && (
      <>
        <div className="card" style={{ marginBottom: 20, borderLeft: "3px solid var(--green)" }}>
          <div className="section-title" style={{ marginTop: 0 }}>1 · The problem (what set this off)</div>
          <div style={{ fontSize: 15, marginBottom: 8 }}>
            🔔 <em>“{res.alert}”</em>
          </div>
          <div className="muted" style={{ fontSize: 13, lineHeight: 1.55 }}>
            The alert is deliberately vague — it just says performance is off. Nobody told the agent
            what’s wrong or what to do. Behind the scenes this is scenario <span className="mono">{res.scenario}</span> ({res.scenario_name}),
            but the agent has to <strong>figure that out from the data</strong> and decide whether to act at all.
          </div>
        </div>

        <div className="section-title">2 · How it worked through it, step by step</div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 320px", gap: 20 }}>
          <div className="card">
            <div className="spread" style={{ marginBottom: 18 }}>
              <strong>Pipeline</strong>
              <Badge tone={STATUS_TONE[res.status] || "blue"}>{res.status}</Badge>
            </div>
            <div className="stepper">
              {res.steps.map((s, i) => {
                const cls = stepClass(s.step, s.data);
                return (
                  <div className={"step " + cls} key={i}>
                    <div className="rail">
                      <div className="node">{ICON[s.step] || "•"}</div>
                      {i < res.steps.length - 1 && <div className="line" />}
                    </div>
                    <div className="body">
                      <div className="t">{s.step.replace("_", " ")}</div>
                      {PLAIN[s.step] && (
                        <div style={{ color: "var(--muted)", fontSize: 13, lineHeight: 1.5, margin: "3px 0 5px" }}>
                          {PLAIN[s.step]}
                        </div>
                      )}
                      <div className="d">{summarize(s.step, s.data)}</div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <div>
            <div className="card" style={{ marginBottom: 16 }}>
              <div className="section-title" style={{ marginTop: 0 }}>Outcome</div>
              <div className="kv">
                <div className="k">Status</div><div className="v"><Badge tone={STATUS_TONE[res.status] || "blue"}>{res.status}</Badge></div>
                {res.mode && <>
                  <div className="k">Brain</div>
                  <div className="v">
                    <Badge tone={res.mode === "live" ? "green" : undefined}>{res.mode}</Badge>
                    {res.diagnosis_tokens ? <span className="muted mono" style={{ fontSize: 11, marginLeft: 6 }}>{res.diagnosis_tokens} tok · {res.diagnosis_latency_s}s</span> : null}
                  </div>
                </>}
                <div className="k">Safe exit</div><div className="v">{res.safe ? "✓ yes" : "✗ no"}</div>
                <div className="k">Executed</div><div className="v">{String(res.executed)}</div>
                {res.manifest_id && <><div className="k">Manifest</div><div className="v" style={{ fontSize: 11 }}>{res.manifest_id}</div></>}
                {res.forecast_delta != null && <><div className="k">Forecast Δ</div><div className="v">{res.forecast_delta}</div></>}
                {res.realized_delta != null && <><div className="k">Realized Δ</div><div className="v">{res.realized_delta}</div></>}
                {res.rolled_back && <><div className="k">Rolled back</div><div className="v" style={{ color: "var(--amber)" }}>yes</div></>}
                {res.fault_mode && <><div className="k">Fault</div><div className="v" style={{ color: "var(--red)" }}>{res.fault_mode}</div></>}
                <div className="k">Score</div><div className="v"><ScorePill score={res.score} /></div>
              </div>
            </div>

            {res.notifications?.length > 0 && (
              <div className="card" style={{ marginBottom: 16 }}>
                <div className="section-title" style={{ marginTop: 0 }}>Notifications</div>
                {res.notifications.map((n, i) => (
                  <div className={"callout" + (n.type.includes("fail") || n.type.includes("rollback") ? "" : " blue")}
                       key={i} style={{ marginBottom: 8, fontSize: 12 }}>
                    <strong>[{n.type}]</strong> {n.message}
                  </div>
                ))}
              </div>
            )}

            <div className="card">
              <div className="section-title" style={{ marginTop: 0 }}>Tool-call audit</div>
              <div className="row">
                {res.tool_log.map((e, i) => <span className="chip" key={i}>{e.tool}</span>)}
              </div>
              <div className="faint" style={{ fontSize: 11, marginTop: 10 }}>
                Every number in the run traces to one of these calls. Zero executions without an approval record.
              </div>
            </div>
          </div>
        </div>

        <div className="section-title">3 · What it decided vs. the correct answer</div>
        <div className="grid c2">
          <div className="card">
            <div className="muted" style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: .5, marginBottom: 10 }}>
              What the agent did
            </div>
            <div className="kv">
              <div className="k">Root cause</div><div className="v">{res.decision?.root_cause || "—"}</div>
              <div className="k">Action</div><div className="v">{res.decision?.action || "—"}</div>
              {res.decision?.source_campaign && <>
                <div className="k">Move</div>
                <div className="v">{res.decision.source_campaign}→{res.decision.target_campaign} @ {res.decision.shift_pct}%</div>
              </>}
              <div className="k">Executed?</div><div className="v">{res.executed ? "yes" : "no"}</div>
            </div>
          </div>
          <div className="card">
            <div className="muted" style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: .5, marginBottom: 10 }}>
              The correct answer
            </div>
            <div className="kv">
              <div className="k">Root cause</div><div className="v">{res.expected?.root_cause}</div>
              <div className="k">Action</div><div className="v">{res.expected?.action}</div>
              {res.expected?.acceptable_targets?.length > 0 && <>
                <div className="k">OK targets</div><div className="v">{res.expected.acceptable_targets.join(" / ")}</div>
              </>}
              {res.expected?.forbidden_sources?.length > 0 && <>
                <div className="k">Never touch</div><div className="v" style={{ color: "var(--amber)" }}>{res.expected.forbidden_sources.join(" / ")}</div>
              </>}
            </div>
          </div>
        </div>
        <div className={"callout " + (res.score >= 0.8 ? "green" : "")} style={{ marginTop: 12 }}>
          <strong>Verdict:</strong> {res.score >= 0.8 ? "✓ matched the correct answer" : res.score >= 0.4 ? "◑ partly right" : "✗ got it wrong"}
          {" "}(score {res.score}). {STATUS_PLAIN[res.status]}
          {res.decision?.rationale && (
            <div className="muted" style={{ fontSize: 12, marginTop: 8, lineHeight: 1.5 }}>
              <strong>Its reasoning:</strong> {res.decision.rationale}
            </div>
          )}
        </div>
      </>
      )}
    </div>
  );
}
