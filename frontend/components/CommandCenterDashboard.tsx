"use client";

// The three Command Center visual narratives: Margin engine, Proxy traffic, and
// Quality guardrails. Recharts components are lazy-loaded with next/dynamic
// (ssr: false) from this client module so the KPI tiles paint first and Recharts
// never runs during SSR (avoiding hydration mismatches). Colours come from the
// hand-rolled CSS tokens; no Tailwind.

import dynamic from "next/dynamic";
import type { ReactNode } from "react";
import { useProjectResource } from "@/components/useProjectResource";
import { percent } from "@/components/viewPrimitives";
import { api } from "@/lib/api";
import { compact, usd } from "@/lib/format";
import type { ActiveRoute, CommandCenterLiveSavings, ProxyTraffic, SavingsTrend } from "@/lib/types";

function ChartFallback() {
  return <div className="cc-chart-frame cc-chart-empty">Loading chart…</div>;
}

// Lazy, client-only chart imports. ssr:false is only valid in a Client Component
// (this module is "use client"), per the Next app-router docs.
const CumulativeSavingsChart = dynamic(
  () => import("./DashboardCharts").then((m) => m.CumulativeSavingsChart),
  { ssr: false, loading: ChartFallback },
);
const HitRateChart = dynamic(() => import("./DashboardCharts").then((m) => m.HitRateChart), {
  ssr: false,
  loading: ChartFallback,
});
const LatencyChart = dynamic(() => import("./DashboardCharts").then((m) => m.LatencyChart), {
  ssr: false,
  loading: ChartFallback,
});

function Stat({ label, value, tone }: { label: string; value: string; tone?: "pos" | "neg" }) {
  return (
    <div className="cc-stat">
      <div className="cc-stat-label">{label}</div>
      <div className={`cc-stat-value${tone ? ` ${tone}` : ""}`}>{value}</div>
    </div>
  );
}

function ChartEmpty({ label }: { label: string }) {
  return <div className="cc-chart-frame cc-chart-empty">{label}</div>;
}

function latency(ms: number | null | undefined): string {
  return ms === null || ms === undefined ? "—" : `${compact(ms)}ms`;
}

// --- Narrative 1: the margin engine -------------------------------------------

export function MarginEngineSection({ liveSavings }: { liveSavings: CommandCenterLiveSavings }) {
  const { data } = useProjectResource<SavingsTrend>(api.savingsTrend);
  const hasSeries = !!data && data.points.length > 0;
  return (
    <section className="card cc-section">
      <div className="card-head">
        <h3>Margin engine</h3>
        <span className="sub">cumulative savings vs naive-retail baseline · last 30 days</span>
      </div>
      <div className="cc-statstrip">
        <Stat label="Gross saved (mo)" value={usd(liveSavings.saved_month, 0)} tone="pos" />
        <Stat label="Net after fee (mo)" value={usd(liveSavings.net_saved_month, 0)} />
        <Stat label="Saved (30d)" value={data ? usd(data.total_saved_usd, 0) : "—"} />
        <Stat label="Annual run-rate" value={usd(liveSavings.annual_run_rate, 0)} />
      </div>
      <div className="cc-chart-wrap">
        {hasSeries ? <CumulativeSavingsChart data={data.points} /> : <ChartEmpty label="No savings recorded yet" />}
      </div>
    </section>
  );
}

// --- Narrative 2: proxy traffic ----------------------------------------------

export function ProxyTrafficSection() {
  const { data } = useProjectResource<ProxyTraffic>(api.proxyTraffic);
  const hasCache = !!data && data.cache_series.length > 0;
  const hasLatency = !!data && data.latency_series.some((p) => p.p50_ms !== null);
  return (
    <section className="card cc-section">
      <div className="card-head">
        <h3>Proxy traffic</h3>
        <span className="sub">cache hit-rate, batching, and latency health · last 30 days</span>
      </div>
      <div className="cc-statstrip">
        <Stat label="Cache hit-rate" value={data ? percent(data.hit_rate) : "—"} tone="pos" />
        <Stat label="Cache saved" value={data ? usd(data.cache_saved_usd, 2) : "—"} />
        <Stat label="Batched reqs" value={data ? compact(data.batch_requests) : "—"} />
        <Stat label="p50 latency" value={latency(data?.latency_p50_ms)} />
        <Stat label="p95 latency" value={latency(data?.latency_p95_ms)} />
        <Stat label="p99 latency" value={latency(data?.latency_p99_ms)} />
      </div>
      <div className="cc-chart-2col">
        <div className="cc-chart-cell">
          <div className="cc-chart-title">Cache hit-rate over time</div>
          {hasCache ? <HitRateChart data={data.cache_series} /> : <ChartEmpty label="Awaiting proxy traffic" />}
        </div>
        <div className="cc-chart-cell">
          <div className="cc-chart-title">Latency p50 / p95</div>
          {hasLatency ? <LatencyChart data={data.latency_series} /> : <ChartEmpty label="Latency capture pending" />}
        </div>
      </div>
    </section>
  );
}

// --- Narrative 3: quality guardrails -----------------------------------------

function RouteStatus({ route }: { route: ActiveRoute }) {
  if (route.drifted) return <span className="pill red">drift</span>;
  if (!route.has_signal) return <span className="pill neutral">gathering</span>;
  const saving = Number(route.savings_per_request_usd ?? 0) > 0;
  return <span className={`pill ${saving ? "green" : "amber"}`}>{saving ? "saving" : "watch"}</span>;
}

function RouteSavings({ route }: { route: ActiveRoute }): ReactNode {
  if (!route.has_signal) return <span className="eval-note">gathering signal</span>;
  const ci =
    route.measured_savings_ci_low_usd && route.measured_savings_ci_high_usd
      ? ` ± [${usd(route.measured_savings_ci_low_usd, 2)}, ${usd(route.measured_savings_ci_high_usd, 2)}]`
      : "";
  return (
    <span>
      {usd(route.measured_savings_usd ?? 0, 2)}
      {ci ? <span className="eval-note"> {ci}</span> : null}
    </span>
  );
}

function RouteQuality({ route }: { route: ActiveRoute }): ReactNode {
  if (route.treatment_ok_rate === null || route.control_ok_rate === null) {
    return <span className="eval-note">-</span>;
  }
  return (
    <span>
      {percent(route.treatment_ok_rate)}
      <span className="eval-note"> vs {percent(route.control_ok_rate)} control</span>
    </span>
  );
}

export function QualityGuardrailsSection() {
  const { data: routes } = useProjectResource<ActiveRoute[]>(api.engineRoutes, []);
  return (
    <section className="card cc-section">
      <div className="card-head">
        <h3>Quality guardrails</h3>
        <span className="sub">live A/B holdbacks per model-swap route · measured against the control arm</span>
      </div>
      {!routes || routes.length === 0 ? (
        <div className="card-pad">
          <p className="muted-copy">
            No model-swap routes live yet — running in cache-only mode. A/B holdback quality and measured
            savings appear here once a cheaper-model route is applied.
          </p>
        </div>
      ) : (
        <table className="tbl">
          <thead>
            <tr>
              <th>Route</th>
              <th className="r">Holdback</th>
              <th className="r">Control / Treatment</th>
              <th className="r">Measured savings</th>
              <th className="r">Quality (treat vs control)</th>
              <th className="r">Status</th>
            </tr>
          </thead>
          <tbody>
            {routes.map((route) => (
              <tr key={route.id}>
                <td>
                  <span className="name">
                    {route.incumbent_model} <span className="eval-note">→ {route.candidate_model}</span>
                  </span>
                </td>
                <td className="r">{percent(route.holdback_percent)}</td>
                <td className="r">
                  {compact(route.control_requests)} / {compact(route.treatment_requests)}
                </td>
                <td className="r">
                  <RouteSavings route={route} />
                </td>
                <td className="r">
                  <RouteQuality route={route} />
                </td>
                <td className="r">
                  <RouteStatus route={route} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
