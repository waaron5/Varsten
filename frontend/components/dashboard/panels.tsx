"use client";

import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import Link from "next/link";
import { useEntitlements } from "@/components/entitlements";
import { useTimedPolling } from "@/components/useTimedPolling";
import { DOCS_HREF } from "@/lib/integrationSnippets";
import { PanelEmpty, PanelSkeleton } from "./primitives";
import { useDashboard } from "./DashboardProvider";
import {
  compactMoneyDisplay,
  dashboardViewModel,
  shortChartDate,
  type DashboardDailyPointView,
  type DashboardDriverView,
  type DashboardFallbackCoverageView,
  type DashboardIntegrityMetricView,
  type DashboardKpiView,
  type DashboardLeverView,
  type DashboardStatView,
  type TrustLevel,
} from "./viewModel";

const DASHBOARD_PREVIEW_STORAGE_KEY = "varsten:dashboard-preview";
const LEVER_OPACITY = [1, 0.78, 0.58, 0.42, 0.3, 0.22];
const DRIVER_OPACITY = [1, 0.78, 0.58, 0.42, 0.3, 0.22];

type DrawableDailyPoint = DashboardDailyPointView & {
  actual: number;
  savings: number;
  total: number;
};

function hasChartValues(point: DashboardDailyPointView): point is DrawableDailyPoint {
  return point.actual !== null && point.savings !== null && point.total !== null;
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

function DashboardLoading() {
  return (
    <div className="lv-dashboard">
      <div className="lv-kpi-strip">
        <PanelSkeleton />
        <PanelSkeleton />
        <PanelSkeleton />
        <PanelSkeleton />
      </div>
      <PanelSkeleton />
      <div className="lv-panel-grid">
        <PanelSkeleton />
        <PanelSkeleton />
        <PanelSkeleton />
      </div>
    </div>
  );
}

function EmptyState() {
  const { observeOnly } = useEntitlements();
  const { reload } = useDashboard();

  useTimedPolling(true, 6000, reload);

  return (
    <section className="lv-empty-card">
      <div className="lv-empty-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round">
          <path d="M3 12h4l2 6 4-14 2 8h6" />
        </svg>
      </div>
      <h2>Waiting for your first request</h2>
      <p>
        You&apos;re connected.{" "}
        {observeOnly
          ? "The moment traffic flows through Varsten, this dashboard fills in with your live spend and where it can be cut."
          : "The moment traffic flows through Varsten, this dashboard fills in with your live spend, the cuts worth real money, and a verified savings number for finance."}{" "}
        Nothing in production changes until you turn on optimization.
      </p>
      <div className="lv-empty-live">
        <span className="spinner" />
        <span>Listening for your first request. This page updates the instant it lands.</span>
      </div>
      <div className="lv-empty-actions">
        <Link href="/onboarding" className="btn primary">View setup steps</Link>
        <a href={DOCS_HREF} target="_blank" rel="noreferrer" className="btn">Read the docs</a>
      </div>
    </section>
  );
}

function FirstRunBanner({ grossSavings }: { grossSavings: string }) {
  const { observeOnly } = useEntitlements();
  if (!observeOnly) return null;

  const hasOpportunity = grossSavings !== "—";
  return (
    <section className="lv-observe-banner">
      <div>
        <div className="lv-section-kicker blue">Observe-only mode</div>
        <h2>You&apos;re observing. Savings are not turned on yet.</h2>
        <p>
          {hasOpportunity ? (
            <>
              Based on your traffic so far, Varsten estimates <strong>{grossSavings}</strong> in savings available once optimization is enabled.
            </>
          ) : (
            "As traffic accrues, Varsten surfaces the savings you could capture once optimization is enabled."
          )}
        </p>
      </div>
      <Link href="/upgrade" className="lv-banner-action">
        Turn on savings
        <span aria-hidden="true">→</span>
      </Link>
    </section>
  );
}

function DeltaPill({ delta, hero }: { delta: DashboardKpiView["delta"]; hero?: boolean }) {
  if (!delta) return null;
  const arrow = delta.arrow === "flat" ? "→" : delta.arrow === "up" ? "↑" : "↓";
  return (
    <span className={`lv-delta${delta.favorable ? " favorable" : ""}${hero ? " hero" : ""}`}>
      <span aria-hidden="true">{arrow}</span>
      <span>{delta.pctDisplay}</span>
      <span className="sr-only">
        {delta.arrow === "up" ? "increased" : delta.arrow === "down" ? "decreased" : "unchanged"} {delta.pctDisplay} versus prior period,
        {delta.favorable ? " favorable" : " unfavorable"}
      </span>
    </span>
  );
}

function KpiCard({ kpi }: { kpi: DashboardKpiView }) {
  return (
    <article className={`lv-kpi-card${kpi.hero ? " hero" : ""}`}>
      <div className="lv-kpi-label">
        <span>{kpi.label}</span>
        {kpi.hero ? <span className="lv-hero-dot" aria-hidden="true">●</span> : null}
      </div>
      <div className="lv-kpi-body">
        <div className="lv-kpi-value">{kpi.valueDisplay}</div>
        <div className="lv-kpi-delta-row">
          <DeltaPill delta={kpi.delta} hero={kpi.hero} />
          <span>vs. prior period</span>
        </div>
        <p>{kpi.detail}</p>
      </div>
    </article>
  );
}

function KpiStrip({ kpis }: { kpis: DashboardKpiView[] }) {
  return (
    <section className="lv-kpi-strip" aria-label="Dashboard KPIs">
      {kpis.map((kpi) => (
        <KpiCard key={kpi.key} kpi={kpi} />
      ))}
    </section>
  );
}

function Stat({ stat, bordered }: { stat: DashboardStatView; bordered?: boolean }) {
  return (
    <div className={bordered ? "bordered" : undefined}>
      <span>{stat.label}</span>
      <b className={stat.positive ? "positive" : undefined}>{stat.value}</b>
    </div>
  );
}

function DailySavingsChart({ data, stats }: { data: DashboardDailyPointView[]; stats: DashboardStatView[] }) {
  const chartData = data.filter(hasChartValues);
  const width = 1400;
  const height = 340;
  const padL = 56;
  const padR = 16;
  const padT = 16;
  const padB = 32;
  const innerW = width - padL - padR;
  const innerH = height - padT - padB;
  const max = Math.max(...chartData.map((point) => point.total), 0) * 1.1 || 1;
  const step = chartData.length ? innerW / chartData.length : innerW;
  const barW = Math.max(3, step * 0.7);
  const ticks = Array.from({ length: 5 }, (_, i) => (max / 4) * i);
  const showLabelEvery = Math.max(1, Math.ceil(chartData.length / 10));

  return (
    <article className="lv-panel lv-daily-panel">
      <header className="lv-panel-head">
        <div>
          <div className="lv-section-kicker">Section 01 · Trend</div>
          <h3>Daily Savings</h3>
        </div>
        <ul className="lv-chart-legend" aria-label="Chart legend">
          <li><span className="actual" aria-hidden="true" />Actual spend</li>
          <li><span className="savings" aria-hidden="true" />Savings</li>
        </ul>
      </header>

      {chartData.length ? (
        <>
          <div className="lv-svg-chart">
            <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Daily stacked spend and savings">
              {ticks.map((value, index) => {
                const y = padT + innerH - (value / max) * innerH;
                return (
                  <g key={index}>
                    <line x1={padL} x2={width - padR} y1={y} y2={y} />
                    <text x={padL - 8} y={y + 3} textAnchor="end">
                      {compactMoneyDisplay(value)}
                    </text>
                  </g>
                );
              })}

              {chartData.map((point, index) => {
                const x = padL + step * index + (step - barW) / 2;
                const actualH = (point.actual / max) * innerH;
                const savingsH = (point.savings / max) * innerH;
                const totalH = (point.total / max) * innerH;
                const yTop = padT + innerH - totalH;
                return (
                  <g key={point.date}>
                    <rect x={x} y={padT + innerH - actualH} width={barW} height={actualH} className="actual">
                      <title>{`${point.date} · Actual ${point.actualDisplay}`}</title>
                    </rect>
                    <rect x={x} y={yTop} width={barW} height={savingsH} className="savings">
                      <title>{`${point.date} · Savings ${point.savingsDisplay}`}</title>
                    </rect>
                    {index % showLabelEvery === 0 ? (
                      <text x={x + barW / 2} y={height - 10} textAnchor="middle">
                        {shortChartDate(point.date)}
                      </text>
                    ) : null}
                  </g>
                );
              })}
            </svg>
          </div>

          <div className="lv-daily-stats">
            {stats.map((stat, index) => (
              <Stat key={stat.label} stat={stat} bordered={index > 0} />
            ))}
          </div>
        </>
      ) : (
        <PanelEmpty label={data.length ? "Savings trend is unavailable for this period." : "Send traffic through Varsten to build your savings trend."} />
      )}
    </article>
  );
}

function leverTone(lever: DashboardLeverView, activeRank: Map<string, number>) {
  if (!lever.active) return { className: "muted", opacity: 0.35 };
  const rank = activeRank.get(lever.id) ?? 0;
  return { className: "blue", opacity: LEVER_OPACITY[rank] ?? 0.2 };
}

function SavingsByLever({
  activeCount,
  levers,
  totalDisplay,
}: {
  activeCount: number;
  levers: DashboardLeverView[];
  totalDisplay: string;
}) {
  const max = Math.max(...levers.map((lever) => lever.value ?? 0), 0);
  const activeRank = useMemo(() => {
    const ranks = new Map<string, number>();
    levers.filter((lever) => lever.active).forEach((lever, index) => ranks.set(lever.id, index));
    return ranks;
  }, [levers]);

  return (
    <article className="lv-panel lv-list-panel">
      <header className="lv-panel-head">
        <div>
          <div className="lv-section-kicker">Section 02 · Mechanism</div>
          <h3>Savings by Lever</h3>
        </div>
        <Link href="/engine/levers" className="lv-panel-link">Engine →</Link>
      </header>

      <div className="lv-panel-tabs">
        <div className="active">{activeCount} · {levers.length} active</div>
      </div>

      {levers.length ? (
        <>
          <div className="lv-stack-bar" aria-hidden="true">
            {levers.map((lever) => {
              const tone = leverTone(lever, activeRank);
              return (
                <span
                  key={lever.id}
                  className={tone.className}
                  style={{ width: `${(lever.share ?? 0) * 100}%`, opacity: tone.opacity }}
                />
              );
            })}
          </div>

          <ul className="lv-ranked-list">
            {levers.map((lever) => {
              const tone = leverTone(lever, activeRank);
              const width = max > 0 && lever.value !== null ? (lever.value / max) * 100 : 0;
              return (
                <li key={lever.id} className={!lever.active ? "dim" : undefined}>
                  <div className="lv-ranked-row">
                    <div className="lv-ranked-name">
                      <span className="lv-row-id">{lever.id}</span>
                      <span>{lever.name}</span>
                      <span className={`lv-status${lever.active ? " active" : ""}`}>
                        <i aria-hidden="true" />
                        {lever.status}
                      </span>
                    </div>
                    <div className="lv-ranked-values">
                      <span>{lever.valueDisplay}</span>
                      <em>{lever.shareDisplay}</em>
                    </div>
                  </div>
                  <div className="lv-row-track">
                    <span className={tone.className} style={{ width: `${width}%`, opacity: tone.opacity }} />
                  </div>
                </li>
              );
            })}
          </ul>

          <footer className="lv-panel-foot">
            <span>Gross savings</span>
            <b>{totalDisplay}</b>
          </footer>
        </>
      ) : (
        <PanelEmpty label="Lever status appears here once Engine configuration loads." />
      )}
    </article>
  );
}

function SpendDrivers({
  actualTotalDisplay,
  feature,
  team,
}: {
  actualTotalDisplay: string;
  feature: DashboardDriverView[];
  team: DashboardDriverView[];
}) {
  const [tab, setTab] = useState<"team" | "feature">("team");
  const rows = tab === "team" ? team : feature;
  const max = Math.max(...rows.map((row) => row.value ?? 0), 0);

  return (
    <article className="lv-panel lv-list-panel">
      <header className="lv-panel-head">
        <div>
          <div className="lv-section-kicker">Section 03 · Allocation</div>
          <h3>Spend Drivers</h3>
        </div>
        <Link href="/analysis/spend" className="lv-panel-link">Analysis →</Link>
      </header>

      <div className="lv-panel-tabs" role="tablist" aria-label="Spend driver dimension">
        {(["team", "feature"] as const).map((value) => (
          <button
            key={value}
            type="button"
            role="tab"
            aria-selected={tab === value}
            className={tab === value ? "active" : undefined}
            onClick={() => setTab(value)}
          >
            By {value}
          </button>
        ))}
      </div>

      {rows.length ? (
        <>
          <div className="lv-stack-bar gold" aria-hidden="true">
            {rows.map((row, index) => (
              <span
                key={row.key}
                style={{ width: `${(row.share ?? 0) * 100}%`, opacity: DRIVER_OPACITY[index] ?? 0.15 }}
              />
            ))}
          </div>

          <ul className="lv-ranked-list">
            {rows.map((row, index) => {
              const width = max > 0 && row.value !== null ? (row.value / max) * 100 : 0;
              const opacity = DRIVER_OPACITY[index] ?? 0.15;
              return (
                <li key={row.key} className={row.untagged ? "dim" : undefined}>
                  <div className="lv-ranked-row">
                    <div className="lv-ranked-name">
                      <span className="lv-driver-swatch" style={{ opacity }} aria-hidden="true" />
                      <span>{row.name}</span>
                    </div>
                    <div className="lv-ranked-values">
                      <span>{row.valueDisplay}</span>
                      <em>{row.shareDisplay}</em>
                    </div>
                  </div>
                  <div className="lv-row-track gold">
                    <span style={{ width: `${width}%`, opacity }} />
                  </div>
                </li>
              );
            })}
          </ul>

          <footer className="lv-panel-foot">
            <span>Total spend</span>
            <b>{actualTotalDisplay}</b>
          </footer>
        </>
      ) : (
        <PanelEmpty label={tab === "team" ? "Team spend appears here once usage includes team metadata." : "Feature spend appears here once usage includes feature metadata."} />
      )}
    </article>
  );
}

function TrustBadge({ level }: { level: TrustLevel }) {
  const label = level === "confidence" ? "Verified" : level === "partial" ? "Partial" : "Unknown";
  return <span className={`lv-trust-badge ${level}`}>{label}</span>;
}

function IntegrityRow({ row }: { row: DashboardIntegrityMetricView }) {
  return (
    <li>
      <div>
        <div className="lv-row-label">{row.label}</div>
        <div className="lv-integrity-value">{row.value}</div>
        <p>{row.sub}</p>
      </div>
      <TrustBadge level={row.level} />
    </li>
  );
}

function DataIntegrity({ data }: { data: ReturnType<typeof dashboardViewModel>["integrity"] }) {
  return (
    <article className="lv-panel lv-integrity-panel">
      <header className="lv-panel-head">
        <div>
          <div className="lv-section-kicker">Section 04 · Proof</div>
          <h3>Data Integrity</h3>
        </div>
        <TrustBadge level={data.scoreLevel} />
      </header>

      <div className="lv-integrity-score">
        <div>{data.scoreDisplay}</div>
        <div>
          <div className="lv-row-label">Confidence score</div>
          <strong className="lv-confidence-label">
            {data.showCheck ? <span aria-hidden="true">✓</span> : null}
            {data.confidenceLabel}
          </strong>
          <p>{data.confidenceNote}</p>
        </div>
      </div>

      <ul className="lv-integrity-list">
        {data.rows.map((row) => (
          <IntegrityRow key={row.label} row={row} />
        ))}
      </ul>
    </article>
  );
}

function FallbackCoveragePanel({ rows }: { rows: DashboardFallbackCoverageView[] }) {
  return (
    <article className="lv-panel lv-coverage-panel">
      <header className="lv-panel-head">
        <div>
          <div className="lv-section-kicker">Section 05 · Resilience</div>
          <h3>Fallback Coverage</h3>
        </div>
        <Link href="/admin/connections" className="lv-panel-link">Connections →</Link>
      </header>
      <p className="lv-coverage-note">
        SDK fallback keeps production available when Varsten is unavailable. Base-URL mode returns typed errors but does not provide automatic provider fallback.
      </p>
      <ul className="lv-coverage-list">
        {rows.map((row) => (
          <li key={row.provider} className={row.enabled ? undefined : "dim"}>
            <div>
              <span>{row.label}</span>
              <small>{row.detail}</small>
            </div>
            <span className={`lv-status${row.enabled ? " active" : ""}`}>
              <i aria-hidden="true" />
              {row.status}
            </span>
          </li>
        ))}
      </ul>
    </article>
  );
}

export function SavingsDashboard() {
  const { snapshot, period } = useDashboard();
  const previewEmptyDashboard = useDashboardPreviewEnabled();
  const data = snapshot.data;
  const vm = useMemo(() => (data ? dashboardViewModel(data, period) : null), [data, period]);

  if (snapshot.loading && !data) return <DashboardLoading />;
  if (snapshot.error) return <div className="lv-dashboard"><section className="lv-panel"><PanelEmpty label={snapshot.error} /></section></div>;
  if (!data || !vm) return <div className="lv-dashboard"><section className="lv-panel"><PanelEmpty label="Dashboard data is not available yet." /></section></div>;

  if (data.mode === "empty" && !previewEmptyDashboard) {
    return (
      <div className="lv-dashboard">
        <EmptyState />
      </div>
    );
  }

  return (
    <div className="lv-dashboard">
      <FirstRunBanner grossSavings={vm.leverTotalDisplay} />
      <KpiStrip kpis={vm.kpis} />
      <DailySavingsChart data={vm.daily} stats={vm.dailyStats} />
      <section className="lv-panel-grid">
        <SavingsByLever activeCount={vm.activeLeverCount} levers={vm.levers} totalDisplay={vm.leverTotalDisplay} />
        <SpendDrivers actualTotalDisplay={vm.drivers.actualTotalDisplay} feature={vm.drivers.feature} team={vm.drivers.team} />
        <DataIntegrity data={vm.integrity} />
      </section>
      <FallbackCoveragePanel rows={vm.fallbackCoverage} />
    </div>
  );
}
