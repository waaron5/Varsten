"use client";

// The Command Center panels mapping to the three narratives: KPI strip, Margin
// engine (hero savings), Proxy traffic (hit-rate + latency), and Quality guardrails
// (A/B holdbacks). Each reads its slice from the provider and shows a fixed-size
// skeleton / honest empty state until data arrives. No fabricated numbers.

import type { ReactNode } from "react";
import { percent } from "@/components/viewPrimitives";
import { compact, usd } from "@/lib/format";
import type { ActiveRoute } from "@/lib/types";
import { useCommandCenter } from "./CommandCenterProvider";
import { CumulativeSavingsChart, HitRateChart, LatencyChart } from "./lazyCharts";
import { KpiTile, Panel, PanelEmpty, PanelSkeleton } from "./primitives";

function latency(ms: number | null | undefined): string {
  return ms === null || ms === undefined ? "—" : `${compact(ms)}ms`;
}

// --- KPI strip (Margin + Proxy headline numbers) ------------------------------

export function KpiStrip() {
  const { commandCenter, proxyTraffic } = useCommandCenter();
  const live = commandCenter.data?.live_savings;
  const pt = proxyTraffic.data;
  return (
    <div className="cc-kpi-strip">
      <KpiTile label="Gross saved (mo)" value={live ? usd(live.saved_month, 0) : "—"} tone="pos" />
      <KpiTile label="Net after fee (mo)" value={live ? usd(live.net_saved_month, 0) : "—"} />
      <KpiTile label="Annual run-rate" value={live ? usd(live.annual_run_rate, 0) : "—"} />
      <KpiTile label="Cache hit-rate" value={pt ? percent(pt.hit_rate) : "—"} tone="pos" />
      <KpiTile label="p95 latency" value={latency(pt?.latency_p95_ms)} />
      <KpiTile label="Trust score" value={live ? percent(live.trust_score) : "—"} />
    </div>
  );
}

// --- Narrative 1: Margin engine (hero) ----------------------------------------

export function MarginEnginePanel() {
  const { savingsTrend } = useCommandCenter();
  const data = savingsTrend.data;
  const hasSeries = !!data && data.points.length > 0;
  return (
    <Panel
      place="cc-pos-margin"
      title="Margin engine"
      sub="cumulative savings vs naive-retail baseline · 30 days"
      right={data ? <span className="cc-panel-stat">{usd(data.total_saved_usd, 0)} saved</span> : null}
    >
      {savingsTrend.loading ? (
        <PanelSkeleton />
      ) : hasSeries ? (
        <CumulativeSavingsChart data={data.points} />
      ) : (
        <PanelEmpty label="No savings recorded yet" />
      )}
    </Panel>
  );
}

// --- Narrative 2: Proxy traffic (hit-rate + latency) --------------------------

export function ProxyHitRatePanel() {
  const { proxyTraffic } = useCommandCenter();
  const data = proxyTraffic.data;
  const hasCache = !!data && data.cache_series.length > 0;
  return (
    <Panel
      place="cc-pos-hitrate"
      title="Cache hit-rate"
      sub="exact-hash served · 30 days"
      right={data ? <span className="cc-panel-stat">{percent(data.hit_rate)}</span> : null}
    >
      {proxyTraffic.loading ? (
        <PanelSkeleton />
      ) : hasCache ? (
        <HitRateChart data={data.cache_series} />
      ) : (
        <PanelEmpty label="Awaiting proxy traffic" />
      )}
    </Panel>
  );
}

export function ProxyLatencyPanel() {
  const { proxyTraffic } = useCommandCenter();
  const data = proxyTraffic.data;
  const hasLatency = !!data && data.latency_series.some((p) => p.p50_ms !== null);
  return (
    <Panel
      place="cc-pos-latency"
      title="Latency health"
      sub="proxy time-to-first-byte · 30 days"
      right={
        data ? (
          <span className="cc-panel-stat cc-lat-stats">
            <span>
              <i style={{ background: "var(--c1)" }} />p50 {latency(data.latency_p50_ms)}
            </span>
            <span>
              <i style={{ background: "var(--c3)" }} />p95 {latency(data.latency_p95_ms)}
            </span>
            <span className="cc-lat-p99">p99 {latency(data.latency_p99_ms)}</span>
          </span>
        ) : null
      }
    >
      {proxyTraffic.loading ? (
        <PanelSkeleton />
      ) : hasLatency ? (
        <LatencyChart data={data.latency_series} />
      ) : (
        <PanelEmpty label="Latency capture pending" />
      )}
    </Panel>
  );
}

// --- Narrative 3: Quality guardrails ------------------------------------------

function RouteStatus({ route }: { route: ActiveRoute }) {
  if (route.drifted) return <span className="pill red">drift</span>;
  if (!route.has_signal) return <span className="pill neutral">gathering</span>;
  const saving = Number(route.savings_per_request_usd ?? 0) > 0;
  return <span className={`pill ${saving ? "green" : "amber"}`}>{saving ? "saving" : "watch"}</span>;
}

function RouteSavings({ route }: { route: ActiveRoute }): ReactNode {
  if (!route.has_signal) return <span className="eval-note">gathering signal</span>;
  return <span>{usd(route.measured_savings_usd ?? 0, 2)}</span>;
}

function RouteQuality({ route }: { route: ActiveRoute }): ReactNode {
  if (route.treatment_ok_rate === null || route.control_ok_rate === null) {
    return <span className="eval-note">-</span>;
  }
  return (
    <span>
      {percent(route.treatment_ok_rate)}
      <span className="eval-note"> vs {percent(route.control_ok_rate)}</span>
    </span>
  );
}

export function QualityGuardrailsPanel() {
  const { routes } = useCommandCenter();
  const list = routes.data ?? [];
  return (
    <Panel
      place="cc-pos-quality"
      title="Quality guardrails"
      sub="live A/B holdbacks per model-swap route"
    >
      {routes.loading ? (
        <PanelSkeleton />
      ) : list.length === 0 ? (
        <PanelEmpty label="No model-swap routes live yet — running cache-only. A/B quality and measured savings appear here once a cheaper-model route is applied." />
      ) : (
        <div className="cc-table-scroll">
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
              {list.map((route) => (
                <tr key={route.id}>
                  <td>
                    <span className="name cc-route-name">
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
        </div>
      )}
    </Panel>
  );
}
