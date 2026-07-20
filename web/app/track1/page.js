"use client";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { Spinner, Button, Badge, ErrorBox } from "../components/ui";
import MemoryReport from "../components/MemoryReport";

export default function Track1() {
  const [rep, setRep] = useState(null);
  const [scen, setScen] = useState([]);
  const [sessions, setSessions] = useState(5);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState(null);
  const [liveAvail, setLiveAvail] = useState(false);

  useEffect(() => {
    api.scenarios().then(setScen).catch(setErr);
    api.health().then((h) => setLiveAvail(h.live_available)).catch(() => {});
    setLoading(true);
    api.liveMemory().then((r) => { if (r && r.ready) setRep(r); }).catch(setErr).finally(() => setLoading(false));
  }, []);

  const run = (n) => {
    setLoading(true); setErr(null);
    api.track1(n, true).then(setRep).catch(setErr).finally(() => setLoading(false));
  };

  return (
    <div>
      <div className="page-head">
        <div className="eyebrow" style={{ color: "var(--blue)" }}>Track 1 · MemoryAgent</div>
        <h2>CMO Copilot remembers</h2>
        <p>
          The same agent, five sessions in a row, persisting memory between runs. Session 1 is a
          cold start; after it the user corrects it (“never move budget out of brand”), and from then on
          it learns from the <strong>outcomes of its own past decisions</strong> — with a forgetting
          policy so old lessons decay and contradictions get demoted. Here the base agent is a single
          live Qwen — see the <strong>Mem + Society</strong> tab for the same memory on top of the society.
        </p>
      </div>

      <div className="row" style={{ marginBottom: 8 }}>
        <Badge tone="green">⚡ live (cached 5-session run)</Badge>
        <div className="seg">
          {[3, 5, 7].map((n) => (
            <button key={n} className={sessions === n ? "on" : ""} onClick={() => setSessions(n)}>{n} sessions</button>
          ))}
        </div>
        <Button onClick={() => run(sessions)} loading={loading} disabled={!liveAvail}>▶ Re-run live ({sessions}×10 Qwen calls)</Button>
      </div>
      <div className="callout" style={{ marginBottom: 22 }}>
        These are <strong>real Qwen</strong> results. Unlike the deterministic offline mechanism (a clean climb to 9.8),
        a lone live model doesn’t reliably act on the memories it recalls — so this curve is noisy and only improves a little.
        (Memory bolted onto the <strong>society</strong> is a different story — see that tab.)
      </div>

      <ErrorBox error={err} />
      {loading && !rep && <Spinner label="Loading live 5-session run…" />}

      {rep && <MemoryReport rep={rep} scen={scen} baselineLabel="Baseline instinct — what the naive rule wanted" />}

      {rep && (
        <>
          <div className="section-title">How the score works</div>
          <div className="card">
            <div className="row" style={{ gap: 18, marginBottom: 12 }}>
              <div><span className="score-pill" style={{ background: "var(--blue-dim)", color: "#9dc2ff" }}>0.4</span> <span className="muted">root cause correct</span></div>
              <div><span className="score-pill" style={{ background: "var(--blue-dim)", color: "#9dc2ff" }}>0.4</span> <span className="muted">action correct</span></div>
              <div><span className="score-pill" style={{ background: "var(--blue-dim)", color: "#9dc2ff" }}>0.2</span> <span className="muted">sourcing (right source/target, protected campaigns untouched)</span></div>
            </div>
            <div className="muted" style={{ fontSize: 13, lineHeight: 1.6 }}>
              Each scenario is graded 0–1 against a known correct answer, so 10 scenarios = <strong>10.0 max</strong>.
              The “total” per session is the sum of those 10 — a decision-accuracy score, not a model confidence.
            </div>
          </div>
        </>
      )}
    </div>
  );
}
