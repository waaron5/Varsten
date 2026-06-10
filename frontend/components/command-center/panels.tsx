"use client";

// The Command Center panels mapping to the three narratives: KPI strip, Margin
// engine (hero savings), Proxy traffic (hit-rate + latency), and Quality guardrails
// (A/B holdbacks). Each reads its slice from the provider and shows a fixed-size
// skeleton / honest empty state until data arrives. No fabricated numbers.

import type { ReactNode } from "react";
import { percent } from "@/components/viewPrimitives";
import { compact, usd } from "@/lib/format";
import type { ActiveRoute, CommandCenterLiveSavings, ProxyTraffic } from "@/lib/types";
import { useCommandCenter } from "./CommandCenterProvider";
import { CumulativeSavingsChart, HitRateChart, LatencyChart, Sparkline } from "./lazyCharts";
import { KpiTile, Panel, PanelEmpty, PanelSkeleton } from "./primitives";

// Latency in human units: raw ms under a second, seconds with one decimal above
// it. Never `${compact(ms)}ms`, which renders 1100 as the unreadable "1.1Kms".
function latency(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  return ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(1)}s`;
}

// A money value renders "—" when null/undefined (no data behind it), never $0.
function money(value: string | number | null | undefined): string {
  return value === null || value === undefined ? "—" : usd(value, 0);
}

function toNum(value: string | number | null): number | null {
  if (value === null) return null;
  const n = typeof value === "string" ? parseFloat(value) : value;
  return Number.isFinite(n) ? n : null;
}

// A sparkline is honest only when there is a real series behind it (>1 point).
// Otherwise the tile is just its number.
function spark(series: (number | null)[], color: string): ReactNode {
  return series.filter((v) => v !== null).length > 1 ? <Sparkline data={series} color={color} /> : undefined;
}

// --- KPI strip (Margin + Proxy headline numbers) ------------------------------

// The hero metric: net savings after the Varsten fee. The gross figure and the fee
// subtraction live in the subtitle so finance sees the full equation without a
// second tile competing for the eye.
function NetSavedTile({ live }: { live: CommandCenterLiveSavings | undefined }) {
  const gross = toNum(live?.saved_month ?? null);
  const net = toNum(live?.net_saved_month ?? null);
  const fee = gross !== null && net !== null ? gross - net : null;
  const sub =
    gross !== null && fee !== null ? `${usd(gross, 0)} gross − ${usd(fee, 0)} Varsten fee` : undefined;
  return <KpiTile label="Net savings (30d)" value={money(live?.net_saved_month)} tone="pos" sub={sub} />;
}

function AnnualRunRateTile({ live }: { live: CommandCenterLiveSavings | undefined }) {
  return <KpiTile label="Annual run-rate" value={money(live?.annual_run_rate)} />;
}

function CacheHitRateTile({ proxyTraffic }: { proxyTraffic: ProxyTraffic | undefined }) {
  const hitSpark = (proxyTraffic?.cache_series ?? []).map((p) => toNum(p.hit_rate));
  return (
    <KpiTile
      label="Cache hit-rate"
      value={percent(proxyTraffic?.hit_rate)}
      tone="pos"
      spark={spark(hitSpark, "var(--c2)")}
    />
  );
}

function P95LatencyTile({ proxyTraffic }: { proxyTraffic: ProxyTraffic | undefined }) {
  const p95Spark = (proxyTraffic?.latency_series ?? []).map((p) => p.p95_ms);
  return (
    <KpiTile
      label="p95 latency"
      value={latency(proxyTraffic?.latency_p95_ms)}
      spark={spark(p95Spark, "var(--c3)")}
    />
  );
}

export function KpiStrip() {
  const { commandCenter, proxyTraffic } = useCommandCenter();
  const live = commandCenter.data?.live_savings;
  const pt = proxyTraffic.data ?? undefined;
  // Four core metrics: the hero (net savings) plus run-rate, cache hit-rate, and
  // p95 latency. Every tile resolves to "—" when its field is null: money() for
  // the savings figures, percent()/latency() already return "—" for null/undefined.
  return (
    <div className="cc-kpi-strip">
      <NetSavedTile live={live} />
      <AnnualRunRateTile live={live} />
      <CacheHitRateTile proxyTraffic={pt} />
      <P95LatencyTile proxyTraffic={pt} />
    </div>
  );
}

// --- Narrative 1: Margin engine (hero) ----------------------------------------

// The legend the wedge chart needs: a key for the dashed top line (what they would
// have paid), the solid bottom line (what they actually pay), and the shaded gap.
function SavingsLegend() {
  return (
    <span className="cc-legend">
      <span>
        <i className="dash" style={{ borderColor: "var(--text-3)" }} />
        Standard API cost
      </span>
      <span>
        <i style={{ borderColor: "var(--text)" }} />
        Your cost with Varsten
      </span>
      <span>
        <i className="fill" style={{ background: "var(--brand)" }} />
        Money saved
      </span>
    </span>
  );
}

export function MarginEnginePanel() {
  const { savingsTrend } = useCommandCenter();
  const data = savingsTrend.data;
  const hasSeries = !!data && data.points.length > 0;
  return (
    <Panel
      place="cc-pos-margin"
      title="Cumulative savings"
      sub="Actual cost vs unoptimized API cost · 30 days"
      right={hasSeries ? <SavingsLegend /> : null}
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
      right={hasCache && data ? <span className="cc-panel-stat">{percent(data.hit_rate)}</span> : null}
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
  const hasLatency = !!data && data.latency_series.some((p) => p.p95_ms !== null);
  return (
    <Panel
      place="cc-pos-latency"
      title="Latency health"
      sub="proxy time-to-first-byte · 30 days"
      right={
        hasLatency && data ? (
          <span className="cc-panel-stat cc-lat-stats">
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

// Measured A/B savings, with the 95% confidence interval tucked into a hover
// tooltip rather than its own column. The CI is the statistical proof the saving
// is real, but it is a deep-dive detail, not a headline number.
function RouteSavings({ route }: { route: ActiveRoute }): ReactNode {
  if (!route.has_signal) return <span className="eval-note">gathering signal</span>;
  const low = route.measured_savings_ci_low_usd;
  const high = route.measured_savings_ci_high_usd;
  const ci = low !== null && high !== null ? `95% CI ${usd(low, 2)} – ${usd(high, 2)}` : undefined;
  return (
    <span className={ci ? "cc-has-tip" : undefined} title={ci}>
      {usd(route.measured_savings_usd ?? 0, 2)}
    </span>
  );
}

// Quality as a single actionable read: the cheaper arm's pass rate relative to the
// incumbent, plus a green/red dot saying whether the swap is safe. "99% match · ●"
// beats "96% vs 97%", which makes the reader do the division. `drifted` is the
// authoritative guardrail signal, so it drives the dot, not an arbitrary cutoff.
function RouteQuality({ route }: { route: ActiveRoute }): ReactNode {
  if (route.treatment_ok_rate === null || route.control_ok_rate === null) {
    return <span className="eval-note">gathering</span>;
  }
  const ratio = route.control_ok_rate === 0 ? 1 : route.treatment_ok_rate / route.control_ok_rate;
  const match = Math.min(100, Math.round(ratio * 100));
  const safe = !route.drifted;
  return (
    <span
      className="cc-quality-match"
      title={`Treatment ${percent(route.treatment_ok_rate)} vs control ${percent(route.control_ok_rate)}`}
    >
      {match}% match
      <i className={safe ? "ok" : "bad"} />
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
                <th>Model swap</th>
                <th className="r">Holdback</th>
                <th className="r">Traffic (held / routed)</th>
                <th className="r">Measured savings</th>
                <th className="r">Quality match</th>
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
