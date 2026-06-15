"use client";

import type { ReactNode } from "react";
import { percent } from "@/components/viewPrimitives";
import { compact, usd } from "@/lib/format";
import type {
  ActiveRoute,
  BreakdownRow,
  CommandCenterLiveSavings,
  MetricsOverview,
  ProofAttributionRow,
  ProxyTraffic,
  Recommendation,
} from "@/lib/types";
import { useCommandCenter } from "./CommandCenterProvider";
import { CacheHitMissChart, CumulativeSavingsChart, LatencyChart } from "./lazyCharts";
import { KpiTile, Panel, PanelEmpty, PanelSkeleton } from "./primitives";

function latency(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  return ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(1)}s`;
}

function money(value: string | number | null | undefined, digits = 0): string {
  return value === null || value === undefined ? "—" : usd(value, digits);
}

function toNum(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined) return null;
  const n = typeof value === "string" ? parseFloat(value) : value;
  return Number.isFinite(n) ? n : null;
}

function pct(value: string | number | null | undefined): string {
  return value === null || value === undefined ? "—" : percent(value);
}

function compactOrDash(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : compact(value);
}

type ExecutiveMetric = {
  label: string;
  value: string;
  sub?: string;
  tone?: "pos" | "neg";
  priority?: "hero";
};

function grossAndFee(live: CommandCenterLiveSavings | undefined): { gross: number | null; fee: number | null } {
  const gross = toNum(live?.saved_month);
  const net = toNum(live?.net_saved_month);
  return { gross, fee: gross === null || net === null ? null : gross - net };
}

function netSavingsSubtitle(live: CommandCenterLiveSavings | undefined): string | undefined {
  const { gross, fee } = grossAndFee(live);
  if (gross === null || fee === null) return undefined;
  return `${usd(gross, 0)} gross minus ${usd(fee, 0)} Varsten fee`;
}

function executiveMetrics(
  live: CommandCenterLiveSavings | undefined,
  overview: MetricsOverview | undefined,
  requestsMonth: number | null | undefined,
): ExecutiveMetric[] {
  return [
    {
      priority: "hero",
      label: "Net savings this month",
      value: money(live?.net_saved_month),
      tone: "pos",
      sub: netSavingsSubtitle(live),
    },
    {
      label: "MTD spend",
      value: money(overview?.spend_month ?? live?.spend_month),
      sub: `Forecast ${money(overview?.monthly_forecast_usd)}`,
    },
    { label: "Annualized run-rate", value: money(live?.annual_run_rate) },
    { label: "Requests this month", value: compactOrDash(requestsMonth) },
  ];
}

function rowName(row: BreakdownRow): string {
  return row.key || "Untagged";
}

function leverName(value: string): string {
  return value
    .replace(/_/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function predicateLabel(route: ActiveRoute): string {
  const predicate = route.predicate;
  if (!predicate) return "Model swap route";
  const parts = [
    predicate.max_prompt_chars ? `prompts under ${compact(predicate.max_prompt_chars)} chars` : null,
    predicate.route_when_tools === false ? "no tool calls" : null,
    predicate.route_when_json_schema === false ? "no JSON schema" : null,
    predicate.max_completion_tokens ? `max ${compact(predicate.max_completion_tokens)} output tokens` : null,
  ].filter(Boolean);
  return parts.length > 0 ? parts.join(" · ") : "Model swap route";
}

function routeMatch(route: ActiveRoute): number | null {
  if (route.treatment_ok_rate === null || route.control_ok_rate === null) return null;
  if (route.control_ok_rate === 0) return 100;
  return Math.min(100, Math.round((route.treatment_ok_rate / route.control_ok_rate) * 100));
}

function RouteStatus({ route }: { route: ActiveRoute }) {
  if (route.drifted) return <span className="pill amber">drift</span>;
  if (!route.has_signal) return <span className="pill neutral">gathering</span>;
  const saving = Number(route.savings_per_request_usd ?? 0) > 0;
  return <span className={`pill ${saving ? "green" : "amber"}`}>{saving ? "saving" : "watch"}</span>;
}

function RouteSavings({ route }: { route: ActiveRoute }): ReactNode {
  if (!route.has_signal) return <span className="eval-note">gathering signal</span>;
  const low = route.measured_savings_ci_low_usd;
  const high = route.measured_savings_ci_high_usd;
  const ci = low !== null && high !== null ? `95% CI ${usd(low, 2)} to ${usd(high, 2)}` : undefined;
  return (
    <span className={ci ? "cc-has-tip" : undefined} title={ci}>
      {usd(route.measured_savings_usd ?? 0, 2)}
    </span>
  );
}

function RouteQuality({ route }: { route: ActiveRoute }): ReactNode {
  const match = routeMatch(route);
  if (match === null) return <span className="eval-note">gathering</span>;
  return (
    <span
      className="cc-quality-match"
      title={`Treatment ${pct(route.treatment_ok_rate)} vs control ${pct(route.control_ok_rate)}`}
    >
      {match}% match
      <i className={route.drifted ? "warn" : "ok"} />
    </span>
  );
}

function HorizontalBar({
  label,
  meta,
  value,
  width,
  tone = "green",
}: {
  label: string;
  meta?: string;
  value: string;
  width: number;
  tone?: "green" | "blue" | "purple" | "amber";
}) {
  return (
    <div className="cc-hbar-row">
      <div className="cc-hbar-head">
        <span>{label}</span>
        <b>{value}</b>
      </div>
      <div className="cc-hbar-track">
        <i className={`cc-hbar-fill ${tone}`} style={{ width: `${Math.max(3, Math.min(100, width))}%` }} />
      </div>
      {meta ? <div className="cc-hbar-meta">{meta}</div> : null}
    </div>
  );
}

export function ExecutiveRow() {
  const { commandCenter, overview } = useCommandCenter();
  const live = commandCenter.data?.live_savings;
  const metrics = executiveMetrics(live, overview.data ?? undefined, commandCenter.data?.requests_month);

  return (
    <div className="cc-kpi-strip">
      {metrics.map((metric) => (
        <KpiTile key={metric.label} {...metric} />
      ))}
    </div>
  );
}

function SavingsLegend() {
  return (
    <span className="cc-legend">
      <span>
        <i className="dash" style={{ borderColor: "var(--text-3)" }} />
        Standard API cost
      </span>
      <span>
        <i style={{ borderColor: "var(--text)" }} />
        Actual cost
      </span>
      <span>
        <i className="fill" style={{ background: "var(--brand)" }} />
        Saved
      </span>
    </span>
  );
}

export function SavingsWedgePanel() {
  const { savingsTrend } = useCommandCenter();
  const data = savingsTrend.data;
  const hasSeries = !!data && data.points.length > 0;
  return (
    <Panel
      place="cc-card-savings"
      title="Savings over baseline"
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

type BudgetForecastState = {
  hasBudget: boolean;
  burnLabel: string;
  burnWidth: number;
  overBudget: boolean;
  varianceText: string;
};

function budgetVarianceText(variance: number | null, overBudget: boolean): string {
  if (variance === null) return "Variance unavailable";
  const amount = money(Math.abs(variance));
  return overBudget ? `${money(variance)} over forecast budget` : `${amount} under forecast budget`;
}

function budgetForecastState(data: MetricsOverview): BudgetForecastState {
  const budget = toNum(data.monthly_budget_usd);
  const burn = toNum(data.budget_burn_percent);
  const variance = toNum(data.budget_variance_usd);
  const hasBudget = budget !== null && burn !== null;
  const overBudget = variance !== null && variance > 0;

  return {
    hasBudget,
    burnLabel: percent(burn),
    burnWidth: hasBudget ? Math.min(100, Math.max(0, burn * 100)) : 0,
    overBudget,
    varianceText: budgetVarianceText(variance, overBudget),
  };
}

function BudgetSummary({ data }: { data: MetricsOverview }) {
  return (
    <>
      <div>
        <span className="cc-small-label">Projected month-end</span>
        <strong>{money(data.monthly_forecast_usd)}</strong>
      </div>
      <div className="cc-budget-grid">
        <span>MTD spend</span>
        <b>{money(data.spend_month)}</b>
        <span>Monthly budget</span>
        <b>{money(data.monthly_budget_usd)}</b>
      </div>
    </>
  );
}

function BudgetMeter({ state }: { state: BudgetForecastState }) {
  if (!state.hasBudget) {
    return <p className="cc-muted">No monthly budget configured. Showing forecast from live usage.</p>;
  }

  return (
    <div className="cc-budget-meter">
      <div className="cc-budget-meter-head">
        <span>Budget burn</span>
        <b className={state.overBudget ? "amber" : undefined}>{state.burnLabel}</b>
      </div>
      <div className="cc-budget-track">
        <i className={state.overBudget ? "amber" : undefined} style={{ width: `${state.burnWidth}%` }} />
      </div>
      <p className={state.overBudget ? "amber" : undefined}>{state.varianceText}</p>
    </div>
  );
}

function BudgetForecastContent({ data }: { data: MetricsOverview }) {
  return (
    <div className="cc-budget">
      <BudgetSummary data={data} />
      <BudgetMeter state={budgetForecastState(data)} />
    </div>
  );
}

export function BudgetForecastPanel() {
  const { overview } = useCommandCenter();
  const data = overview.data;

  return (
    <Panel place="cc-card-budget" title="Budget forecast" sub="Month-to-date spend and projected close">
      {overview.loading ? (
        <PanelSkeleton />
      ) : data ? (
        <BudgetForecastContent data={data} />
      ) : (
        <PanelEmpty label="No spend data yet" />
      )}
    </Panel>
  );
}

export function SavingsMixPanel() {
  const { proofAttribution } = useCommandCenter();
  const rows = proofAttribution.data?.rows ?? [];
  const total = rows.reduce((sum, row) => sum + (toNum(row.gross_savings_usd) ?? 0), 0);

  return (
    <Panel place="cc-card-mix" title="Savings mix" sub="Gross savings by optimization lever">
      {proofAttribution.loading ? (
        <PanelSkeleton />
      ) : rows.length > 0 && total > 0 ? (
        <div className="cc-hbar-list">
          {rows.slice(0, 5).map((row: ProofAttributionRow) => {
            const gross = toNum(row.gross_savings_usd) ?? 0;
            return (
              <HorizontalBar
                key={`${row.lever}-${row.measurement_method}`}
                label={leverName(row.lever)}
                meta={`${row.actions} actions · ${row.measurement_method}`}
                value={money(gross)}
                width={(gross / total) * 100}
                tone="purple"
              />
            );
          })}
        </div>
      ) : (
        <PanelEmpty label="Applied engine actions will populate lever-level proof" />
      )}
    </Panel>
  );
}

export function TopSpendDriversPanel() {
  const { spendDrivers } = useCommandCenter();
  const rows = spendDrivers.data?.rows ?? [];
  const maxSpend = rows.reduce((max, row) => Math.max(max, toNum(row.spend) ?? 0), 0);

  return (
    <Panel place="cc-card-drivers" title="Top spend drivers" sub="Model spend over the last 30 days">
      {spendDrivers.loading ? (
        <PanelSkeleton />
      ) : rows.length > 0 && maxSpend > 0 ? (
        <div className="cc-hbar-list">
          {rows.map((row: BreakdownRow) => {
            const spend = toNum(row.spend) ?? 0;
            return (
              <HorizontalBar
                key={rowName(row)}
                label={rowName(row)}
                meta={`${compact(row.requests)} requests`}
                value={money(spend)}
                width={(spend / maxSpend) * 100}
                tone="blue"
              />
            );
          })}
        </div>
      ) : (
        <PanelEmpty label="No model spend recorded yet" />
      )}
    </Panel>
  );
}

export function TopOpportunitiesPanel() {
  const { commandCenter } = useCommandCenter();
  const data = commandCenter.data;
  const recommendations = data?.top_waste_now
    ? [data.top_waste_now, ...(data.decision_queue ?? []).filter((rec) => rec.id !== data.top_waste_now?.id)]
    : (data?.decision_queue ?? []);

  return (
    <Panel place="cc-card-opportunities" title="Top opportunities" sub="Open recommendations ranked by savings">
      {commandCenter.loading ? (
        <PanelSkeleton />
      ) : recommendations.length > 0 ? (
        <div className="cc-opportunity-list">
          {recommendations.slice(0, 4).map((rec: Recommendation) => (
            <div className="cc-opportunity-row" key={rec.id}>
              <div>
                <b>{rec.title}</b>
                <span>{rec.measurement_method} · {rec.confidence} confidence · {rec.risk_level} risk</span>
              </div>
              <strong>{money(rec.estimated_monthly_savings_usd)}</strong>
            </div>
          ))}
        </div>
      ) : (
        <PanelEmpty label="No open savings recommendations" />
      )}
    </Panel>
  );
}

export function ProxyEfficiencyPanel() {
  const { proxyTraffic } = useCommandCenter();
  const data = proxyTraffic.data;
  const hasCache = !!data && data.cache_series.length > 0;

  return (
    <Panel
      place="cc-card-cache"
      title="Proxy efficiency"
      sub="Cache hits vs misses · 30 days"
      right={data ? <span className="cc-panel-stat">{pct(data.hit_rate)}</span> : null}
    >
      {proxyTraffic.loading ? (
        <PanelSkeleton />
      ) : hasCache ? (
        <div className="cc-proxy-panel">
          <div className="cc-proxy-stats">
            <div>
              <span>Cache savings</span>
              <b>{money(data.cache_saved_usd)}</b>
            </div>
            <div>
              <span>Requests</span>
              <b>{compact(data.requests)}</b>
            </div>
            <div>
              <span>Batch saved</span>
              <b>{money(data.batch_saved_usd)}</b>
            </div>
          </div>
          <div className="cc-chart-tall">
            <CacheHitMissChart data={data.cache_series} />
          </div>
        </div>
      ) : (
        <PanelEmpty label="Awaiting proxy traffic" />
      )}
    </Panel>
  );
}

type SafetyStatusTone = "amber" | "green" | "neutral";

type SafetySummaryState = {
  avgMatch: string;
  statusLabel: string;
  statusTone: SafetyStatusTone;
  hasLatency: boolean;
};

function averageQualityMatch(routes: ActiveRoute[]): string {
  const measuredMatches = routes.map(routeMatch).filter((value): value is number => value !== null);
  if (measuredMatches.length === 0) return "—";
  const total = measuredMatches.reduce((sum, value) => sum + value, 0);
  return `${Math.round(total / measuredMatches.length)}%`;
}

function routeStatus(routes: ActiveRoute[]): Pick<SafetySummaryState, "statusLabel" | "statusTone"> {
  const driftCount = routes.filter((route) => route.drifted).length;
  if (driftCount > 0) return { statusLabel: `${driftCount} drift warnings`, statusTone: "amber" };
  if (routes.length > 0) return { statusLabel: "No drift detected", statusTone: "green" };
  return { statusLabel: "No active routes", statusTone: "neutral" };
}

function latencySeriesReady(traffic: ProxyTraffic | null): boolean {
  return !!traffic && traffic.latency_series.some((point) => point.p95_ms !== null);
}

function safetySummaryState(traffic: ProxyTraffic | null, routes: ActiveRoute[]): SafetySummaryState {
  return {
    ...routeStatus(routes),
    avgMatch: averageQualityMatch(routes),
    hasLatency: latencySeriesReady(traffic),
  };
}

function SafetyMetric({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <span>{label}</span>
      <b>{children}</b>
    </div>
  );
}

function SafetyLatencyChart({ traffic, hasLatency }: { traffic: ProxyTraffic | null; hasLatency: boolean }) {
  return (
    <div className="cc-safety-chart">
      {hasLatency && traffic ? <LatencyChart data={traffic.latency_series} /> : <PanelEmpty label="Latency capture pending" />}
    </div>
  );
}

function SafetySummaryContent({ traffic, routes }: { traffic: ProxyTraffic | null; routes: ActiveRoute[] }) {
  const state = safetySummaryState(traffic, routes);

  return (
    <div className="cc-safety-grid">
      <SafetyMetric label="p95 latency">{latency(traffic?.latency_p95_ms)}</SafetyMetric>
      <SafetyMetric label="p99 tail">{latency(traffic?.latency_p99_ms)}</SafetyMetric>
      <SafetyMetric label="Avg quality match">{state.avgMatch}</SafetyMetric>
      <SafetyMetric label="Route status">
        <span className={`pill ${state.statusTone}`}>{state.statusLabel}</span>
      </SafetyMetric>
      <SafetyLatencyChart traffic={traffic} hasLatency={state.hasLatency} />
    </div>
  );
}

export function SafetySummaryPanel() {
  const { proxyTraffic, routes } = useCommandCenter();
  const traffic = proxyTraffic.data;
  const routeList = routes.data ?? [];

  return (
    <Panel place="cc-card-safety" title="Safety summary" sub="Latency and A/B quality guardrails">
      {proxyTraffic.loading || routes.loading ? (
        <PanelSkeleton />
      ) : (
        <SafetySummaryContent traffic={traffic} routes={routeList} />
      )}
    </Panel>
  );
}

export function GuardrailRoutesPanel() {
  const { routes } = useCommandCenter();
  const list = routes.data ?? [];
  return (
    <Panel place="cc-card-routes" title="Guardrail routes" sub="Live A/B holdbacks for model-swap routes">
      {routes.loading ? (
        <PanelSkeleton />
      ) : list.length === 0 ? (
        <PanelEmpty label="No model-swap routes live yet. Quality and measured savings appear here once a cheaper-model route is applied." />
      ) : (
        <div className="cc-route-list">
          {list.map((route) => (
            <div className="cc-route-row" key={route.id}>
              <div className="cc-route-main">
                <b>{route.incumbent_model} <span>to {route.candidate_model}</span></b>
                <small>{route.source_title || predicateLabel(route)}</small>
              </div>
              <div>
                <span>Holdback</span>
                <b>{pct(route.holdback_percent)}</b>
              </div>
              <div>
                <span>Traffic</span>
                <b>{compact(route.control_requests)} / {compact(route.treatment_requests)}</b>
              </div>
              <div>
                <span>Measured</span>
                <b><RouteSavings route={route} /></b>
              </div>
              <div>
                <span>Quality</span>
                <b><RouteQuality route={route} /></b>
              </div>
              <div>
                <span>Status</span>
                <b><RouteStatus route={route} /></b>
              </div>
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}
