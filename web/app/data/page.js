"use client";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { Spinner, Badge, ErrorBox } from "../components/ui";

export default function DataPage() {
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => { api.data().then(setD).catch(setErr); }, []);

  return (
    <div>
      <div className="page-head">
        <div className="eyebrow" style={{ color: "var(--green)" }}>The data · full transparency</div>
        <h2>What the agents actually see</h2>
        <p>
          Everything is <strong>synthetic and deterministic</strong> — generated once from a fixed seed, checked into the
          repo, resembling no real customer. That’s what makes the comparison honest: every architecture runs on the
          identical data, tools, rules, and scoring.
        </p>
      </div>

      <ErrorBox error={err} />
      {!d && !err && <Spinner label="Loading dataset…" />}

      {d && (
        <>
          <div className="grid c3">
            <div className="card stat"><div className="label">Dataset</div><div className="value" style={{ fontSize: 26 }}>{d.sim.n_campaigns}×{d.sim.days}</div><div className="sub">campaigns × days, seed {d.sim.seed}</div></div>
            <div className="card stat"><div className="label">Recent window</div><div className="value" style={{ fontSize: 26 }}>{d.sim.recent_window}d</div><div className="sub">where each scenario’s effect is injected</div></div>
            <div className="card stat"><div className="label">Scenarios</div><div className="value" style={{ fontSize: 26 }}>{d.scenarios.length}</div><div className="sub">{d.scenarios.filter((s) => s.is_trap).length} of them are traps</div></div>
          </div>

          <div className="section-title">The 5 campaigns</div>
          <div className="card" style={{ padding: 8, overflowX: "auto" }}>
            <table className="grid-table">
              <thead><tr><th>ID</th><th>Name</th><th>Platform</th><th>Kind</th><th className="num" style={{ textAlign: "right" }}>$/day</th><th className="num" style={{ textAlign: "right" }}>CTR</th><th className="num" style={{ textAlign: "right" }}>CVR</th><th className="num" style={{ textAlign: "right" }}>AOV</th></tr></thead>
              <tbody>
                {d.campaigns.map((c) => (
                  <tr key={c.id}>
                    <td className="mono muted">{c.id}</td><td>{c.name}</td><td>{c.platform}</td>
                    <td>{c.kind}{c.id === "G2" && <Badge tone="amber" >brand · protected</Badge>}</td>
                    <td className="num">${c.daily_spend}</td><td className="num">{(c.ctr * 100).toFixed(1)}%</td>
                    <td className="num">{(c.cvr * 100).toFixed(1)}%</td><td className="num">${c.aov}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="grid c2" style={{ marginTop: 18 }}>
            <div className="card">
              <div className="section-title" style={{ marginTop: 0 }}>Business rules (enforced by the tools)</div>
              <div className="kv">
                <div className="k">Brand floor</div><div className="v">C2 ≥ ${d.constraints.brand_floor_monthly}/mo</div>
                <div className="k">Pacing cap</div><div className="v">≤ {d.constraints.max_weekly_shift_pct}% moved/week</div>
                <div className="k">Learning phase</div><div className="v">no edits within {d.constraints.learning_phase_days} days</div>
              </div>
              <div className="muted" style={{ fontSize: 12, marginTop: 10 }}>
                These are what <span className="mono">propose_reallocation</span> checks and the Risk officer vetoes on.
                (Telling a bare LLM these rules only got it to 5.8 — see the Overview.)
              </div>
            </div>
            <div className="card">
              <div className="section-title" style={{ marginTop: 0 }}>Industry benchmarks (the “KB”)</div>
              <div className="kv">
                {Object.entries(d.benchmarks).map(([k, v]) => (
                  <div key={k} style={{ display: "contents" }}>
                    <div className="k">{k.replace(/_/g, " ")}</div><div className="v">{v.value} <span className="faint">({v.source})</span></div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="section-title">The tool belt (shared by every architecture)</div>
          <div className="card">
            {d.tools.map((t) => (
              <div key={t.name} style={{ padding: "8px 0", borderBottom: "1px solid var(--border)" }}>
                <span className="chip" style={{ marginRight: 10 }}>{t.name}</span>
                <span className="muted" style={{ fontSize: 13 }}>{t.description}</span>
              </div>
            ))}
          </div>

          <div className="spread" style={{ margin: "34px 2px 14px" }}>
            <div className="section-title" style={{ margin: 0 }}>The 10 scenarios — what’s perturbed & the correct answer</div>
            <span className="trap-legend"><span className="swatch" /> ⚠ trap: the intuitive answer is wrong</span>
          </div>
          <div className="card" style={{ padding: 8, overflowX: "auto" }}>
            <table className="grid-table">
              <thead><tr><th>ID</th><th>What happens in the last 14 days</th><th>Correct answer</th></tr></thead>
              <tbody>
                {d.scenarios.map((s) => (
                  <tr key={s.id} className={s.is_trap ? "trap-row" : ""}>
                    <td className="mono muted">{s.id} {s.is_trap && <Badge tone="trap">trap</Badge>}</td>
                    <td style={{ fontSize: 12.5, lineHeight: 1.5 }}>{s.perturb}</td>
                    <td className="mono" style={{ fontSize: 12 }}>
                      {s.expected.root_cause} → {s.expected.action}
                      {s.expected.acceptable_targets?.length > 0 && <span className="faint"> (→{s.expected.acceptable_targets.join("/")})</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="section-title">Sample rows (raw daily data)</div>
          <div className="card" style={{ padding: 8, overflowX: "auto" }}>
            <table className="grid-table">
              <thead><tr><th>Day</th><th>Campaign</th><th className="num" style={{ textAlign: "right" }}>Spend</th><th className="num" style={{ textAlign: "right" }}>Impr.</th><th className="num" style={{ textAlign: "right" }}>Clicks</th><th className="num" style={{ textAlign: "right" }}>Conv.</th><th className="num" style={{ textAlign: "right" }}>Revenue</th></tr></thead>
              <tbody>
                {d.sample_rows.map((r, i) => (
                  <tr key={i}>
                    <td className="mono muted">{r.day}</td><td>{r.campaign_id} · {r.name}</td>
                    <td className="num">${r.spend}</td><td className="num">{r.impressions}</td>
                    <td className="num">{r.clicks}</td><td className="num">{r.conversions}</td><td className="num">${r.revenue}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="faint" style={{ fontSize: 11, marginTop: 10 }}>
              90 days × 5 campaigns = 450 rows, generated deterministically (seed {d.sim.seed}). Scenarios perturb only the last {d.sim.recent_window} days.
            </div>
          </div>
        </>
      )}
    </div>
  );
}
