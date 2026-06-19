"use client";

import { useState } from "react";
import Link from "next/link";
import { useEntitlements } from "@/components/entitlements";
import { compact, usd } from "@/lib/format";
import { NetSavingsTrendChart, SpendDonutChart } from "./lazyCharts";
import type { DonutRow } from "./charts";
import { PanelEmpty, PanelSkeleton } from "./primitives";
import { useDashboard } from "./DashboardProvider";
import { buildDashboardViewModel } from "./viewModel";
import type { DashboardMetric, DashboardViewModel } from "./viewModel";
import type { Breakdown, BreakdownRow, ProofDataQuality, ProofSavings, SavingsTrend } from "@/lib/types";

function money(value: number | null, digits = 0): string {
  return value === null ? "—" : usd(value, digits);
}

function precisePercent(value: number | null, digits = 1): string {
  if (value === null || !Number.isFinite(value)) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

function metricValue(metric: DashboardMetric): string {
  if (metric.value === null || metric.value === undefined) return "—";
  if (metric.kind === "money") return typeof metric.value === "number" ? usd(metric.value, 0) : metric.value;
  if (metric.kind === "percent") return typeof metric.value === "number" ? precisePercent(metric.value) : metric.value;
  if (metric.kind === "compact") return typeof metric.value === "number" ? compact(metric.value) : metric.value;
  return String(metric.value);
}


function num(value: string | number | null | undefined): number {
  if (value === null || value === undefined) return 0;
  const parsed = typeof value === "string" ? parseFloat(value) : value;
  return Number.isFinite(parsed) ? parsed : 0;
}

function nullableNum(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined) return null;
  const parsed = typeof value === "string" ? parseFloat(value) : value;
  return Number.isFinite(parsed) ? parsed : null;
}

function totalSaved(trend: SavingsTrend): number | null {
  if (trend.points.length === 0) return null;
  return nullableNum(trend.total_saved_usd) ?? trend.points.reduce((sum, point) => sum + num(point.saved_usd), 0);
}

function totalSpend(trend: SavingsTrend): number | null {
  if (trend.points.length === 0) return null;
  return nullableNum(trend.total_optimized_usd) ?? trend.points.reduce((sum, point) => sum + num(point.optimized_usd), 0);
}

function effectiveTrendRate(trend: SavingsTrend): number | null {
  const direct = nullableNum(trend.effective_savings_rate);
  if (direct !== null) return direct;
  const saved = nullableNum(trend.total_saved_usd) ?? trend.points.reduce((sum, point) => sum + num(point.saved_usd), 0);
  const baseline = nullableNum(trend.total_baseline_usd) ?? trend.points.reduce((sum, point) => sum + num(point.baseline_usd), 0);
  return baseline > 0 ? saved / baseline : null;
}

function averageDailyValue(trend: SavingsTrend, total: number | null): number | null {
  return total !== null && trend.points.length > 0 ? total / trend.points.length : null;
}

type DashboardResources = ReturnType<typeof useDashboard>;
type DashboardResource = { data: unknown | null; loading: boolean; error: string | null };

function requiredResources(resources: DashboardResources): DashboardResource[] {
  return [
    resources.dashboard,
    resources.engineLevers,
    resources.overview,
    resources.proofDataQuality,
    resources.proofSavings,
    resources.savingsTrend,
  ];
}

function dashboardReadState(resources: DashboardResources, entitlementsLoading: boolean) {
  const required = requiredResources(resources);
  const loading = entitlementsLoading || (required.some((resource) => resource.loading) && required.some((resource) => !resource.data));
  const error = required.find((resource) => resource.error)?.error ?? null;
  const ready = Boolean(resources.dashboard.data && resources.overview.data && resources.proofSavings.data && resources.savingsTrend.data);
  return { error, loading, ready };
}

function DashboardLoading() {
  return (
    <div className="dashboard-view dash-overview">
      <div className="dash-metric-strip">
        <PanelSkeleton />
        <PanelSkeleton />
        <PanelSkeleton />
        <PanelSkeleton />
      </div>
      <div className="dash-main-grid">
        <PanelSkeleton />
        <PanelSkeleton />
      </div>
      <div className="dash-bottom-grid">
        <PanelSkeleton />
        <PanelSkeleton />
      </div>
    </div>
  );
}

function DashboardError({ message }: { message: string }) {
  return (
    <div className="dashboard-view dash-overview">
      <section className="dash-card">
        <PanelEmpty label={message} />
      </section>
    </div>
  );
}

function MetricCard({ metric }: { metric: DashboardMetric }) {
  const className = metric.tone === "brand" ? "dash-metric primary" : "dash-metric";
  return (
    <section className={className}>
      <p>
        <span aria-hidden="true" />
        {metric.label}
      </p>
      <strong>{metricValue(metric)}</strong>
    </section>
  );
}

function TrendStats({ trend }: { trend: SavingsTrend }) {
  const saved = totalSaved(trend);
  const spend = totalSpend(trend);
  const avgDailySaved = averageDailyValue(trend, saved);
  const avgDailySpend = averageDailyValue(trend, spend);
  const rate = effectiveTrendRate(trend);

  return (
    <div className="dash-trend-stats">
      <div>
        <span>Avg daily spend</span>
        <b>{money(avgDailySpend)}</b>
      </div>
      <div>
        <span>Avg daily saved</span>
        <b>{money(avgDailySaved)}</b>
      </div>
      <div>
        <span>Effective savings rate</span>
        <b>{precisePercent(rate)}</b>
      </div>
    </div>
  );
}

function SavingsTrendPanel({ trend }: { trend: SavingsTrend }) {
  const points = trend.points;
  const hasTrend = points.length > 0;
  return (
    <section className="dash-card dash-trend-card">
      <div className="dash-card-head">
        <div>
          <h2>Savings</h2>
        </div>
        <div className="dash-chart-legend" aria-label="Chart legend">
          <span><i className="spend" />Actual spend</span>
          <span><i className="savings" />Savings</span>
        </div>
      </div>
      {hasTrend ? (
        <>
          <div className="dash-trend-chart">
            <NetSavingsTrendChart points={points} />
          </div>
          <TrendStats trend={trend} />
        </>
      ) : (
        <PanelEmpty label="Send traffic through Varsten to build your savings trend." />
      )}
    </section>
  );
}

const DONUT_PALETTE = ["#0e9e6e", "#58b28a", "#85c5a6", "#afd8c3", "#d7ece1", "#ebf5f0"];

function driverLabel(value: string | null): string {
  if (!value || value.trim() === "" || value.toLowerCase() === "unknown") return "Unknown";
  return value;
}

function buildDonutRows(rows: BreakdownRow[]): { donut: DonutRow[]; total: number } {
  const top = rows.slice(0, 5);
  const total = top.reduce((s, r) => s + (parseFloat(r.spend) || 0), 0);
  const donut = top.map((r, i) => ({
    name: driverLabel(r.key),
    spend: parseFloat(r.spend) || 0,
    color: DONUT_PALETTE[i] ?? DONUT_PALETTE[DONUT_PALETTE.length - 1],
  }));
  return { donut, total };
}

function TopSpendDriversPanel({
  teamData, teamLoading, teamError,
  featureData, featureLoading, featureError,
}: {
  teamData: Breakdown | null;
  teamLoading: boolean;
  teamError: string | null;
  featureData: Breakdown | null;
  featureLoading: boolean;
  featureError: string | null;
}) {
  const [tab, setTab] = useState<"team" | "feature">("team");
  const activeData = tab === "team" ? teamData : featureData;
  const activeLoading = tab === "team" ? teamLoading : featureLoading;
  const activeError = tab === "team" ? teamError : featureError;
  const emptyLabel = tab === "team"
    ? "Team spend appears here once usage includes team metadata."
    : "Feature spend appears here once usage includes feature metadata.";

  const { donut, total } = buildDonutRows(activeData?.rows ?? []);

  return (
    <section className="dash-card dash-drivers-card">
      <div className="dash-card-head">
        <div>
          <h2>Spend drivers</h2>
        </div>
        <Link href="/analysis/spend" className="dash-head-link">Open Analysis →</Link>
      </div>
      <div className="dash-drivers-tabs" role="tablist">
        <button role="tab" aria-selected={tab === "team"} className={`dash-drivers-tab${tab === "team" ? " active" : ""}`} onClick={() => setTab("team")}>Team</button>
        <button role="tab" aria-selected={tab === "feature"} className={`dash-drivers-tab${tab === "feature" ? " active" : ""}`} onClick={() => setTab("feature")}>Feature</button>
      </div>
      {activeLoading && !activeData ? (
        <div className="dash-drivers-loading"><PanelSkeleton /></div>
      ) : activeError ? (
        <PanelEmpty label={activeError} />
      ) : donut.length ? (
        <div className="dash-drivers-body">
          <div className="dash-donut-wrap">
            <SpendDonutChart rows={donut} />
            <div className="dash-donut-center">
              <b>{money(total)}</b>
              <span>total spend</span>
            </div>
          </div>
          <div className="dash-drivers-legend">
            {donut.map((row) => (
              <div className="dash-driver-legend-row" key={row.name}>
                <span className="dash-driver-swatch" style={{ background: row.color }} />
                <span className="dash-driver-legend-name">{row.name}</span>
                <div className="dash-driver-legend-bar">
                  <div className="dash-driver-legend-bar-fill" style={{ width: `${total > 0 ? Math.round((row.spend / total) * 100) : 0}%`, background: row.color }} />
                </div>
                <span className="dash-driver-legend-amount">{money(row.spend)}</span>
                <span className="dash-driver-legend-pct">{precisePercent(total > 0 ? row.spend / total : null, 0)}</span>
              </div>
            ))}
            <div className="dash-drivers-total">
              <span className="dash-drivers-total-label">Total</span>
              <span className="dash-drivers-total-amount">{money(total)}</span>
            </div>
          </div>
        </div>
      ) : (
        <PanelEmpty label={emptyLabel} />
      )}
    </section>
  );
}

function ActiveLeversPanel({ model }: { model: DashboardViewModel }) {
  return (
    <section className="dash-card dash-levers-card">
      <div className="dash-card-head">
        <div className="dash-levers-heading">
          <h2>Savings by lever</h2>
          <span className="dash-levers-count">{model.leversRunning} active</span>
        </div>
        <Link href="/engine/levers" className="dash-head-link">Open Engine →</Link>
      </div>
      {model.levers.length ? (
        <div className="dash-levers-list">
          {model.levers.map((lever) => (
            <div className={`dash-lever-item${lever.enabled ? "" : " dim"}`} key={lever.lever}>
              <div className="dash-lever-item-head">
                <div className="dash-lever-item-name">
                  <b>{lever.lever}</b>
                  <span className={`dash-lever-badge ${lever.enabled ? "active" : "off"}`}>
                    {lever.status}
                  </span>
                </div>
                <strong>{money(lever.impactValue)}</strong>
              </div>
              <div className="dash-lever-item-bar">
                <span><i style={{ width: `${Math.round((lever.share ?? 0) * 100)}%` }} /></span>
                <em>{lever.share === null ? "0%" : precisePercent(lever.share, 0)}</em>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <PanelEmpty label="Lever status appears here once Engine configuration loads." />
      )}
    </section>
  );
}

function toNum(v: string | number | null | undefined): number | null {
  if (v === null || v === undefined) return null;
  const n = typeof v === "string" ? parseFloat(v) : v;
  return Number.isFinite(n) ? n : null;
}

function posNum(v: string | number | null | undefined): number | null {
  const n = toNum(v);
  return n !== null && n > 0 ? n : null;
}

function proofScore(dq: ProofDataQuality | null): number | null {
  return toNum(dq?.trust_score);
}

function proofConfidenceLabel(score: number | null): string {
  if (score === null || score < 0.6) return "Building confidence";
  if (score >= 0.8) return "High confidence";
  return "Medium confidence";
}

function proofConfidenceNote(score: number | null): string {
  if (score === null || score < 0.6) return "Increase pricing coverage and metadata tagging to improve your trust score.";
  if (score >= 0.8) return "Numbers are suitable for board-level reporting and finance decisions.";
  return "Suitable for internal reporting. Improve pricing coverage and metadata tagging for board-ready numbers.";
}

function proofPricingCoverage(dq: ProofDataQuality | null): number | null {
  if (!dq) return null;
  const total = dq.priced_event_count + dq.unpriced_event_count;
  return total > 0 ? dq.priced_event_count / total : null;
}

function proofPricingBadge(cov: number | null): { text: string; cls: string } {
  if (cov === null) return { text: "Unchecked", cls: "gray" };
  if (cov >= 0.95) return { text: "Catalog-verified", cls: "green" };
  if (cov >= 0.8) return { text: "Mostly verified", cls: "green" };
  return { text: "Partial", cls: "amber" };
}

function proofAttribution(dq: ProofDataQuality | null): number | null {
  if (!dq?.metadata_quality) return null;
  const mq = dq.metadata_quality;
  const team = Math.max(0, Math.min(1, toNum(mq.team) ?? 0));
  const feature = Math.max(0, Math.min(1, toNum(mq.feature) ?? 0));
  return 1 - (1 - team) * (1 - feature);
}

function proofAttributionBadge(rate: number | null): { text: string; cls: string } {
  if (rate === null) return { text: "Unknown", cls: "gray" };
  if (rate >= 0.9) return { text: "Full", cls: "green" };
  if (rate >= 0.5) return { text: "Partial", cls: "amber" };
  return { text: "Low", cls: "amber" };
}

function proofMeasurementMethod(ps: ProofSavings | null): { label: string; hasDirectLedger: boolean; hasABHoldback: boolean } {
  const hasAB = ps?.verified?.holdback_has_signal ?? false;
  const hasDirect = posNum(ps?.verified?.direct_measured_usd) !== null || posNum(ps?.gross_savings_usd) !== null;
  const label = hasAB && hasDirect ? "Direct + A/B" : hasAB ? "A/B holdback" : hasDirect ? "Direct ledger" : "Not yet active";
  return { label, hasDirectLedger: hasDirect, hasABHoldback: hasAB };
}

function ProofTrustPanel({
  dataQuality,
  proofSavings,
}: {
  dataQuality: ProofDataQuality | null;
  proofSavings: ProofSavings | null;
}) {
  const score = proofScore(dataQuality);
  const scoreDisplay = score === null ? "—" : String(Math.round(score * 100));

  const pricCov = proofPricingCoverage(dataQuality);
  const pricBadge = proofPricingBadge(pricCov);
  const pricValCls = pricCov !== null && pricCov >= 0.9 ? "green" : "amber";

  const attrRate = proofAttribution(dataQuality);
  const attrBadge = proofAttributionBadge(attrRate);
  const attrValCls = attrRate !== null && attrRate >= 0.9 ? "green" : "amber";

  const { label: methodLabel, hasDirectLedger, hasABHoldback } = proofMeasurementMethod(proofSavings);
  const hasAnyMethod = hasDirectLedger || hasABHoldback;

  return (
    <section className="dash-card dash-proof-card">
      <div className="dash-card-head">
        <h2>Proof & trust</h2>
        <Link href="/proof/savings" className="dash-head-link">Open Proof →</Link>
      </div>

      <div className="dash-proof-hero">
        <div>
          <p className="dash-proof-hero-label">✓ {proofConfidenceLabel(score)}</p>
          <p className="dash-proof-hero-note">{proofConfidenceNote(score)}</p>
        </div>
        <div className="dash-proof-hero-score">
          <b>{scoreDisplay}</b>
          <span>/ 100</span>
        </div>
      </div>

      <div className="dash-proof-metrics">
        <div className="dash-proof-metric">
          <div className="dash-proof-metric-top">
            <div className="dash-proof-metric-name">
              <b>Pricing coverage</b>
              <span className={`dash-proof-badge ${pricBadge.cls}`}>{pricBadge.text}</span>
            </div>
            <span className={`dash-proof-metric-val ${pricValCls}`}>{pricCov === null ? "—" : precisePercent(pricCov, 0)}</span>
          </div>
          <p className="dash-proof-metric-desc">Spend priced from official catalog or org override — not unknown or self-reported</p>
        </div>

        <div className="dash-proof-metric">
          <div className="dash-proof-metric-top">
            <div className="dash-proof-metric-name">
              <b>Spend attribution</b>
              <span className={`dash-proof-badge ${attrBadge.cls}`}>{attrBadge.text}</span>
            </div>
            <span className={`dash-proof-metric-val ${attrValCls}`}>{attrRate === null ? "—" : precisePercent(attrRate, 0)}</span>
          </div>
          <p className="dash-proof-metric-desc">% of requests tagged with team, feature, or use case — untagged spend cannot be assigned ownership</p>
        </div>

        <div className="dash-proof-metric">
          <div className="dash-proof-metric-top">
            <div className="dash-proof-metric-name">
              <b>Measurement method</b>
              {hasAnyMethod && <span className="dash-proof-badge green">Active</span>}
            </div>
            <span className="dash-proof-metric-val">{methodLabel}</span>
          </div>
          <p className="dash-proof-metric-desc">How savings are recorded and validated against real outcomes</p>
          {(hasDirectLedger || hasABHoldback) && (
            <div className="dash-proof-pills">
              {hasDirectLedger && <span className="dash-proof-pill">✓ Direct ledger</span>}
              {hasABHoldback && <span className="dash-proof-pill">✓ A/B holdback</span>}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

export function SavingsDashboard() {
  const resources = useDashboard();
  const { dashboard, engineLevers, overview, proofDataQuality, proofSavings, savingsTrend, spendDrivers, spendDriversByFeature } = resources;
  const { isPerformance, loading: entitlementsLoading } = useEntitlements();
  const readState = dashboardReadState(resources, entitlementsLoading);

  if (readState.loading) return <DashboardLoading />;
  if (readState.error) return <DashboardError message={readState.error} />;
  if (!readState.ready || !dashboard.data || !overview.data || !proofSavings.data || !savingsTrend.data) {
    return <DashboardError message="Dashboard data is not available yet." />;
  }

  const model = buildDashboardViewModel({
    dashboard: dashboard.data,
    dataQuality: proofDataQuality.data,
    isPerformance,
    levers: engineLevers.data,
    overview: overview.data,
    proofSavings: proofSavings.data,
  });

  return (
    <div className="dashboard-view dash-overview">
      <div className="dash-metric-strip">
        {model.accountingMetrics.map((metric) => (
          <MetricCard key={metric.label} metric={metric} />
        ))}
      </div>
      <div className="dash-main-grid">
        <SavingsTrendPanel trend={savingsTrend.data} />
        <ActiveLeversPanel model={model} />
      </div>
      <div className="dash-bottom-grid">
        <TopSpendDriversPanel
          teamData={spendDrivers.data} teamLoading={spendDrivers.loading} teamError={spendDrivers.error}
          featureData={spendDriversByFeature.data} featureLoading={spendDriversByFeature.loading} featureError={spendDriversByFeature.error}
        />
        <ProofTrustPanel dataQuality={proofDataQuality.data} proofSavings={proofSavings.data} />
      </div>
    </div>
  );
}
