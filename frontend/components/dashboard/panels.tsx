"use client";

// The Dashboard renders one consolidated snapshot (GET /dashboard/snapshot). The
// backend reconciles every panel to a single window, fee, and savings source, so
// these components are thin: they format and lay out, they do not re-derive money.
// This layout is the canonical design reference for future pages. The period
// toggle + Export live in the top navbar (see DashboardTopbarControls).

import { useEffect, useState, useSyncExternalStore } from "react";
import type { ReactNode } from "react";
import Link from "next/link";
import { usd } from "@/lib/format";
import { useEntitlements } from "@/components/entitlements";
import { useTimedPolling } from "@/components/useTimedPolling";
import { DOCS_HREF } from "@/lib/integrationSnippets";
import { NetSavingsTrendChart } from "./lazyCharts";
import { PanelEmpty, PanelSkeleton } from "./primitives";
import { useDashboard } from "./DashboardProvider";
import type {
  DashboardDriverRow,
  DashboardDrivers,
  DashboardKpi,
  DashboardLever,
  DashboardPeriod,
  DashboardProofTrust,
  FallbackCoverageRow,
  SavingsTrendBucket,
  TrendStats,
} from "@/lib/types";

// Spend/allocation blue ramp (darkest = largest).
// The last (lightest) is used for the untagged bucket.
const DRIVER_PALETTE = ["#2B4A5A", "#3B6275", "#4F7A90", "#6E96AA", "#B8CED8", "#E9F1F5"];
const DASHBOARD_PREVIEW_STORAGE_KEY = "varsten:dashboard-preview";

function num(value: string | null | undefined): number | null {
  if (value === null || value === undefined) return null;
  const parsed = parseFloat(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function money(value: string | number | null | undefined, digits = 0): string {
  const n = typeof value === "number" ? value : num(value);
  return n === null ? "—" : usd(n, digits);
}

function pct(value: string | null | undefined, digits = 1): string {
  const n = num(value);
  return n === null ? "—" : `${(n * 100).toFixed(digits)}%`;
}

function roundPct(value: string | null | undefined): number {
  const n = num(value);
  return n === null ? 0 : Math.round(n * 100);
}

function DashboardLoading() {
  return (
    <>
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
    </>
  );
}

function performanceFeeCopy(feePercent: string | null | undefined): string {
  const fee = pct(feePercent, 0);
  return fee === "—"
    ? "Verified savings retained after Varsten's performance fee."
    : `Verified savings retained after Varsten's ${fee} performance fee.`;
}

const KPI_COPY: Record<string, { label: string; detail: (feePercent: string | null | undefined) => string }> = {
  net_saved: {
    label: "Net Realized Savings",
    detail: performanceFeeCopy,
  },
  gross_saved: {
    label: "Gross Savings",
    detail: () => "Total cost eliminated before the performance fee is applied.",
  },
  without_varsten: {
    label: "Baseline Cost",
    detail: () => "Projected spend at provider list pricing, without Varsten.",
  },
  actual_spend: {
    label: "Actual Spend",
    detail: () => "Amount paid directly to providers this period.",
  },
};

function kpiCopy(kpi: DashboardKpi, feePercent: string | null | undefined): { label: string; detail: string } {
  const copy = KPI_COPY[kpi.key];
  return copy
    ? { label: copy.label, detail: copy.detail(feePercent) }
    : { label: kpi.label, detail: kpi.detail };
}

// Savings/gross KPIs read better when they go up; spend KPIs read better when they
// go down. The arrow follows the raw sign; the color follows whether that is good.
const HIGHER_IS_BETTER = new Set(["net_saved", "gross_saved"]);

function DeltaPill({ kpi, period }: { kpi: DashboardKpi; period: DashboardPeriod }) {
  const n = num(kpi.delta.delta_pct);
  if (n === null) return null;
  const magnitude = `${Math.abs(n * 100).toFixed(0)}%`;
  const arrow = n === 0 ? "→" : n > 0 ? "↑" : "↓";
  // Favorable changes get the green pill; everything else stays neutral gray
  // rather than alarming red, matching the mockup's calm badge treatment. Only
  // the arrow + percent sit in the pill; "vs. prior <period>" is plain gray text.
  const tone = n !== 0 && n > 0 === HIGHER_IS_BETTER.has(kpi.key) ? "up" : "flat";
  return (
    <div className="dash-metric-delta">
      <span className={`dash-metric-delta-pill ${tone}`}>
        {arrow} {magnitude}
      </span>
      <span className="dash-metric-delta-suffix">vs. prior {period}</span>
    </div>
  );
}

function MetricCard({
  kpi,
  period,
  feePercent,
}: {
  kpi: DashboardKpi;
  period: DashboardPeriod;
  feePercent: string | null | undefined;
}) {
  const copy = kpiCopy(kpi, feePercent);
  return (
    <section className={kpi.tone === "brand" ? "dash-metric primary" : "dash-metric"}>
      <p>
        <span aria-hidden="true" />
        {copy.label}
      </p>
      <strong>{money(kpi.value)}</strong>
      <small>{copy.detail}</small>
      <DeltaPill kpi={kpi} period={period} />
    </section>
  );
}

function SavingsTrendPanel({ trend, stats }: { trend: SavingsTrendBucket[]; stats: TrendStats }) {
  const hasTrend = trend.length > 0;
  return (
    <section className="dash-card dash-trend-card">
      <div className="dash-card-head">
        <div>
          <h2>Daily Savings</h2>
          <p>Each bar shows your projected cost for the day, split into what you paid and what Varsten saved.</p>
        </div>
        <div className="dash-chart-legend" aria-label="Chart legend">
          <span><i className="spend" />Actual spend</span>
          <span><i className="savings" />Savings</span>
        </div>
      </div>
      {hasTrend ? (
        <>
          <div className="dash-trend-chart">
            <NetSavingsTrendChart points={trend} />
          </div>
          <div className="dash-trend-stats">
            <div>
              <span>Avg daily spend</span>
              <b>{money(stats.avg_spend_per_bucket_usd)}</b>
            </div>
            <div>
              <span>Avg daily savings</span>
              <b>{money(stats.avg_saved_per_bucket_usd)}</b>
            </div>
            <div>
              <span>Effective savings rate</span>
              <b>{pct(stats.effective_savings_rate)}</b>
            </div>
          </div>
        </>
      ) : (
        <PanelEmpty label="Send traffic through Varsten to build your savings trend." />
      )}
    </section>
  );
}

function ActiveLeversPanel({ levers, gross, mode }: { levers: DashboardLever[]; gross: string | null; mode: string }) {
  const active = levers.filter((lever) => lever.enabled).length;
  // A lever with no measured savings reads $0 / 0% once the project has traffic
  // (the lever is known, it simply saved nothing); "—" is reserved for the
  // genuinely empty dashboard where there is no data at all.
  const hasTraffic = mode !== "empty";
  const leverMoney = (value: string | null) => (value === null ? (hasTraffic ? "$0" : "—") : money(value));
  const leverPct = (value: string | null) => (value === null ? (hasTraffic ? "0%" : "—") : pct(value, 0));
  return (
    <section className="dash-card dash-levers-card">
      <div className="dash-card-head">
        <div className="dash-levers-heading">
          <h2>Savings by Lever</h2>
          <span className="dash-levers-count">{active} active</span>
        </div>
        <Link href="/engine/levers" className="dash-head-link">Open Engine →</Link>
      </div>
      {levers.length ? (
        <>
          <div className="dash-levers-list">
            {levers.map((lever) => (
              <div className={`dash-lever-item${lever.enabled ? "" : " dim"}`} key={lever.lever}>
                <div className="dash-lever-item-head">
                  <div className="dash-lever-item-name">
                    <b>{lever.label}</b>
                    <span className={`dash-lever-badge ${lever.enabled ? "active" : "off"}`}>{lever.status}</span>
                  </div>
                  <strong>{leverMoney(lever.value_usd)}</strong>
                </div>
                <div className="dash-lever-item-bar">
                  <span><i style={{ width: `${roundPct(lever.share)}%` }} /></span>
                  <em>{leverPct(lever.share)}</em>
                </div>
              </div>
            ))}
          </div>
          <div className="dash-levers-foot">
            <span>Gross savings</span>
            <b>{money(gross)}</b>
          </div>
        </>
      ) : (
        <PanelEmpty label="Lever status appears here once Engine configuration loads." />
      )}
    </section>
  );
}

function DriverBars({ rows }: { rows: DashboardDriverRow[] }) {
  const shownTotal = rows.reduce((sum, row) => sum + (num(row.spend_usd) ?? 0), 0);
  return (
    <div className="dash-drivers-bars">
      <h3 className="dash-drivers-section-title">Allocation Breakdown</h3>
      <div className="dash-driver-stack" aria-hidden="true">
        {rows.map((row, index) => {
          const seg = shownTotal > 0 ? ((num(row.spend_usd) ?? 0) / shownTotal) * 100 : 0;
          return (
            <span
              key={`seg-${row.key ?? "untagged"}-${index}`}
              style={{ width: `${seg}%`, background: DRIVER_PALETTE[index] ?? DRIVER_PALETTE[DRIVER_PALETTE.length - 1] }}
            />
          );
        })}
      </div>
      <div className="dash-driver-rows">
        {rows.map((row, index) => {
          const color = DRIVER_PALETTE[index] ?? DRIVER_PALETTE[DRIVER_PALETTE.length - 1];
          const untagged = row.key === null;
          return (
            <div className={`dash-driver-row${untagged ? " untagged" : ""}`} key={`${row.key ?? "untagged"}-${index}`}>
              <span className="dash-driver-swatch" style={{ background: color }} />
              <span className="dash-driver-name">{row.label}</span>
              <div className="dash-driver-track">
                <div className="dash-driver-fill" style={{ width: `${roundPct(row.share)}%`, background: color }} />
              </div>
              <span className="dash-driver-amount">{money(row.spend_usd)}</span>
              <span className="dash-driver-pct">{pct(row.share, 1)}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function TopSpendDriversPanel({ drivers }: { drivers: DashboardDrivers }) {
  const [tab, setTab] = useState<"team" | "feature">("team");
  const rows = tab === "team" ? drivers.team : drivers.feature;
  const emptyLabel = tab === "team"
    ? "Team spend appears here once usage includes team metadata."
    : "Feature spend appears here once usage includes feature metadata.";

  return (
    <section className="dash-card dash-drivers-card">
      <div className="dash-card-head">
        <div>
          <h2>Spend Drivers</h2>
          <p>A full breakdown of where your {money(drivers.actual_total_usd)} in actual spend was allocated.</p>
        </div>
        <Link href="/analysis/spend" className="dash-head-link">View Full Analysis →</Link>
      </div>
      <div className="dash-drivers-tabs" role="tablist">
        <button role="tab" aria-selected={tab === "team"} className={`dash-drivers-tab${tab === "team" ? " active" : ""}`} onClick={() => setTab("team")}>By Team</button>
        <button role="tab" aria-selected={tab === "feature"} className={`dash-drivers-tab${tab === "feature" ? " active" : ""}`} onClick={() => setTab("feature")}>By Feature</button>
      </div>
      {rows.length ? <DriverBars rows={rows} /> : <PanelEmpty label={emptyLabel} />}
    </section>
  );
}

function coverageBadge(value: number | null): { text: string; cls: string } {
  if (value === null) return { text: "Unchecked", cls: "gray" };
  if (value >= 0.95) return { text: "Catalog-Verified", cls: "confidence" };
  if (value >= 0.8) return { text: "Mostly Verified", cls: "confidence" };
  return { text: "Partial", cls: "amber" };
}

function attributionBadge(value: number | null): { text: string; cls: string } {
  if (value === null) return { text: "Unknown", cls: "gray" };
  if (value >= 0.9) return { text: "Fully Tagged", cls: "confidence" };
  if (value >= 0.5) return { text: "Partial", cls: "amber" };
  return { text: "Low", cls: "amber" };
}

function proofConfidenceClass(level: DashboardProofTrust["confidence_level"]): string {
  return `confidence-${level}`;
}

function ratioValueCls(value: number | null, highThreshold: number): string {
  if (value === null) return "gray";
  return value >= highThreshold ? "confidence" : "amber";
}

function verifiedSavingsBadge(proof: DashboardProofTrust, measured: number | null): { text: string; cls: string } {
  if (proof.claimed_savings_usd === null) return { text: "No data", cls: "gray" };
  if (measured !== null && measured > 0) return { text: "Ledger-Backed", cls: "confidence" };
  return { text: "Modeled", cls: "amber" };
}

function ProofMetric({
  name,
  badge,
  value,
  valueCls,
  desc,
  children,
}: {
  name: string;
  badge: { text: string; cls: string } | null;
  value: string;
  valueCls?: string;
  desc: string;
  children?: ReactNode;
}) {
  return (
    <div className="dash-proof-metric">
      <div className="dash-proof-metric-top">
        <div className="dash-proof-metric-name">
          <b>{name}</b>
          {badge && <span className={`dash-proof-badge ${badge.cls}`}>{badge.text}</span>}
        </div>
        <span className={`dash-proof-metric-val ${valueCls ?? ""}`}>{value}</span>
      </div>
      <p className="dash-proof-metric-desc">{desc}</p>
      {children}
    </div>
  );
}

function ProofTrustPanel({ proof }: { proof: DashboardProofTrust }) {
  const coverage = num(proof.pricing_coverage);
  const attribution = num(proof.attribution_share);
  const measured = num(proof.measured_share);
  const hero = proofHeroValues(proof);
  const isHighConfidence = proof.confidence_level === "high";

  return (
    <section className={`dash-card dash-proof-card ${proofConfidenceClass(proof.confidence_level)}`}>
      <div className="dash-card-head">
        <h2>Data Integrity</h2>
        <Link href="/proof/attribution" className="dash-head-link">View Audit Trail →</Link>
      </div>

      <div className="dash-proof-hero">
        <div className="dash-proof-hero-main">
          {isHighConfidence && <span className="dash-proof-check" aria-hidden="true">✓</span>}
          <div>
            <p className="dash-proof-section-title">Confidence Score</p>
            <p className="dash-proof-hero-label">{proof.confidence_label}</p>
            <p className="dash-proof-hero-note">{proof.confidence_note}</p>
          </div>
        </div>
        <div className="dash-proof-hero-score">
          <b>{hero.scoreDisplay}</b>
          <span>{hero.scoreSuffix}</span>
        </div>
      </div>

      <div className="dash-proof-metrics">
        <ProofMetric
          name="Pricing coverage"
          badge={coverageBadge(coverage)}
          value={pct(proof.pricing_coverage, 0)}
          valueCls={ratioValueCls(coverage, 0.9)}
          desc="All spend is priced against official provider catalogs or your organization's negotiated rates — never estimated or self-reported."
        />
        <ProofMetric
          name="Verified savings"
          badge={verifiedSavingsBadge(proof, measured)}
          value={proof.claimed_savings_usd === null ? "—" : `${money(proof.verified_savings_usd)} of ${money(proof.claimed_savings_usd)}`}
          valueCls={proof.claimed_savings_usd === null ? "gray" : "confidence"}
          desc={hero.verifiedDesc}
        />
        <ProofMetric
          name="Spend attribution"
          badge={attributionBadge(attribution)}
          value={pct(proof.attribution_share, 1)}
          valueCls={ratioValueCls(attribution, 0.9)}
          desc="Every request is tagged to a team or feature, so all spend is fully accountable and owned."
        />
      </div>
    </section>
  );
}

function proofHeroValues(proof: DashboardProofTrust) {
  const score = num(proof.score);
  const measured = num(proof.measured_share);
  const measuredPct = measured === null ? 0 : Math.round(measured * 100);
  return {
    scoreDisplay: score === null ? "—" : String(Math.round(score * 100)),
    scoreSuffix: score === null ? "No data" : "/ 100",
    verifiedDesc: proof.claimed_savings_usd === null
      ? "Verified savings appear once measured optimizations run."
      : `Savings are traced to real cache hits, routing events, and batch records — ${measuredPct}% recorded, ${100 - measuredPct}% modeled.`,
  };
}

function FallbackCoveragePanel({ coverage }: { coverage: FallbackCoverageRow[] }) {
  return (
    <section className="dash-card dash-coverage-card">
      <div className="dash-card-head">
        <h2>Fallback Coverage</h2>
        <Link href="/admin/connections" className="dash-head-link">Connect SDKs →</Link>
      </div>
      <p className="dash-coverage-note">
        The fail-open SDK keeps your app running when Varsten is unavailable by calling your
        provider directly — an outage costs savings, not uptime. Base-URL mode returns typed
        errors but has no automatic fallback, so the SDK is the safe production path.
      </p>
      <div className="dash-levers-list">
        {coverage.map((row) => {
          const detail = row.sdk_enabled
            ? (row.sdk_client ?? "SDK active")
            : row.key_configured
              ? "Key set · base-URL mode (no auto-fallback)"
              : "Not integrated";
          return (
            <div className={`dash-lever-item${row.sdk_enabled ? "" : " dim"}`} key={row.provider}>
              <div className="dash-lever-item-head">
                <div className="dash-lever-item-name">
                  <strong>{row.label}</strong>
                  <span className={`dash-lever-badge ${row.sdk_enabled ? "active" : "off"}`}>{row.status}</span>
                </div>
                <span className="dash-coverage-detail">{detail}</span>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

// Shown the moment onboarding is finished but no traffic has arrived. Replaces
// the whole dashboard grid — a wall of "—" placeholders is a worse first
// impression than a focused "you're set up, waiting for traffic" state. Polls so
// it flips to the live dashboard the instant the first request lands, matching
// the onboarding verify step's live confirmation.
function DashboardEmptyState() {
  const { observeOnly } = useEntitlements();
  const { reload } = useDashboard();

  useTimedPolling(true, 6000, reload);

  return (
    <section className="dash-card dash-empty">
      <div className="dash-empty-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
          <path d="M3 12h4l2 6 4-14 2 8h6" />
        </svg>
      </div>
      <h2 className="dash-empty-title">Waiting for your first request</h2>
      <p className="dash-empty-body">
        You&apos;re connected.{" "}
        {observeOnly
          ? "The moment traffic flows through Varsten, this dashboard fills in with your live spend and where it can be cut."
          : "The moment traffic flows through Varsten, this dashboard fills in with your live spend, the cuts worth real money, and a verified savings number for finance."}{" "}
        Nothing in production changes until you turn on optimization.
      </p>
      <div className="dash-empty-live">
        <span className="spinner" />
        <span>Listening for your first request — this page updates the instant it lands.</span>
      </div>
      <div className="dash-empty-actions">
        <Link href="/onboarding" className="btn primary">View setup steps</Link>
        <a href={DOCS_HREF} target="_blank" rel="noreferrer" className="btn">Read the docs</a>
      </div>
    </section>
  );
}

function readDashboardPreviewEnabled(): boolean {
  if (process.env.NODE_ENV !== "development" || typeof window === "undefined") return false;

  const params = new URLSearchParams(window.location.search);
  const queryValue = params.get("dashboard_preview");
  if (queryValue === "1") return true;
  if (queryValue === "0") return false;
  return window.localStorage.getItem(DASHBOARD_PREVIEW_STORAGE_KEY) === "1";
}

function subscribeDashboardPreview(onStoreChange: () => void): () => void {
  if (typeof window === "undefined") return () => {};

  window.addEventListener("storage", onStoreChange);
  window.addEventListener("popstate", onStoreChange);
  return () => {
    window.removeEventListener("storage", onStoreChange);
    window.removeEventListener("popstate", onStoreChange);
  };
}

function useDashboardPreviewEnabled(): boolean {
  const enabled = useSyncExternalStore(subscribeDashboardPreview, readDashboardPreviewEnabled, () => false);

  useEffect(() => {
    if (process.env.NODE_ENV !== "development") return;
    const params = new URLSearchParams(window.location.search);
    const queryValue = params.get("dashboard_preview");
    if (queryValue === "1") {
      window.localStorage.setItem(DASHBOARD_PREVIEW_STORAGE_KEY, "1");
      return;
    }
    if (queryValue === "0") {
      window.localStorage.removeItem(DASHBOARD_PREVIEW_STORAGE_KEY);
    }
  }, []);

  return enabled;
}

function FirstRunBanner({ mode, grossSavings }: { mode: string; grossSavings: string | null }) {
  const { observeOnly } = useEntitlements();

  if (mode === "empty") return null;

  if (observeOnly) {
    const opportunity = num(grossSavings);
    return (
      <section className="dash-card">
        <div className="dash-card-head">
          <h2>You&apos;re observing — savings are not turned on yet</h2>
          <Link href="/upgrade" className="dash-head-link">Turn on savings →</Link>
        </div>
        <p className="dash-coverage-note">
          Varsten is measuring your traffic in observe-only mode.{" "}
          {opportunity
            ? `We estimate about ${money(grossSavings)} in savings you could capture. `
            : "As traffic accrues we surface the savings you could capture. "}
          Enabling Optimize lets Varsten act on them — safely, behind eval gates and rollback —
          and bills only on verified savings.
        </p>
      </section>
    );
  }

  return null;
}

export function SavingsDashboard() {
  const { snapshot, period } = useDashboard();
  const previewEmptyDashboard = useDashboardPreviewEnabled();
  const data = snapshot.data;

  if (snapshot.loading && !data) return <div className="dashboard-view dash-overview"><DashboardLoading /></div>;
  if (snapshot.error) return <div className="dashboard-view dash-overview"><section className="dash-card"><PanelEmpty label={snapshot.error} /></section></div>;
  if (!data) return <div className="dashboard-view dash-overview"><section className="dash-card"><PanelEmpty label="Dashboard data is not available yet." /></section></div>;

  // No traffic yet: a focused "waiting for your first request" state, not a grid
  // of empty placeholders.
  if (data.mode === "empty" && !previewEmptyDashboard) return <div className="dashboard-view dash-overview"><DashboardEmptyState /></div>;

  return (
    <div className="dashboard-view dash-overview">
      <FirstRunBanner mode={data.mode} grossSavings={data.gross_savings_usd} />
      <div className="dash-metric-strip">
        {data.kpis.map((kpi) => (
          <MetricCard key={kpi.key} kpi={kpi} period={period} feePercent={data.fee_percent} />
        ))}
      </div>
      <div className="dash-main-grid">
        <SavingsTrendPanel trend={data.savings_trend} stats={data.trend_stats} />
        <ActiveLeversPanel levers={data.levers} gross={data.gross_savings_usd} mode={data.mode} />
      </div>
      <div className="dash-bottom-grid">
        <TopSpendDriversPanel drivers={data.drivers} />
        <ProofTrustPanel proof={data.proof_trust} />
      </div>
      <FallbackCoveragePanel coverage={data.fallback_coverage} />
    </div>
  );
}
