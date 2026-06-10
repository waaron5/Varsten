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
import type { ReactNode } from "react";
import { compact, usd } from "@/lib/format";
import type { CacheTrafficPoint, LatencyPoint, SavingsTrendPoint } from "@/lib/types";

const AXIS = { fontSize: 11, fontFamily: "var(--font-mono)", fill: "var(--text-3)" } as const;
const MARGIN = { top: 6, right: 8, bottom: 0, left: 6 } as const;
const DEBOUNCE = 150;
const INITIAL_DIMENSION = { width: 1, height: 1 } as const;
const TOOLTIP_CURSOR = { stroke: "var(--border-strong)", strokeWidth: 1 } as const;
type TooltipPoint = Record<string, unknown> | undefined;
type TooltipRow = { name: string; value: string; color: string };

function shortDate(iso: string): string {
  const d = new Date(`${iso}T00:00:00`);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function num(value: string | number | null): number {
  if (value === null) return 0;
  const n = typeof value === "string" ? parseFloat(value) : value;
  return Number.isFinite(n) ? n : 0;
}

function tooltipNum(value: unknown): number {
  return typeof value === "number" || typeof value === "string" ? num(value) : 0;
}

function MinimalTooltip({
  active,
  label,
  rows,
}: {
  active?: boolean;
  label?: string;
  rows: TooltipRow[];
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

function ChartTooltip({ rowsForPoint }: { rowsForPoint: (point: TooltipPoint) => TooltipRow[] }) {
  return (
    <Tooltip
      cursor={TOOLTIP_CURSOR}
      content={({ active, label, payload }) => (
        <MinimalTooltip active={active} label={label as string} rows={rowsForPoint(payload?.[0]?.payload)} />
      )}
    />
  );
}

function ChartFrame({ children }: { children: ReactNode }) {
  return (
    <ResponsiveContainer width="100%" height="100%" debounce={DEBOUNCE} initialDimension={INITIAL_DIMENSION}>
      {children}
    </ResponsiveContainer>
  );
}

function DateAxis() {
  return (
    <XAxis
      dataKey="date"
      tickFormatter={shortDate}
      tick={AXIS}
      tickLine={false}
      axisLine={{ stroke: "var(--border)" }}
      minTickGap={32}
    />
  );
}

// Running cumulative totals for the wedge. Module-level (not in render) so the
// accumulators stay out of the component body.
function toWedgeSeries(data: SavingsTrendPoint[]) {
  let cumBaseline = 0;
  let cumOptimized = 0;
  return data.map((p) => {
    cumBaseline += num(p.baseline_usd);
    cumOptimized += num(p.optimized_usd);
    return {
      date: p.date,
      optimized: cumOptimized, // actual spend (the floor + the solid line)
      saved: cumBaseline - cumOptimized, // the wedge height (stacked on the floor)
      baseline: cumBaseline, // naive-retail (top of the band + the dashed line)
    };
  });
}

// The savings wedge: cumulative naive-retail spend (what they would have paid)
// against cumulative actual spend, with the gap between them shaded as the saved
// dollars. The proof-of-value hero. Built with two stacked areas so the band sits
// exactly in the gap: an invisible floor at actual spend, then the savings band
// stacked on top (floor + band = naive-retail). Each area's top stroke doubles as
// a boundary line — solid for actual spend, faint dashed for naive-retail — so the
// whole thing is one AreaChart, no separate Line layer.
export function CumulativeSavingsChart({ data }: { data: SavingsTrendPoint[] }) {
  const series = toWedgeSeries(data);
  return (
    <ChartFrame>
      <AreaChart data={series} margin={MARGIN}>
        <defs>
          <linearGradient id="ccWedgeFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--brand)" stopOpacity={0.26} />
            <stop offset="100%" stopColor="var(--brand)" stopOpacity={0.03} />
          </linearGradient>
        </defs>
        <DateAxis />
        <YAxis tickFormatter={(v) => `$${compact(v)}`} tick={AXIS} tickLine={false} axisLine={false} width={50} />
        <ChartTooltip
          rowsForPoint={(point) => [
            { name: "Naive retail", value: usd(tooltipNum(point?.baseline)), color: "var(--text-3)" },
            { name: "Actual spend", value: usd(tooltipNum(point?.optimized)), color: "var(--text)" },
            { name: "Saved", value: usd(tooltipNum(point?.saved)), color: "var(--brand)" },
          ]}
        />
        {/* Invisible floor at actual spend; its top stroke is the solid actual-spend
            line. */}
        <Area
          type="monotone"
          dataKey="optimized"
          stackId="wedge"
          stroke="var(--text)"
          strokeWidth={2}
          fill="none"
          dot={false}
          isAnimationActive={false}
        />
        {/* The savings band, stacked from actual spend up to naive-retail; its top
            stroke is the faint dashed naive-retail line. */}
        <Area
          type="monotone"
          dataKey="saved"
          stackId="wedge"
          stroke="var(--text-3)"
          strokeWidth={1.5}
          strokeDasharray="4 3"
          fill="url(#ccWedgeFill)"
          dot={false}
          isAnimationActive={false}
        />
      </AreaChart>
    </ChartFrame>
  );
}

export function HitRateChart({ data }: { data: CacheTrafficPoint[] }) {
  const series = data.map((p) => ({
    date: p.date,
    hit_rate: p.hit_rate === null ? null : num(p.hit_rate) * 100,
    requests: p.requests,
  }));
  return (
    <ChartFrame>
      <AreaChart data={series} margin={MARGIN}>
        <defs>
          <linearGradient id="ccHitFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--c2)" stopOpacity={0.22} />
            <stop offset="100%" stopColor="var(--c2)" stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <DateAxis />
        <YAxis
          domain={[0, 100]}
          tickFormatter={(v) => `${v}%`}
          tick={AXIS}
          tickLine={false}
          axisLine={false}
          width={38}
        />
        <ChartTooltip
          rowsForPoint={(point) => [
            {
              name: "Hit rate",
              value: `${tooltipNum(point?.hit_rate).toFixed(1)}%`,
              color: "var(--c2)",
            },
            { name: "Requests", value: compact(tooltipNum(point?.requests)), color: "var(--c4)" },
          ]}
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
    </ChartFrame>
  );
}

// Latency tick in human units: raw ms under a second, seconds above it. `compact`
// here renders 1100 as "1.1Kms" (kilo-milliseconds), which is not a unit.
function latencyTick(v: number): string {
  return v < 1000 ? `${v}ms` : `${(v / 1000).toFixed(1)}s`;
}

// p95 and p99 only. p50 is the happy-path median; p95/p99 are the tails that catch
// performance regressions, so they are what the panel surfaces.
export function LatencyChart({ data }: { data: LatencyPoint[] }) {
  const series = data.map((p) => ({ date: p.date, p95_ms: p.p95_ms, p99_ms: p.p99_ms }));
  return (
    <ChartFrame>
      <LineChart data={series} margin={MARGIN}>
        <CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="2 4" />
        <DateAxis />
        <YAxis tickFormatter={latencyTick} tick={AXIS} tickLine={false} axisLine={false} width={50} />
        <ChartTooltip
          rowsForPoint={(point) => [
            { name: "p95", value: `${point?.p95_ms ?? "-"}ms`, color: "var(--c3)" },
            { name: "p99 (tail)", value: `${point?.p99_ms ?? "-"}ms`, color: "var(--c3)" },
          ]}
        />
        {/* p99 tail: a faint dashed upper line so the latency tail is visible
            without competing with the p95 read. */}
        <Line
          type="monotone"
          dataKey="p99_ms"
          stroke="var(--c3)"
          strokeOpacity={0.4}
          strokeWidth={1.5}
          strokeDasharray="3 3"
          dot={false}
          connectNulls
        />
        <Line type="monotone" dataKey="p95_ms" stroke="var(--c3)" strokeWidth={2} dot={false} connectNulls />
      </LineChart>
    </ChartFrame>
  );
}

// A KPI sparkline: pure stroke, zero chrome. Axes, grid and tooltip are all
// disabled (per the design constraint) so it reads as a clean 30-day trend line
// inside a BAN tile. Colour comes from a CSS token the caller passes.
export function Sparkline({ data, color }: { data: (number | null)[]; color: string }) {
  const series = data.map((v, i) => ({ i, v }));
  return (
    <ResponsiveContainer width="100%" height="100%" debounce={DEBOUNCE} initialDimension={INITIAL_DIMENSION}>
      <LineChart data={series} margin={{ top: 2, right: 0, bottom: 2, left: 0 }}>
        <XAxis dataKey="i" hide />
        <YAxis hide domain={["dataMin", "dataMax"]} />
        <Tooltip active={false} />
        <Line
          type="monotone"
          dataKey="v"
          stroke={color}
          strokeWidth={1.5}
          dot={false}
          connectNulls
          isAnimationActive={false}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
