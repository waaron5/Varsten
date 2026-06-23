"use client";

// Raw Recharts chart bodies for the Dashboard. Each fills its parent
// (ResponsiveContainer height="100%") so the grid cell governs the aspect ratio;
// there is no fixed ratio to break when the sidebar collapses. `debounce` lets the
// SVG re-lay-out once after the 0.22s shell grid transition rather than every
// frame. Colours come from the hand-rolled CSS tokens passed straight into SVG
// attributes (no Tailwind). Loaded only via lazyCharts.tsx (next/dynamic ssr:false).

import {
  Bar,
  BarChart,
  CartesianGrid,
  LabelList,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { compact, usd } from "@/lib/format";
import type { SavingsTrendBucket } from "@/lib/types";

const AXIS = { fontSize: 11, fontFamily: "var(--font-mono)", fill: "var(--text-3)" } as const;
const DEBOUNCE = 150;
const INITIAL_DIMENSION = { width: 1, height: 1 } as const;
const TOOLTIP_CURSOR = { stroke: "var(--border-strong)", strokeWidth: 1 } as const;
const MOBILE_CHART_QUERY = "(max-width: 700px)";
const MAX_DAILY_BAR_SIZE = 34;
const DENSE_LABEL_DAY_LIMIT = 14;
const DENSE_TICK_DAY_LIMIT = 23;
const LABEL_FONT_SIZE = 11;
const LABEL_MIN_HEIGHT = 16;
const LABEL_CHAR_WIDTH = 6.8;
const LABEL_HORIZONTAL_PADDING = 8;

function shortDate(iso: string): string {
  const d = new Date(`${iso}T00:00:00`);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function shortDay(iso: string): string {
  return String(new Date(`${iso}T00:00:00`).getDate());
}

function dayOfMonth(iso: string): number {
  return new Date(`${iso}T00:00:00`).getDate();
}

function num(value: string | number | null): number {
  if (value === null) return 0;
  const n = typeof value === "string" ? parseFloat(value) : value;
  return Number.isFinite(n) ? n : 0;
}

function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() =>
    typeof window === "undefined" ? false : window.matchMedia(query).matches,
  );

  useEffect(() => {
    const media = window.matchMedia(query);
    const sync = () => setMatches(media.matches);
    sync();
    media.addEventListener("change", sync);
    return () => media.removeEventListener("change", sync);
  }, [query]);

  return matches;
}

function ChartFrame({ children }: { children: ReactNode }) {
  return (
    <ResponsiveContainer width="100%" height="100%" debounce={DEBOUNCE} initialDimension={INITIAL_DIMENSION}>
      {children}
    </ResponsiveContainer>
  );
}

function withBookends(dates: string[], selected: Iterable<string>): string[] {
  const ordered = new Set<string>();
  const first = dates[0];
  const last = dates[dates.length - 1];
  if (first) ordered.add(first);
  for (const date of selected) {
    if (dates.includes(date)) ordered.add(date);
  }
  if (last) ordered.add(last);
  return dates.filter((date) => ordered.has(date));
}

function buildDateTicks(series: SavingsCapturedDatum[], isCompact: boolean): string[] {
  const dates = series.map((point) => point.date);
  const count = dates.length;
  if (count <= 1) return dates;

  if (isCompact) {
    const anchors = new Set([1, 10, 20].map(String));
    return withBookends(
      dates,
      dates.filter((date) => anchors.has(shortDay(date))),
    );
  }

  if (count <= DENSE_LABEL_DAY_LIMIT) return dates;

  if (count <= DENSE_TICK_DAY_LIMIT) {
    const step = count <= 18 ? 2 : 3;
    return withBookends(dates, dates.filter((_, index) => index % step === 0));
  }

  const weeklyAnchors = new Set([1, 7, 14, 21, 28]);
  return withBookends(
    dates,
    dates.filter((date) => weeklyAnchors.has(dayOfMonth(date))),
  );
}

function DateAxis({ ticks }: { ticks: string[] }) {
  return (
    <XAxis
      dataKey="date"
      tickFormatter={shortDay}
      tick={AXIS}
      tickLine={false}
      axisLine={{ stroke: "var(--border)" }}
      ticks={ticks.length ? ticks : undefined}
      interval={0}
      minTickGap={8}
    />
  );
}

// Stacked per-day view: the beige base is what was actually paid (optimized
// spend) and the green stacked on top is the gross avoided spend. The two sum to
// the counterfactual (what they would have paid without Varsten), so the full bar
// height reads as naive retail cost. Mirrors the "Savings captured" mockup.
interface SavingsCapturedDatum {
  date: string;
  spendWith: number;
  savings: number;
  counterfactual: number;
}

function toSavingsCaptured(points: SavingsTrendBucket[]): SavingsCapturedDatum[] {
  return [...points]
    .sort((a, b) => a.date.localeCompare(b.date))
    .map((point) => ({
      date: point.date,
      spendWith: num(point.optimized_usd),
      savings: num(point.saved_usd),
      counterfactual: num(point.baseline_usd),
    }));
}

interface BarLabelRenderProps {
  x?: number | string;
  y?: number | string;
  width?: number | string;
  height?: number | string;
  value?: number | string | boolean | null;
}

function barLabelValue(value: number): string | null {
  const rounded = Math.round(value);
  if (rounded <= 0) return null;
  return `$${compact(rounded)}`;
}

function estimatedTextWidth(label: string): number {
  return label.length * LABEL_CHAR_WIDTH;
}

// Renders a compact whole-dollar value centered inside a bar segment when it can
// fit cleanly. Exact daily values remain available in the tooltip for dense MTD.
function makeBarLabel(fill: string) {
  return function BarLabel({ x, y, width, height, value }: BarLabelRenderProps) {
    if (x === undefined || y === undefined || width === undefined || height === undefined) {
      return null;
    }
    const v = typeof value === "number" || typeof value === "string" ? num(value) : 0;
    const label = barLabelValue(v);
    if (!label) return null;
    const xn = num(x);
    const yn = num(y);
    const wn = num(width);
    const hn = num(height);
    if (hn < LABEL_MIN_HEIGHT || wn < estimatedTextWidth(label) + LABEL_HORIZONTAL_PADDING) return null;
    return (
      <text
        x={xn + wn / 2}
        y={yn + hn / 2}
        fill={fill}
        fontSize={LABEL_FONT_SIZE}
        fontWeight={600}
        fontFamily="var(--font-mono)"
        textAnchor="middle"
        dominantBaseline="central"
      >
        {label}
      </text>
    );
  };
}

function SavingsCapturedTooltip({
  active,
  payload,
  spendLabel,
}: {
  active?: boolean;
  payload?: ReadonlyArray<{ payload?: SavingsCapturedDatum }>;
  spendLabel: string;
}) {
  if (!active) return null;
  const point = payload?.[0]?.payload;
  if (!point) return null;
  return (
    <div className="chart-tip">
      <div className="chart-tip-label">{shortDate(point.date)}</div>
      <div className="chart-tip-row">
        <span className="chart-tip-dot savings-cost" />
        <span className="chart-tip-name">{spendLabel}</span>
        <span className="chart-tip-value">{usd(point.spendWith)}</span>
      </div>
      <div className="chart-tip-row">
        <span className="chart-tip-dot savings-net" />
        <span className="chart-tip-name">Savings</span>
        <span className="chart-tip-value">{usd(point.savings)}</span>
      </div>
      <div className="chart-tip-row">
        <span className="chart-tip-dot savings-spend" />
        <span className="chart-tip-name">Projected cost</span>
        <span className="chart-tip-value">{usd(point.counterfactual)}</span>
      </div>
    </div>
  );
}

export function NetSavingsTrendChart({
  points,
}: {
  points: SavingsTrendBucket[];
}) {
  const series = useMemo(() => toSavingsCaptured(points), [points]);
  const isCompact = useMediaQuery(MOBILE_CHART_QUERY);
  const dateTicks = useMemo(() => buildDateTicks(series, isCompact), [isCompact, series]);
  const showValueLabels = !isCompact && series.length <= DENSE_LABEL_DAY_LIMIT;
  const barCategoryGap = series.length > DENSE_TICK_DAY_LIMIT ? "10%" : "18%";
  const spendLabel = "Actual spend";
  const SpendLabel = useMemo(() => makeBarLabel("var(--chart-spend-label)"), []);
  const SavingsLabel = useMemo(() => makeBarLabel("#ffffff"), []);

  return (
    <ChartFrame>
      <BarChart data={series} margin={{ top: 12, right: 8, bottom: 0, left: 4 }} barCategoryGap={barCategoryGap}>
        <CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="2 4" />
        <DateAxis ticks={dateTicks} />
        <YAxis
          tickFormatter={(v) => `$${compact(v)}`}
          tick={AXIS}
          tickLine={false}
          axisLine={false}
          width={54}
        />
        <Tooltip
          cursor={TOOLTIP_CURSOR}
          content={({ active, payload }) => (
            <SavingsCapturedTooltip active={active} payload={payload} spendLabel={spendLabel} />
          )}
        />
        <Bar
          dataKey="spendWith"
          stackId="cost"
          name={spendLabel}
          fill="var(--chart-spend)"
          isAnimationActive={false}
          maxBarSize={MAX_DAILY_BAR_SIZE}
        >
          {showValueLabels ? <LabelList dataKey="spendWith" content={SpendLabel} /> : null}
        </Bar>
        <Bar
          dataKey="savings"
          stackId="cost"
          name="Savings"
          fill="var(--brand)"
          radius={[4, 4, 0, 0]}
          isAnimationActive={false}
          maxBarSize={MAX_DAILY_BAR_SIZE}
        >
          {showValueLabels ? <LabelList dataKey="savings" content={SavingsLabel} /> : null}
        </Bar>
      </BarChart>
    </ChartFrame>
  );
}
