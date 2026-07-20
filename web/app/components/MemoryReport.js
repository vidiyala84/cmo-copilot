"use client";
import { useState, Fragment } from "react";
import { LineChart } from "./Charts";
import { ScorePill, Badge } from "./ui";

function decisionStr(d) {
  if (!d) return "—";
  let s = `${d.root_cause} → ${d.action}`;
  if (d.source_campaign) s += ` (${d.source_campaign}→${d.target_campaign} @ ${d.shift_pct}%)`;
  return s;
}

// The per-scenario "how it reached this answer" trace.
export function StepsPanel({ steps, baselineLabel = "Baseline instinct — what the naive rule wanted" }) {
  if (!steps || !steps.final) return <div className="muted" style={{ fontSize: 12 }}>No trace.</div>;
  const sig = steps.signature || "";
  const relevant = (steps.recalled || []).filter(
    (m) => m.kind === "preference" || (m.text || "").startsWith(`[${sig}]`));
  const changed = steps.memory_moves && steps.memory_moves.length > 0;
  const Row = ({ n, title, children, tone }) => (
    <div style={{ display: "flex", gap: 12, padding: "7px 0" }}>
      <div style={{ width: 20, height: 20, borderRadius: "50%", flexShrink: 0, display: "grid",
        placeItems: "center", fontSize: 11, fontWeight: 700,
        border: `2px solid ${tone || "var(--border-2)"}`, color: tone || "var(--muted)" }}>{n}</div>
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 12, fontWeight: 700, textTransform: "uppercase", letterSpacing: .4, color: "var(--muted)" }}>{title}</div>
        <div style={{ fontSize: 13, marginTop: 2, lineHeight: 1.5 }}>{children}</div>
      </div>
    </div>
  );
  return (
    <div style={{ padding: "6px 4px 6px 8px" }}>
      <Row n="1" title="Recall — what it remembered">
        {relevant.length === 0
          ? <span className="muted">No matching preference or past outcome for this situation yet — going in cold.</span>
          : <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              {relevant.slice(0, 5).map((m, i) => (
                <div key={i}>
                  <span className={"badge " + (m.kind === "preference" ? "blue" : "")} style={{ marginRight: 6 }}>{m.kind}</span>
                  <span className="muted" style={{ fontSize: 12.5 }}>{m.text}</span>
                </div>
              ))}
            </div>}
      </Row>
      <Row n="2" title={baselineLabel}>
        <span className="mono">{decisionStr(steps.baseline)}</span>
      </Row>
      <Row n="3" title="Memory adjustment" tone={changed ? "var(--green)" : undefined}>
        {changed
          ? <span style={{ color: "var(--green)" }}>✓ {steps.memory_moves.join("; ")}</span>
          : <span className="muted">none — no relevant memory, so it kept the base decision.</span>}
      </Row>
      <Row n="4" title="Decision" tone="var(--blue)">
        <span className="mono" style={{ fontWeight: 600 }}>{decisionStr(steps.final)}</span>
      </Row>
      <Row n="5" title="Outcome — what it learned for next time">
        <span className="muted">{steps.outcome_written}</span>
      </Row>
    </div>
  );
}

// Full report body shared by the Memory and Memory+Society tabs.
export default function MemoryReport({ rep, scen, baselineLabel }) {
  const [open, setOpen] = useState({ 1: true, 2: true });
  const toggle = (n) => setOpen((o) => ({ ...o, [n]: !o[n] }));
  const [openStep, setOpenStep] = useState({});
  const toggleStep = (k) => setOpenStep((o) => ({ ...o, [k]: !o[k] }));
  const nameOf = (id) => (scen.find((s) => s.id === id) || {}).name || id;
  const isTrap = (id) => (scen.find((s) => s.id === id) || {}).is_trap;
  if (!rep) return null;

  return (
    <>
      <div className="grid c3">
        <div className="card stat tint-blue">
          <div className="label">Session 1</div>
          <div className="value">{rep.curve[0]}</div>
          <div className="sub">the base architecture, before learning</div>
        </div>
        <div className="card stat tint-blue">
          <div className="label">Session {rep.sessions}</div>
          <div className="value" style={{ color: "var(--blue)" }}>{rep.curve[rep.curve.length - 1]}</div>
          <div className={"delta " + (rep.gain >= 0 ? "up" : "down")}>{rep.gain >= 0 ? "+" : ""}{rep.gain} points</div>
        </div>
        <div className="card stat">
          <div className="label">Baseline (no memory)</div>
          <div className="value" style={{ color: "var(--faint)" }}>{rep.baseline_total}</div>
          <div className="sub">flat — the control line</div>
        </div>
      </div>

      <div className="card" style={{ marginTop: 18 }}>
        <div className="spread" style={{ marginBottom: 6 }}>
          <strong>Accuracy across sessions</strong>
          <Badge tone="green">⚡ live</Badge>
        </div>
        <LineChart points={rep.curve} baseline={rep.baseline_total}
                   labels={rep.curve.map((_, i) => `S${i + 1}`)} />
      </div>

      <div className="section-title">Scenario scores across sessions (watch the traps flip)</div>
      <div className="card" style={{ padding: 8, overflowX: "auto" }}>
        <table className="grid-table">
          <thead>
            <tr>
              <th>Scenario</th>
              {rep.per_session.map((s) => <th key={s.session} style={{ textAlign: "center" }}>S{s.session}</th>)}
            </tr>
          </thead>
          <tbody>
            {rep.per_session[0].results.map((r) => (
              <tr key={r.scenario} className={isTrap(r.scenario) ? "trap-row" : ""}>
                <td><span className="mono muted">{r.scenario}</span> {nameOf(r.scenario)}{" "}
                  {isTrap(r.scenario) && <Badge tone="trap">trap</Badge>}</td>
                {rep.per_session.map((s) => {
                  const cell = s.results.find((x) => x.scenario === r.scenario);
                  return <td key={s.session} style={{ textAlign: "center" }}><ScorePill score={cell.score} /></td>;
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="section-title">Output each session — expand any decision to see how it got there</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {rep.per_session.map((s, i) => {
          const prevBy = i > 0
            ? Object.fromEntries(rep.per_session[i - 1].results.map((r) => [r.scenario, r])) : {};
          const changed = s.results.filter((r) => {
            const p = prevBy[r.scenario];
            return p && (p.score !== r.score || p.action !== r.action || p.root_cause !== r.root_cause);
          });
          const isOpen = !!open[s.session];
          return (
            <div className="card" key={s.session}>
              <div className="spread" style={{ cursor: "pointer" }} onClick={() => toggle(s.session)}>
                <div className="row" style={{ gap: 14 }}>
                  <span style={{ fontSize: 18, color: "var(--faint)" }}>{isOpen ? "▾" : "▸"}</span>
                  <strong>Session {s.session}</strong>
                  <ScorePill score={s.total / 10} />
                  <span className="muted" style={{ fontSize: 13 }}>{s.total} / 10</span>
                  {i > 0 && <Badge tone={changed.length ? "green" : undefined}>{changed.length ? `${changed.length} decision(s) changed` : "no change"}</Badge>}
                  {s.corrections_applied > 0 && <Badge tone="blue">+{s.corrections_applied} correction</Badge>}
                </div>
                <span className="muted" style={{ fontSize: 12 }}>
                  ~{s.avg_context_tokens} tok/decision · {s.forgetting.expired_outcomes.length} expired · {s.forgetting.stale_preferences.length} stale
                </span>
              </div>
              {i > 0 && (
                <div className="muted" style={{ fontSize: 12.5, marginTop: 12, lineHeight: 1.55 }}>
                  <strong style={{ color: "var(--text)" }}>In plain English:</strong>{" "}
                  {changed.length
                    ? `it changed ${changed.length} earlier call${changed.length > 1 ? "s" : ""} this session — recalling that those moves backfired before (or a correction), it picked the right answer instead of repeating the mistake.`
                    : "nothing changed — memory just reinforced the decisions that were already working."}
                </div>
              )}
              {isOpen && (
                <table className="grid-table" style={{ marginTop: 14 }}>
                  <thead>
                    <tr>
                      <th style={{ width: 24 }}></th><th>Scenario</th><th>Decision</th>
                      <th style={{ textAlign: "center" }}>Score</th><th>Δ vs previous</th>
                    </tr>
                  </thead>
                  <tbody>
                    {s.results.map((r) => {
                      const p = prevBy[r.scenario];
                      const decisionChanged = p && (p.action !== r.action || p.root_cause !== r.root_cause);
                      const up = p && r.score > p.score;
                      const rowStyle = (decisionChanged || (p && p.score !== r.score)) ? { borderLeft: "2px solid var(--green)" } : undefined;
                      const k = `${s.session}:${r.scenario}`;
                      const openS = !!openStep[k];
                      return (
                        <Fragment key={k}>
                          <tr style={{ ...rowStyle, cursor: "pointer" }} onClick={() => toggleStep(k)}>
                            <td style={{ color: "var(--faint)" }}>{openS ? "▾" : "▸"}</td>
                            <td><span className="mono muted">{r.scenario}</span> {isTrap(r.scenario) && <Badge tone="trap">trap</Badge>}</td>
                            <td className="mono" style={{ fontSize: 12 }}>{r.root_cause} <span className="faint">→</span> {r.action}</td>
                            <td style={{ textAlign: "center" }}><ScorePill score={r.score} /></td>
                            <td style={{ fontSize: 12 }}>
                              {!p ? <span className="faint">baseline</span>
                                : up ? <span style={{ color: "var(--green)" }}>▲ +{(r.score - p.score).toFixed(1)} — {p.action} → {r.action}</span>
                                : p.score !== r.score ? <span style={{ color: "var(--red)" }}>▼ {(r.score - p.score).toFixed(1)}</span>
                                : decisionChanged ? <span className="muted">reworded, same score</span>
                                : <span className="faint">unchanged</span>}
                            </td>
                          </tr>
                          {openS && (
                            <tr><td></td><td colSpan={4} style={{ background: "var(--bg-2)", borderRadius: 8 }}>
                              <StepsPanel steps={r.steps} baselineLabel={baselineLabel} />
                            </td></tr>
                          )}
                        </Fragment>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </div>
          );
        })}
      </div>
    </>
  );
}
