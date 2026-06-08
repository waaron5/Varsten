"use client";

// Raw Recharts chart bodies for the Command Center. Each fills its parent
// (ResponsiveContainer height="100%") so the grid cell governs the aspect ratio;
// there is no fixed ratio to break when the sidebar collapses. `debounce` lets the
// SVG re-lay-out once after the 0.22s shell grid transition rather than every
// frame. Colours come from the hand-rolled CSS tokens passed straight into SVG
// attributes (no Tailwind). Loaded only via lazyCharts.tsx (next/dynamic ssr:false).

import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { compact, usd } from "@/lib/format";
import type { CacheTrafficPoint, LatencyPoint, SavingsTrendPoint } from "@/lib/types";

const AXIS = { fontSize: 11, fontFamily: "var(--font-mono)", fill: "var(--text-3)" } as const;
const MARGIN = { top: 6, right: 8, bottom: 0, left: 6 } as const;
const DEBOUNCE = 150;

function shortDate(iso: string): string {
  const d = new Date(`${iso}T00:00:00`);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function num(value: string | number | null): number {
  if (value === null) return 0;
  const n = typeof value === "string" ? parseFloat(value) : value;
  return Number.isFinite(n) ? n : 0;
}

function MinimalTooltip({
  active,
  label,
  rows,
}: {
  active?: boolean;
  label?: string;
  rows: { name: string; value: string; color: string }[];
}) {
  if (!active || !label) return null;
  return (
    <div className="chart-tip">
      <div className="chart-tip-label">{shortDate(label)}</div>
      {rows.map((r) => (
        <div className="chart-tip-row" key={r.name}>
          <span className="chart-tip-dot" style={{ background: r.color }} />
          <span className="chart-tip-name">{r.name}</span>
          <span className="chart-tip-value">{r.value}</span>
        </div>
      ))}
    </div>
  );
}

export function CumulativeSavingsChart({ data }: { data: SavingsTrendPoint[] }) {
  const series = data.map((p) => ({
    date: p.date,
    cumulative: num(p.cumulative_saved_usd),
    daily: num(p.saved_usd),
  }));
  return (
    <ResponsiveContainer width="100%" height="100%" debounce={DEBOUNCE}>
      <AreaChart data={series} margin={MARGIN}>
        <defs>
          <linearGradient id="ccSavingsFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--brand)" stopOpacity={0.28} />
            <stop offset="100%" stopColor="var(--brand)" stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <XAxis
          dataKey="date"
          tickFormatter={shortDate}
          tick={AXIS}
          tickLine={false}
          axisLine={{ stroke: "var(--border)" }}
          minTickGap={32}
        />
        <YAxis tickFormatter={(v) => `$${compact(v)}`} tick={AXIS} tickLine={false} axisLine={false} width={50} />
        <Tooltip
          cursor={{ stroke: "var(--border-strong)", strokeWidth: 1 }}
          content={({ active, label, payload }) => (
            <MinimalTooltip
              active={active}
              label={label as string}
              rows={[
                { name: "Cumulative saved", value: usd(payload?.[0]?.payload?.cumulative ?? 0), color: "var(--brand)" },
                { name: "Saved that day", value: usd(payload?.[0]?.payload?.daily ?? 0), color: "var(--c4)" },
              ]}
            />
          )}
        />
        <Area
          type="monotone"
          dataKey="cumulative"
          stroke="var(--brand)"
          strokeWidth={2}
          fill="url(#ccSavingsFill)"
          dot={false}
          activeDot={{ r: 3, fill: "var(--brand)" }}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function HitRateChart({ data }: { data: CacheTrafficPoint[] }) {
  const series = data.map((p) => ({
    date: p.date,
    hit_rate: p.hit_rate === null ? null : num(p.hit_rate) * 100,
    requests: p.requests,
  }));
  return (
    <ResponsiveContainer width="100%" height="100%" debounce={DEBOUNCE}>
      <AreaChart data={series} margin={MARGIN}>
        <defs>
          <linearGradient id="ccHitFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--c2)" stopOpacity={0.22} />
            <stop offset="100%" stopColor="var(--c2)" stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <XAxis
          dataKey="date"
          tickFormatter={shortDate}
          tick={AXIS}
          tickLine={false}
          axisLine={{ stroke: "var(--border)" }}
          minTickGap={32}
        />
        <YAxis
          domain={[0, 100]}
          tickFormatter={(v) => `${v}%`}
          tick={AXIS}
          tickLine={false}
          axisLine={false}
          width={38}
        />
        <Tooltip
          cursor={{ stroke: "var(--border-strong)", strokeWidth: 1 }}
          content={({ active, label, payload }) => (
            <MinimalTooltip
              active={active}
              label={label as string}
              rows={[
                {
                  name: "Hit rate",
                  value: `${(payload?.[0]?.payload?.hit_rate ?? 0).toFixed(1)}%`,
                  color: "var(--c2)",
                },
                { name: "Requests", value: compact(payload?.[0]?.payload?.requests ?? 0), color: "var(--c4)" },
              ]}
            />
          )}
        />
        <Area
          type="monotone"
          dataKey="hit_rate"
          stroke="var(--c2)"
          strokeWidth={2}
          fill="url(#ccHitFill)"
          connectNulls
          dot={false}
          activeDot={{ r: 3, fill: "var(--c2)" }}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function LatencyChart({ data }: { data: LatencyPoint[] }) {
  const series = data.map((p) => ({ date: p.date, p50_ms: p.p50_ms, p95_ms: p.p95_ms }));
  return (
    <ResponsiveContainer width="100%" height="100%" debounce={DEBOUNCE}>
      <LineChart data={series} margin={MARGIN}>
        <CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="2 4" />
        <XAxis
          dataKey="date"
          tickFormatter={shortDate}
          tick={AXIS}
          tickLine={false}
          axisLine={{ stroke: "var(--border)" }}
          minTickGap={32}
        />
        <YAxis tickFormatter={(v) => `${compact(v)}ms`} tick={AXIS} tickLine={false} axisLine={false} width={50} />
        <Tooltip
          cursor={{ stroke: "var(--border-strong)", strokeWidth: 1 }}
          content={({ active, label, payload }) => (
            <MinimalTooltip
              active={active}
              label={label as string}
              rows={[
                { name: "p50", value: `${payload?.[0]?.payload?.p50_ms ?? "-"}ms`, color: "var(--c1)" },
                { name: "p95", value: `${payload?.[0]?.payload?.p95_ms ?? "-"}ms`, color: "var(--c3)" },
              ]}
            />
          )}
        />
        <Line type="monotone" dataKey="p50_ms" stroke="var(--c1)" strokeWidth={2} dot={false} connectNulls />
        <Line type="monotone" dataKey="p95_ms" stroke="var(--c3)" strokeWidth={2} dot={false} connectNulls />
      </LineChart>
    </ResponsiveContainer>
  );
}
