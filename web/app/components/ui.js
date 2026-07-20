"use client";

export function Spinner({ label = "Running…" }) {
  return (
    <div className="loading-wrap">
      <div className="spinner" /> {label}
    </div>
  );
}

export function Button({ children, onClick, disabled, ghost, loading }) {
  return (
    <button className={"btn" + (ghost ? " ghost" : "")} onClick={onClick} disabled={disabled || loading}>
      {loading && <span className="spinner" style={{ width: 14, height: 14 }} />}
      {children}
    </button>
  );
}

export function Stat({ label, value, delta, deltaDir, sub, color }) {
  return (
    <div className="card stat" style={color ? { borderTop: `2px solid ${color}` } : undefined}>
      <div className="label">{label}</div>
      <div className="value" style={color ? { color } : undefined}>{value}</div>
      {delta != null && <div className={"delta " + (deltaDir || "up")}>{delta}</div>}
      {sub && <div className="sub">{sub}</div>}
    </div>
  );
}

export function Badge({ children, tone }) {
  return <span className={"badge" + (tone ? " " + tone : "")}>{children}</span>;
}

export function ScorePill({ score }) {
  const s = score == null ? null : score;
  let bg = "var(--red-dim)", fg = "var(--red)";
  if (s >= 0.8) { bg = "var(--green-dim)"; fg = "var(--green)"; }
  else if (s >= 0.4) { bg = "var(--amber-dim)"; fg = "var(--amber)"; }
  return <span className="score-pill" style={{ background: bg, color: fg }}>{s == null ? "—" : s.toFixed(1)}</span>;
}

export function ErrorBox({ error }) {
  if (!error) return null;
  return <div className="err">⚠ {String(error.message || error)}. Is the FastAPI backend running on {process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000"}?</div>;
}
