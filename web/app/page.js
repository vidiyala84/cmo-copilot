"use client";
import { useEffect, useState } from "react";
import { api } from "./lib/api";
import { BarChart, LineChart } from "./components/Charts";
import { Spinner, Button, ScorePill, Badge, ErrorBox } from "./components/ui";

const APPROACHES = [
  { key: "direct", label: "Direct Qwen", tag: "layman",
    plain: "Paste the dashboard into Qwen and ask “what should I do?” — no tools, no validation, no memory. What most business owners actually do.", color: "var(--faint)" },
  { key: "direct_rules", label: "Direct + rules", tag: "told the rules",
    plain: "Direct Qwen, but handed every business rule and diagnostic tell right in the prompt. No tools, no structure — just told the rules.", color: "#6b7280" },
  { key: "baseline", label: "Baseline", tag: "1 agent + tools",
    plain: "One Qwen agent that CAN call the tools (pull metrics, forecast, validate against business rules) before answering.", color: "var(--blue-dim)" },
  { key: "society", label: "Society", tag: "4 agents",
    plain: "Four specialists debate — Analyst diagnoses, Forecaster proposes, Risk vetoes rule-breaking plans, Coordinator rules.", color: "var(--amber)" },
  { key: "memory", label: "Memory (S5)", tag: "learns",
    plain: "The same agent after 5 sessions of remembering what worked and what backfired.", color: "var(--blue)" },
  { key: "memsoc", label: "Memory + Society", tag: "combined",
    plain: "The composed system: the 4-agent society decides, memory enforces recalled rules and corrects situations that backfired before.", color: "var(--violet)" },
];

function totalOf(b, key) {
  if (key === "memory") return b.memory?.curve?.[b.memory.curve.length - 1];
  if (key === "memsoc") return b.memsoc?.curve?.[b.memsoc.curve.length - 1];
  return b[key]?.total;
}

export default function Overview() {
  const [b, setB] = useState(null);
  const [scen, setScen] = useState([]);
  const [err, setErr] = useState(null);
  const [loading, setLoading] = useState(true);
  const [sc, setSc] = useState("S07");
  const [approach, setApproach] = useState("direct");
  const [runResult, setRunResult] = useState(null);
  const [running, setRunning] = useState(false);

  useEffect(() => {
    Promise.all([api.liveBenchmark(), api.scenarios()])
      .then(([bench, s]) => { setB(bench); setScen(s); })
      .catch(setErr).finally(() => setLoading(false));
  }, []);

  const runLive = () => {
    setRunning(true); setErr(null); setRunResult(null);
    api.liveRun(sc, approach).then(setRunResult).catch(setErr).finally(() => setRunning(false));
  };

  const nameOf = (id) => (scen.find((s) => s.id === id) || {}).name || id;
  const isTrap = (id) => (scen.find((s) => s.id === id) || {}).is_trap;

  return (
    <div>
      <div className="page-head">
        <div className="eyebrow">Live Benchmark · real Qwen on Qwen Cloud</div>
        <h2>Does the architecture actually matter?</h2>
        <p>
          Four ways to answer the same question — “ROAS dropped, where should the budget go?” — all
          running on <strong>real Qwen</strong>, scored on the identical 10-scenario harness. The control
          is <strong>Direct Qwen</strong>: what you get just asking the model, like a business owner would.
          Everything to its right adds architecture (tools, a specialist society, memory).
        </p>
      </div>

      <div className="card" style={{ marginBottom: 24, borderLeft: "3px solid var(--green)" }}>
        <div className="section-title" style={{ marginTop: 0 }}>▶ Try it live — pick a scenario, run real Qwen now</div>
        <div className="row" style={{ gap: 18, alignItems: "flex-end" }}>
          <div>
            <div className="muted" style={{ fontSize: 11, marginBottom: 6, textTransform: "uppercase", letterSpacing: .5 }}>Scenario</div>
            <select className="seg" style={{ padding: 8 }} value={sc} onChange={(e) => setSc(e.target.value)}>
              {scen.map((s) => <option key={s.id} value={s.id}>{s.id} · {s.name}{s.is_trap ? " (trap)" : ""}</option>)}
            </select>
          </div>
          <div>
            <div className="muted" style={{ fontSize: 11, marginBottom: 6, textTransform: "uppercase", letterSpacing: .5 }}>Approach</div>
            <div className="seg">
              {[["direct", "Direct Qwen"], ["direct_rules", "Direct + rules"], ["baseline", "Baseline + tools"], ["society", "Society"]].map(([k, l]) => (
                <button key={k} className={approach === k ? "on" : ""} onClick={() => setApproach(k)}>{l}</button>
              ))}
            </div>
          </div>
          <div style={{ marginLeft: "auto" }}>
            <Button onClick={runLive} loading={running}>⚡ Run live</Button>
          </div>
        </div>
        {running && <Spinner label={`Calling real Qwen on Qwen Cloud (${approach})…`} />}
        {runResult && !running && (
          <div style={{ marginTop: 18 }}>
            <div className="grid c2">
              <div className="card">
                <div className="muted" style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: .5, marginBottom: 10 }}>
                  What {runResult.approach === "direct" ? "Direct Qwen" : runResult.approach} decided (live)
                </div>
                <div className="kv">
                  <div className="k">Root cause</div><div className="v">{runResult.decision.root_cause}</div>
                  <div className="k">Action</div><div className="v">{runResult.decision.action}</div>
                  {runResult.decision.source_campaign && <>
                    <div className="k">Move</div><div className="v">{runResult.decision.source_campaign}→{runResult.decision.target_campaign} @ {runResult.decision.shift_pct}%</div>
                  </>}
                </div>
              </div>
              <div className="card">
                <div className="muted" style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: .5, marginBottom: 10 }}>The correct answer</div>
                <div className="kv">
                  <div className="k">Root cause</div><div className="v">{runResult.expected.root_cause}</div>
                  <div className="k">Action</div><div className="v">{runResult.expected.action}</div>
                  {runResult.expected.forbidden_sources?.length > 0 && <>
                    <div className="k">Never touch</div><div className="v" style={{ color: "var(--amber)" }}>{runResult.expected.forbidden_sources.join(" / ")}</div>
                  </>}
                </div>
              </div>
            </div>
            <div className={"callout " + (runResult.score >= 0.8 ? "green" : "")} style={{ marginTop: 12 }}>
              <strong>{runResult.score >= 0.8 ? "✓ correct" : runResult.score >= 0.4 ? "◑ partly right" : "✗ wrong"}</strong> (score {runResult.score})
              {" · "}<span className="mono">{runResult.tokens} tokens · {runResult.latency_s}s</span>
              {runResult.tool_log.length > 0 && <> · called {runResult.tool_log.length} tools</>}
              {runResult.decision.rationale && (
                <div className="muted" style={{ fontSize: 12.5, marginTop: 8, lineHeight: 1.5 }}>
                  <strong>Its reasoning:</strong> {runResult.decision.rationale}
                </div>
              )}
              {runResult.approach === "society" && runResult.transcript && (
                <div className="muted" style={{ fontSize: 12.5, marginTop: 6 }}>
                  <strong>Debate:</strong> {runResult.transcript.conflicts?.join(" · ")}
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      <ErrorBox error={err} />
      {loading && <Spinner label="Loading live benchmark…" />}

      {b && !b.ready && (
        <div className="callout">
          The live benchmark hasn’t been computed yet. Run <span className="mono">python scratchpad/bench_live.py</span> (real Qwen calls) to populate it.
        </div>
      )}

      {b && b.ready && (() => {
        const shown = APPROACHES.filter((a) => totalOf(b, a.key) != null);
        return (
        <>
          <div className="grid" style={{ gridTemplateColumns: `repeat(${shown.length}, 1fr)` }}>
            {shown.map((a) => (
              <div className="card stat" key={a.key} style={{ borderTop: `2px solid ${a.color}` }}>
                <div className="label">{a.label} <span className="faint" style={{ textTransform: "none" }}>· {a.tag}</span></div>
                <div className="value" style={{ color: a.color === "var(--faint)" ? "var(--faint)" : a.color }}>
                  {totalOf(b, a.key)}<span className="muted" style={{ fontSize: 16 }}>/10</span>
                </div>
                <div className="sub" style={{ minHeight: 62, fontSize: 11.5 }}>{a.plain}</div>
              </div>
            ))}
          </div>

          <div className="grid c2" style={{ marginTop: 18 }}>
            <div className="card">
              <div className="spread" style={{ marginBottom: 6 }}>
                <strong>Harness total — the more architecture, the better</strong>
                <Badge tone="green">⚡ live</Badge>
              </div>
              <BarChart data={shown.map((a) => ({ label: a.label.replace(" (S5)", "").replace("Memory + Society", "Mem+Soc"), value: totalOf(b, a.key), color: a.color }))} />
            </div>
            <div className="card">
              <div className="spread" style={{ marginBottom: 6 }}>
                <strong>Memory across 5 live sessions</strong>
                <Badge tone="blue">Track 1 · live</Badge>
              </div>
              <LineChart points={b.memory.curve} baseline={b.memory.baseline}
                         labels={b.memory.curve.map((_, i) => `S${i + 1}`)} />
              <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
                Live curve is noisy (+{b.memory.gain}) — the memory <em>mechanism</em> is proven in the offline test, but a real model doesn’t always act on what it recalls.
              </div>
            </div>
          </div>

          {(() => {
            const trapTotal = (rows) => rows ? rows.filter((r) => r.is_trap).reduce((a, r) => a + r.score, 0) : null;
            const trapRows = [
              ["Direct Qwen", trapTotal(b.direct.rows), "var(--faint)"],
              ["Direct + rules", trapTotal(b.direct_rules?.rows), "#9ca3af"],
              ["Baseline + tools", trapTotal(b.baseline.rows), "var(--blue)"],
              ["Society", trapTotal(b.society.rows), "var(--amber)"],
            ].filter(([, v]) => v != null);
            return (
              <>
                <div className="section-title">⚠ The 4 traps — where the “obvious” move is wrong</div>
                <div className="callout" style={{ marginBottom: 14 }}>
                  <strong>Trap scenarios are the whole test.</strong> On the easy scenarios almost everyone scores well;
                  the gap between “ask an LLM” and “engineer around it” lives entirely in these four —
                  <span className="mono"> S02</span> tracking bug (don’t move budget),
                  <span className="mono"> S07</span> brand floor (don’t cut brand),
                  <span className="mono"> S08</span> learning phase (be patient),
                  <span className="mono"> S09</span> budget cap (increase, don’t shift).
                </div>
                <div className="grid" style={{ gridTemplateColumns: `repeat(${trapRows.length}, 1fr)`, marginBottom: 18 }}>
                  {trapRows.map(([label, val, color]) => (
                    <div className="card stat" key={label} style={{ borderTop: `2px solid ${color}` }}>
                      <div className="label" style={{ fontSize: 11 }}>{label}</div>
                      <div className="value" style={{ fontSize: 30, color }}>{val.toFixed(1)}<span className="muted" style={{ fontSize: 14 }}>/4</span></div>
                      <div className="sub">on the 4 traps</div>
                    </div>
                  ))}
                </div>
              </>
            );
          })()}

          <div className="spread" style={{ margin: "8px 2px" }}>
            <div className="section-title" style={{ margin: 0 }}>Per scenario — every architecture, side by side</div>
            <span className="trap-legend"><span className="swatch" /> ⚠ trap: the intuitive answer is the wrong one</span>
          </div>
          <div className="card" style={{ padding: 8, overflowX: "auto" }}>
            <table className="grid-table">
              <thead>
                <tr>
                  <th>ID</th><th>Scenario</th>
                  <th style={{ textAlign: "center" }}>Direct</th>
                  {b.direct_rules && <th style={{ textAlign: "center" }}>+Rules</th>}
                  <th style={{ textAlign: "center" }}>Baseline</th>
                  <th style={{ textAlign: "center" }}>Society</th>
                </tr>
              </thead>
              <tbody>
                {scen.map((s) => {
                  const dir = b.direct.rows.find((r) => r.scenario === s.id) || {};
                  const dr = b.direct_rules?.rows.find((r) => r.scenario === s.id) || {};
                  const bl = b.baseline.rows.find((r) => r.scenario === s.id) || {};
                  const soc = b.society.rows.find((r) => r.scenario === s.id) || {};
                  return (
                    <tr key={s.id} className={s.is_trap ? "trap-row" : ""}>
                      <td className="mono muted">{s.id}</td>
                      <td>{s.name} {s.is_trap && <Badge tone="trap">trap</Badge>}</td>
                      <td style={{ textAlign: "center" }}><ScorePill score={dir.score} /></td>
                      {b.direct_rules && <td style={{ textAlign: "center" }}><ScorePill score={dr.score} /></td>}
                      <td style={{ textAlign: "center" }}><ScorePill score={bl.score} /></td>
                      <td style={{ textAlign: "center" }}><ScorePill score={soc.score} /></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <div className="section-title">What this actually shows</div>
          <div className="grid c2">
            <div className="callout">
              <strong>Direct Qwen ({b.direct.total}/10) is the layman control.</strong> With no tools it can’t
              check the brand-spend floor, can’t tell a tracking bug from a real drop, and can’t forecast — so it
              confidently moves budget on the trap scenarios (S02, S07, S08, S09) where the right answer is “don’t.”
              A smart model is not enough on its own.
            </div>
            <div className="callout green">
              {b.baseline.total > b.direct.total + 0.3
                ? <><strong>Giving one agent tools helped ({b.direct.total}→{b.baseline.total}), and the 4-agent society more so ({b.society.total}/10).</strong> The society’s Risk veto is what makes the constraint traps hard to get wrong.</>
                : <><strong>Surprise: tools alone barely moved a single agent ({b.direct.total} vs {b.baseline.total}).</strong> It still mislabels root causes. What actually moved the needle was <strong>structure</strong> — the 4-agent society ({b.society.total}/10), where a dedicated Risk officer can veto rule-breaking plans. On a real model, how you <em>organize</em> the agents matters more than just handing one agent tools.</>}
            </div>
          </div>

          {b.direct_rules && (
            <div className="callout" style={{ marginTop: 12, borderLeftColor: "#6b7280" }}>
              <strong>“Why not just tell Qwen the rules?” We did — it only reached {b.direct_rules.total}/10.</strong>{" "}
              We handed the model every business rule and diagnostic tell in the prompt (no tools, no structure). It went
              from {b.direct.total} → {b.direct_rules.total} — barely, and still below the society ({b.society.total}). Told the exact
              tracking rule, it <em>still</em> moved budget on the tracking trap; and it started over-applying the seasonality
              rule to cases it didn’t fit. <strong>Stating a rule isn’t enforcing it</strong> — the society’s Risk officer
              enforces constraints deterministically, which is why structure beats a well-briefed prompt.
            </div>
          )}
          {b.memsoc && (
            <div className="callout blue" style={{ marginTop: 12 }}>
              <strong>Memory + Society ({totalOf(b, "memsoc")}/10) is the composed system.</strong> The society
              still does the hard diagnosis, but now memory <em>enforces</em> the rules it has learned and corrects
              the exact situations that backfired in earlier sessions — so it tops out above the society alone
              ({b.society.total}/10). Session curve: {b.memsoc.curve.join(" → ")}. Memory works far better bolted onto
              structure (where recalled rules become vetoes) than on a lone LLM (where they’re just suggestions it may ignore).
            </div>
          )}
          <div className="faint" style={{ fontSize: 11, marginTop: 16 }}>
            All figures are live Qwen on Qwen Cloud (Model Studio), captured from real runs. Model: qwen-plus / qwen-max. No mock data on this page.
          </div>
        </>
        );
      })()}
    </div>
  );
}
