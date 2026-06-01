"use client";

import type { SpendTrendPoint } from "@/lib/types";
import { usd } from "@/lib/format";

// Hand-built SVG line chart, ported from the mockup. Server returns only days
// with data, so a single point still renders as a flat marker.
export function SpendLineChart({ points }: { points: SpendTrendPoint[] }) {
  if (points.length === 0) {
    return <div className="empty es" style={{ padding: 40 }}>No spend in this window yet.</div>;
  }

  const W = 1000;
  const h = 240;
  const pad = { t: 14, r: 14, b: 26, l: 56 };
  const values = points.map((p) => parseFloat(p.spend));
  const max = Math.max(...values) * 1.08 || 1;
  const min = Math.min(...values, 0) * 0.92;
  const plotW = W - pad.l - pad.r;
  const plotH = h - pad.t - pad.b;
  const n = points.length;
  const x = (i: number) => pad.l + (n === 1 ? plotW / 2 : (i / (n - 1)) * plotW);
  const y = (v: number) => pad.t + (1 - (v - min) / (max - min || 1)) * plotH;
  const line = values.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(" ");

  const grid: React.ReactElement[] = [];
  for (let g = 0; g <= 4; g++) {
    const v = min + ((max - min) * g) / 4;
    const yy = y(v);
    grid.push(<line key={`g${g}`} className="gridline" x1={pad.l} y1={yy} x2={W - pad.r} y2={yy} />);
    grid.push(
      <text key={`l${g}`} className="axis-lbl" x={pad.l - 9} y={yy + 3} textAnchor="end">
        {usd(v, 2)}
      </text>,
    );
  }

  const step = Math.max(1, Math.ceil(n / 8));
  const xlabels = points
    .map((p, i) => ({ p, i }))
    .filter(({ i }) => i % step === 0 || i === n - 1)
    .map(({ p, i }) => (
      <text key={`x${i}`} className="axis-lbl" x={x(i)} y={h - 7} textAnchor="middle">
        {p.date.slice(5)}
      </text>
    ));

  return (
    <div className="chart-wrap">
      <svg className="chart" viewBox={`0 0 ${W} ${h}`} preserveAspectRatio="none">
        <defs>
          <linearGradient id="ag" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.26" />
            <stop offset="100%" stopColor="var(--accent)" stopOpacity="0" />
          </linearGradient>
        </defs>
        {grid}
        {xlabels}
        <path d={`${line} L${x(n - 1)} ${pad.t + plotH} L${x(0)} ${pad.t + plotH} Z`} fill="url(#ag)" />
        <path className="area-line" d={line} />
        <circle cx={x(n - 1)} cy={y(values[n - 1])} r={3.5} fill="var(--accent)" stroke="var(--surface)" strokeWidth={2} />
      </svg>
    </div>
  );
}

export interface HBarItem {
  name: string;
  value: number;
  color?: string;
}

export function HBars({ items }: { items: HBarItem[] }) {
  if (items.length === 0) {
    return <div className="empty es" style={{ padding: 30 }}>No data yet.</div>;
  }
  const mx = Math.max(...items.map((i) => i.value)) || 1;
  return (
    <div>
      {items.map((it, idx) => (
        <div className="hbar-row" key={idx}>
          <div className="hl">
            <span className="dot-ic" style={{ background: it.color ?? "var(--accent)" }} />
            {it.name}
          </div>
          <div className="hbar-track">
            <i style={{ width: `${((it.value / mx) * 100).toFixed(1)}%`, background: it.color ?? "var(--accent)" }} />
          </div>
          <div className="hv mono tnum">{usd(it.value, 2)}</div>
        </div>
      ))}
    </div>
  );
}
