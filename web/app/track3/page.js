"use client";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { Spinner, Button, ScorePill, Badge, ErrorBox } from "../components/ui";

const AV = {
  Analyst: { c: "var(--blue)", role: "diagnosis · qwen-plus",
    plain: "Figures out WHY performance moved (the root cause). Doesn’t touch budget." },
  Forecaster: { c: "var(--violet)", role: "optimizer · qwen-plus",
    plain: "The eager one — always wants to move money to chase more ROAS." },
  Risk: { c: "var(--red)", role: "guardrail · qwen-flash",
    plain: "The guardrail. Can VETO any plan that breaks a rule — and a veto is final." },
};

function AgentCard({ m }) {
  const meta = AV[m.agent] || { c: "var(--muted)", role: "" };
  const claim = m.claim || {};
  return (
    <div className="agent-card">
      <div className="who">
        <div className="av" style={{ background: meta.c }}>{m.agent[0]}</div>
        <div>
          <div style={{ fontWeight: 700, fontSize: 13 }}>{m.agent}</div>
          <div className="role">{meta.role}</div>
        </div>
        <div style={{ marginLeft: "auto" }}>
          {m.veto ? <Badge tone="red">VETO</Badge> : <Badge>{claim.action || "—"}</Badge>}
        </div>
      </div>
      {meta.plain && <div className="muted" style={{ fontSize: 11.5, lineHeight: 1.5, marginBottom: 9 }}>{meta.plain}</div>}
      <div className="claim">
        {claim.root_cause && <><span className="muted">root:</span> <strong>{claim.root_cause}</strong> · </>}
        <span className="muted">action:</span> {claim.action || "—"}
        {claim.source_campaign && <> · {claim.source_campaign}→{claim.target_campaign} @ {claim.shift_pct}%</>}
      </div>
      {m.rationale && <div className="muted" style={{ fontSize: 12, marginTop: 6, lineHeight: 1.5 }}>{m.rationale}</div>}
      {m.veto && <div className="err" style={{ marginTop: 8 }}>veto: {m.veto}</div>}
      <div className="evidence">
        {(m.evidence || []).map((e, i) => <span className="chip" key={i}>{e}</span>)}
      </div>
      <div className="conf-bar"><div style={{ width: `${(m.confidence || 0) * 100}%` }} /></div>
      <div className="faint" style={{ fontSize: 10, marginTop: 3, fontFamily: "var(--mono)" }}>
        confidence {(m.confidence || 0).toFixed(2)}
      </div>
    </div>
  );
}

export default function Track3() {
  const [scen, setScen] = useState([]);
  const [sel, setSel] = useState("S07");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState(null);
  const [liveAvail, setLiveAvail] = useState(false);

  useEffect(() => {
    api.scenarios().then(setScen).catch(setErr);
    api.health().then((h) => setLiveAvail(h.live_available)).catch(() => {});
  }, []);
  useEffect(() => { load(sel, false); }, [sel]);   // shows the cached LIVE debate

  // "live" here = use the cached live transcript (fast); fresh = re-run on real Qwen now
  const load = (sid, fresh) => {
    setLoading(true); setErr(null);
    api.track3(sid, true, fresh).then(setData).catch(setErr).finally(() => setLoading(false));
  };

  const t = data?.transcript;
  const round1 = t?.debate?.[0]?.messages || [];

  return (
    <div>
      <div className="page-head">
        <div className="eyebrow" style={{ color: "var(--amber)" }}>Track 3 · Agent Society</div>
        <h2>The marketing team in a box</h2>
        <p>
          Four specialists argue under a structured protocol — each submits a{" "}
          <span className="mono">claim + evidence + confidence</span>. The Forecaster always wants to
          move money; the Analyst’s diagnosis and the Risk Officer’s <strong>absolute veto</strong> rein
          it in. The Coordinator rules on a coded policy. The transcript is the demo.
        </p>
      </div>

      <ErrorBox error={err} />
      <div className="row" style={{ marginBottom: 16, gap: 12 }}>
        <Button onClick={() => load(sel, true)} loading={loading} disabled={!liveAvail}>
          ⚡ Re-run live on {sel} (fresh Qwen call)
        </Button>
        <span className="muted" style={{ fontSize: 12 }}>
          Showing the <strong>real Qwen debate</strong> captured from the live run. Re-run for a fresh call (~10s).
        </span>
        <Badge tone="green">⚡ live</Badge>
        {t && t.total_tokens ? (
          <span className="muted mono" style={{ fontSize: 12 }}>{t.total_tokens} tok · {t.latency_s}s</span>
        ) : null}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "260px 1fr", gap: 20 }}>
        <div className="card" style={{ padding: 10, alignSelf: "start" }}>
          <div className="scen-list">
            {scen.map((s) => (
              <div key={s.id} className={"scen-item" + (sel === s.id ? " sel" : "")} onClick={() => setSel(s.id)}>
                <span className="id">{s.id}</span>
                <span style={{ flex: 1 }}>{s.name}</span>
                {s.is_trap && <Badge tone="trap">trap</Badge>}
              </div>
            ))}
          </div>
        </div>

        <div>
          {loading && <Spinner label="Running the society debate…" />}
          {t && !loading && (
            <>
              <div className="card" style={{ marginBottom: 18, borderLeft: "3px solid var(--amber)" }}>
                <div className="section-title" style={{ marginTop: 0 }}>The problem</div>
                <div style={{ fontSize: 14, marginBottom: 6 }}>
                  ❓ <em>“Campaign ROAS dropped this week across our 5-campaign account. What’s going on, and where should the budget go?”</em>
                </div>
                <div className="muted" style={{ fontSize: 13 }}>
                  Scenario <span className="mono">{data.scenario}</span> — {data.name}
                  {data.is_trap && <> · <span style={{ color: "var(--amber)" }}>this is a trap: the obvious move is the wrong one</span></>}
                </div>
              </div>

              <div className="card" style={{ marginBottom: 18 }}>
                <div className="spread">
                  <div>
                    <div className="muted" style={{ fontSize: 12 }}>The four agents’ final answer</div>
                    <div style={{ fontSize: 22, fontWeight: 800, marginTop: 4 }}>
                      {t.final_decision.action}{" "}
                      <span className="muted" style={{ fontSize: 14, fontWeight: 500 }}>({t.final_decision.root_cause})</span>
                    </div>
                  </div>
                  <div style={{ textAlign: "right" }}>
                    <div className="muted" style={{ fontSize: 11 }}>harness score</div>
                    <ScorePill score={data.score} />
                  </div>
                </div>
              </div>

              <div className="section-title" style={{ marginTop: 4 }}>How they thought it through · Round 1 — each specialist submits a claim</div>
              <div className="grid c3">
                {round1.map((m, i) => <AgentCard key={i} m={m} />)}
              </div>

              <div className="section-title">Conflicts resolved · {t.rounds} rebuttal round(s)</div>
              {t.conflicts.map((c, i) => (
                <div className="callout" key={i} style={{ marginBottom: 8 }}>⚔ {c}</div>
              ))}

              <div className="section-title">Coordinator ruling</div>
              <div className="callout green">
                <strong>⚖ {t.ruling_reason}</strong>
                <div className="kv" style={{ marginTop: 10 }}>
                  <div className="k">Final action</div><div className="v">{t.final_decision.action}</div>
                  <div className="k">Root cause</div><div className="v">{t.final_decision.root_cause}</div>
                  {t.final_decision.source_campaign && (
                    <>
                      <div className="k">Move</div>
                      <div className="v">{t.final_decision.source_campaign}→{t.final_decision.target_campaign} @ {t.final_decision.shift_pct}%</div>
                    </>
                  )}
                </div>
              </div>

              <div className="section-title">What they decided vs. the correct answer</div>
              <div className="grid c2">
                <div className="card">
                  <div className="muted" style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: .5, marginBottom: 10 }}>The society decided</div>
                  <div className="kv">
                    <div className="k">Root cause</div><div className="v">{t.final_decision.root_cause}</div>
                    <div className="k">Action</div><div className="v">{t.final_decision.action}</div>
                    {t.final_decision.source_campaign && <>
                      <div className="k">Move</div><div className="v">{t.final_decision.source_campaign}→{t.final_decision.target_campaign} @ {t.final_decision.shift_pct}%</div>
                    </>}
                  </div>
                </div>
                <div className="card">
                  <div className="muted" style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: .5, marginBottom: 10 }}>The correct answer</div>
                  <div className="kv">
                    <div className="k">Root cause</div><div className="v">{data.expected?.root_cause}</div>
                    <div className="k">Action</div><div className="v">{data.expected?.action}</div>
                    {data.expected?.acceptable_targets?.length > 0 && <>
                      <div className="k">OK targets</div><div className="v">{data.expected.acceptable_targets.join(" / ")}</div>
                    </>}
                    {data.expected?.forbidden_sources?.length > 0 && <>
                      <div className="k">Never touch</div><div className="v" style={{ color: "var(--amber)" }}>{data.expected.forbidden_sources.join(" / ")}</div>
                    </>}
                  </div>
                </div>
              </div>
              <div className={"callout " + (data.score >= 0.8 ? "green" : "")} style={{ marginTop: 12 }}>
                <strong>{data.score >= 0.8 ? "✓ matched" : data.score >= 0.4 ? "◑ partly right" : "✗ wrong"}</strong>
                {" "}(score {data.score}). {data.is_trap
                  ? "This is a trap — a single naive agent would move budget the wrong way here; the debate + veto is what catches it."
                  : "The specialists agreed on the sound move."}
              </div>

              <div className="section-title">Tool-call audit trail (every number the agents cited came from one of these)</div>
              <div className="card">
                <div className="row">
                  {data.tool_log.map((e, i) => (
                    <span className="chip" key={i}>{e.tool}{e.args && Object.keys(e.args).length ? " " + JSON.stringify(e.args) : ""}</span>
                  ))}
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
