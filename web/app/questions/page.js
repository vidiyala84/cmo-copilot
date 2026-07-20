"use client";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { BarChart } from "../components/Charts";
import { Spinner, ScorePill, Badge, ErrorBox } from "../components/ui";

const APPS = [
  { key: "direct", label: "Direct Qwen", color: "var(--faint)" },
  { key: "direct_rules", label: "Direct + rules", color: "#9ca3af" },
  { key: "memory", label: "Memory (lone)", color: "var(--blue)" },
  { key: "society", label: "Society", color: "var(--amber)" },
  { key: "memsoc", label: "Mem + Society", color: "var(--violet)" },
];

export default function Questions() {
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    const poll = () => api.questions().then((r) => {
      if (r.ready) { setD(r); setLoading(false); }
      else setTimeout(poll, 8000);   // still computing — poll
    }).catch((e) => { setErr(e); setLoading(false); });
    poll();
  }, []);

  const shown = d ? APPS.filter((a) => d.approaches[a.key]) : [];

  return (
    <div>
      <div className="page-head">
        <div className="eyebrow" style={{ color: "var(--violet)" }}>5 questions · robustness</div>
        <h2>Not just “where should budget go?”</h2>
        <p>
          One question is a noisy benchmark. Here the <strong>same account dynamics</strong> are posed as five
          genuinely different CMO questions — <strong>reallocation, scale-up, efficiency audit, health check,</strong> and a
          <strong> patience test</strong> — where the <em>same</em> situation often has a <em>different</em> right answer
          (a winning campaign is a shift-target in Q1, a scale-up pick in Q2, and something you must not cut in Q5).
          Averaging across all five is a far more honest score.
        </p>
      </div>

      <ErrorBox error={err} />
      {loading && <Spinner label="Running the 5-question benchmark on live Qwen (~25 min)… this polls automatically." />}
      {d && !d.ready && !loading && <div className="callout">Not computed yet.</div>}

      {d && d.ready && (
        <>
          <div className="grid" style={{ gridTemplateColumns: `repeat(${shown.length}, 1fr)` }}>
            {shown.map((a) => (
              <div className="card stat" key={a.key} style={{ borderTop: `2px solid ${a.color}` }}>
                <div className="label">{a.label}</div>
                <div className="value" style={{ color: a.color === "var(--faint)" ? "var(--faint)" : a.color }}>
                  {d.approaches[a.key].avg_pct}<span className="muted" style={{ fontSize: 16 }}>%</span>
                </div>
                <div className="sub">averaged over all 5 questions</div>
              </div>
            ))}
          </div>

          <div className="card" style={{ marginTop: 18 }}>
            <div className="spread" style={{ marginBottom: 6 }}>
              <strong>Average accuracy across 5 questions</strong><Badge tone="green">⚡ live</Badge>
            </div>
            <BarChart max={100} data={shown.map((a) => ({ label: a.label.replace("Direct ", "D.").replace(" + rules", "+rules"), value: d.approaches[a.key].avg_pct, color: a.color }))} />
          </div>

          <div className="section-title">Per-question breakdown (score out of 5)</div>
          <div className="card" style={{ padding: 8, overflowX: "auto" }}>
            <table className="grid-table">
              <thead>
                <tr>
                  <th>Question</th>
                  {shown.map((a) => <th key={a.key} style={{ textAlign: "center" }}>{a.label}</th>)}
                </tr>
              </thead>
              <tbody>
                {d.questions.map((q, i) => (
                  <tr key={q.id}>
                    <td><span className="mono muted">{q.id}</span> <strong>{q.title}</strong>
                      <div className="faint" style={{ fontSize: 11, marginTop: 2, maxWidth: 520 }}>{q.prompt.slice(0, 90)}…</div></td>
                    {shown.map((a) => {
                      const pq = d.approaches[a.key].per_question[i];
                      return <td key={a.key} style={{ textAlign: "center" }}><ScorePill score={pq ? pq.total / pq.max : null} /></td>;
                    })}
                  </tr>
                ))}
                <tr>
                  <td><strong>Average</strong></td>
                  {shown.map((a) => (
                    <td key={a.key} style={{ textAlign: "center", fontFamily: "var(--mono)", fontWeight: 700, color: a.color }}>
                      {d.approaches[a.key].avg_pct}%
                    </td>
                  ))}
                </tr>
              </tbody>
            </table>
          </div>

          <div className="section-title">What this adds</div>
          <div className="callout green">
            <strong>Averaging over 5 questions de-noises the score and tests generalization.</strong> The society has to
            adapt its answer to what’s actually being asked — the same winning campaign should be <em>increased</em> for a
            scale-up question but merely <em>fed</em> for a reallocation one. A single-question benchmark can’t catch that;
            five can. The gap that holds up across all five — not just ROAS reallocation — is the credible one.
          </div>
          <div className="faint" style={{ fontSize: 11, marginTop: 16 }}>
            All live Qwen on Qwen Cloud. Same validated account dynamics, five different question framings, question-specific answer keys.
          </div>
        </>
      )}
    </div>
  );
}
