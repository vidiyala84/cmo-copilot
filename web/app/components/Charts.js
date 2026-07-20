"use client";

// Hand-rolled SVG charts — zero chart dependencies, theme-aware via CSS vars.

export function BarChart({ data, max = 10, height = 260 }) {
  const W = 100 / data.length;
  return (
    <svg viewBox="0 0 100 62" style={{ width: "100%", height }} preserveAspectRatio="none">
      {[0.25, 0.5, 0.75, 1].map((g) => (
        <line key={g} x1="0" x2="100" y1={54 - 54 * g} y2={54 - 54 * g}
              stroke="var(--border)" strokeWidth="0.2" />
      ))}
      {data.map((d, i) => {
        const h = Math.max(0.5, (d.value / max) * 54);
        const x = i * W + W * 0.18;
        const w = W * 0.64;
        return (
          <g key={i}>
            <rect x={x} y={54 - h} width={w} height={h} rx="0.8" fill={d.color || "var(--blue)"} />
            <text x={i * W + W / 2} y={61} fontSize="2.1" fill="var(--muted)" textAnchor="middle">
              {d.label}
            </text>
            <text x={i * W + W / 2} y={52 - h} fontSize="2.6" fill="var(--text)" textAnchor="middle"
                  fontFamily="var(--mono)" fontWeight="700">
              {d.value}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

export function LineChart({ points, baseline, max = 10, labels, height = 280 }) {
  const n = points.length;
  const px = (i) => 6 + (i / Math.max(1, n - 1)) * 90;
  const py = (v) => 52 - (v / max) * 48;
  const path = points.map((v, i) => `${i === 0 ? "M" : "L"} ${px(i)} ${py(v)}`).join(" ");
  const area = `${path} L ${px(n - 1)} 52 L ${px(0)} 52 Z`;
  return (
    <svg viewBox="0 0 100 60" style={{ width: "100%", height }}>
      <defs>
        <linearGradient id="areaFill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--blue)" stopOpacity="0.28" />
          <stop offset="100%" stopColor="var(--blue)" stopOpacity="0" />
        </linearGradient>
      </defs>
      {[0, 0.25, 0.5, 0.75, 1].map((g) => (
        <g key={g}>
          <line x1="6" x2="96" y1={py(max * g)} y2={py(max * g)} stroke="var(--border)" strokeWidth="0.2" />
          <text x="2" y={py(max * g) + 1} fontSize="2" fill="var(--faint)">{Math.round(max * g)}</text>
        </g>
      ))}
      {baseline != null && (
        <>
          <line x1="6" x2="96" y1={py(baseline)} y2={py(baseline)} stroke="var(--muted)"
                strokeWidth="0.4" strokeDasharray="1.5 1.2" />
          <text x="96" y={py(baseline) - 1} fontSize="2.1" fill="var(--muted)" textAnchor="end">
            baseline {baseline}
          </text>
        </>
      )}
      <path d={area} fill="url(#areaFill)" />
      <path d={path} fill="none" stroke="var(--blue)" strokeWidth="0.7" strokeLinejoin="round" />
      {points.map((v, i) => (
        <g key={i}>
          <circle cx={px(i)} cy={py(v)} r="1.1" fill="var(--blue)" stroke="var(--bg)" strokeWidth="0.4" />
          <text x={px(i)} y={py(v) - 2.2} fontSize="2.4" fill="var(--text)" textAnchor="middle"
                fontFamily="var(--mono)" fontWeight="700">{v}</text>
          <text x={px(i)} y="58" fontSize="2.1" fill="var(--muted)" textAnchor="middle">
            {labels ? labels[i] : `S${i + 1}`}
          </text>
        </g>
      ))}
    </svg>
  );
}
