"use client";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { Spinner, Badge, ErrorBox } from "../components/ui";

// Simple log-scale token-vs-N chart with context-window walls drawn in.
function ScaleChart({ points, height = 300 }) {
  const maxN = points[points.length - 1].n;
  const maxTok = 128000;
  const lx = (n) => 6 + (Math.log10(n) / Math.log10(maxN)) * 90;
  const ly = (t) => 54 - (Math.log10(Math.max(t, 1)) / Math.log10(maxTok)) * 50;
  const path = points.map((p, i) => `${i === 0 ? "M" : "L"} ${lx(p.n)} ${ly(p.full_prompt_tokens)}`).join(" ");
  const walls = [[32000, "32k window"], [128000, "128k window"]];
  return (
    <svg viewBox="0 0 100 62" style={{ width: "100%", height }}>
      {walls.map(([t, label]) => (
        <g key={t}>
          <line x1="6" x2="96" y1={ly(t)} y2={ly(t)} stroke="var(--red)" strokeWidth="0.3" strokeDasharray="1.5 1" opacity="0.7" />
          <text x="96" y={ly(t) - 1} fontSize="2.1" fill="var(--red)" textAnchor="end">{label}</text>
        </g>
      ))}
      <path d={path} fill="none" stroke="var(--amber)" strokeWidth="0.7" />
      {points.map((p, i) => (
        <g key={i}>
          <circle cx={lx(p.n)} cy={ly(p.full_prompt_tokens)} r="1" fill="var(--amber)" />
          <text x={lx(p.n)} y="59.5" fontSize="2" fill="var(--muted)" textAnchor="middle">{p.n}</text>
        </g>
      ))}
      <text x="50" y="61.8" fontSize="2" fill="var(--faint)" textAnchor="middle"># campaigns (log scale)</text>
    </svg>
  );
}

export default function Scaling() {
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => { api.scaling().then((r) => { if (r.ready) setD(r); }).catch(setErr); }, []);

  return (
    <div>
      <div className="page-head">
        <div className="eyebrow" style={{ color: "var(--amber)" }}>Scaling stress test</div>
        <h2>Where “read the whole account” breaks</h2>
        <p>
          Every architecture here reads the full account into the model’s context. That’s fine for 5 campaigns —
          but the context is <strong>O(N)</strong> in campaign count. Here’s the real measured growth, and the wall.
        </p>
      </div>

      <ErrorBox error={err} />
      {!d && !err && <Spinner label="Loading scaling data…" />}

      {d && (
        <>
          <div className="grid c3">
            <div className="card stat"><div className="label">At 5 campaigns</div><div className="value" style={{ fontSize: 26 }}>{d.points[0].full_prompt_tokens}</div><div className="sub">prompt tokens (the demo)</div></div>
            <div className="card stat tint-amber"><div className="label">At 1,000 campaigns</div><div className="value" style={{ fontSize: 26, color: "var(--amber)" }}>{(d.points.find((p) => p.n === 1000)?.full_prompt_tokens / 1000).toFixed(0)}k</div><div className="sub">fills a 32k context window</div></div>
            <div className="card stat"><div className="label">Growth</div><div className="value" style={{ fontSize: 26 }}>≈ O(N)</div><div className="sub">linear in campaign count</div></div>
          </div>

          <div className="card" style={{ marginTop: 18 }}>
            <div className="spread" style={{ marginBottom: 6 }}>
              <strong>Prompt tokens vs. account size (log–log, with context-window walls)</strong>
              <Badge tone="amber">measured</Badge>
            </div>
            <ScaleChart points={d.points} />
          </div>

          <div className="grid c2" style={{ marginTop: 18 }}>
            <div className="card" style={{ padding: 8, overflowX: "auto" }}>
              <div className="section-title" style={{ marginTop: 4, marginLeft: 8 }}>Context growth (measured)</div>
              <table className="grid-table">
                <thead><tr><th className="num" style={{ textAlign: "right" }}>Campaigns</th><th className="num" style={{ textAlign: "right" }}>Prompt tokens</th><th>Fits in…</th></tr></thead>
                <tbody>
                  {d.points.map((p) => (
                    <tr key={p.n} className={p.full_prompt_tokens > 32000 ? "trap-row" : ""}>
                      <td className="num">{p.n.toLocaleString()}</td>
                      <td className="num">{p.full_prompt_tokens.toLocaleString()}</td>
                      <td>{p.full_prompt_tokens > 128000 ? <span style={{ color: "var(--red)" }}>✗ overflows 128k</span>
                        : p.full_prompt_tokens > 32000 ? <span style={{ color: "var(--amber)" }}>needs 128k window</span>
                        : <span className="muted">32k window ✓</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="card" style={{ padding: 8, overflowX: "auto" }}>
              <div className="section-title" style={{ marginTop: 4, marginLeft: 8 }}>Live latency (real Qwen, single call)</div>
              <table className="grid-table">
                <thead><tr><th className="num" style={{ textAlign: "right" }}>Campaigns</th><th className="num" style={{ textAlign: "right" }}>Latency</th><th className="num" style={{ textAlign: "right" }}>Input tokens</th></tr></thead>
                <tbody>
                  {(d.live || []).map((l) => (
                    <tr key={l.n}>
                      <td className="num">{l.n}</td><td className="num">{l.latency_s}s</td><td className="num">{l.input_tokens.toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="muted" style={{ fontSize: 12, marginTop: 10, padding: "0 8px" }}>
                One call stays ~flat, but input tokens jump ~25× from 5→200 campaigns. The society makes ~4–6 calls per
                decision, so its <strong>token cost</strong> scales ~linearly with campaigns × specialists.
              </div>
            </div>
          </div>

          <div className="section-title">What this means</div>
          <div className="grid c2">
            <div className="callout">
              <strong>The demo scales to ~hundreds of campaigns, then hits a wall.</strong> Around <strong>1,000 campaigns</strong>
              the “describe the whole account” prompt fills a 32k window; past ~4,000 it overflows 128k. Cost climbs linearly
              well before that. So this exact design is fine for an SMB account, not a 50,000-campaign enterprise one.
            </div>
            <div className="callout green">
              <strong>The fix is decomposition, not a bigger model.</strong> Cluster/summarize campaigns, diagnose per-segment,
              and only escalate anomalies to the full society. The parts that already scale: the deterministic constraint
              validators (O(1) per rule), the triage-first pipeline (skip trivial cases), and retrieval-bounded memory
              (context stays flat regardless of history).
            </div>
          </div>
          <div className="faint" style={{ fontSize: 11, marginTop: 16 }}>
            Token counts measured from the real prompt builder; latency from live Qwen on Qwen Cloud. Synthetic campaigns, deterministic seed.
          </div>
        </>
      )}
    </div>
  );
}
