import type {
  DashboardDriverRow,
  DashboardKpi,
  DashboardLever,
  DashboardPeriod,
  DashboardProofTrust,
  DashboardSnapshot,
  FallbackCoverageRow,
  SavingsTrendBucket,
} from "@/lib/types";

export type TrustLevel = "confidence" | "partial" | "unknown";

export interface DashboardDeltaView {
  arrow: "up" | "down" | "flat";
  favorable: boolean;
  pctDisplay: string;
}

export interface DashboardKpiView {
  key: string;
  label: string;
  valueDisplay: string;
  detail: string;
  hero: boolean;
  delta: DashboardDeltaView | null;
}

export interface DashboardDailyPointView {
  date: string;
  actual: number | null;
  savings: number | null;
  total: number | null;
  actualDisplay: string;
  savingsDisplay: string;
}

export interface DashboardStatView {
  label: string;
  value: string;
  positive?: boolean;
}

export interface DashboardLeverView {
  id: string;
  name: string;
  active: boolean;
  status: string;
  value: number | null;
  valueDisplay: string;
  share: number | null;
  shareDisplay: string;
}

export interface DashboardDriverView {
  key: string;
  name: string;
  value: number | null;
  valueDisplay: string;
  share: number | null;
  shareDisplay: string;
  untagged: boolean;
}

export interface DashboardIntegrityMetricView {
  label: string;
  value: string;
  sub: string;
  level: TrustLevel;
}

export interface DashboardIntegrityView {
  scoreDisplay: string;
  scoreNumber: number | null;
  scoreLevel: TrustLevel;
  confidenceLabel: string;
  confidenceNote: string;
  showCheck: boolean;
  rows: DashboardIntegrityMetricView[];
}

export interface DashboardFallbackCoverageView {
  provider: string;
  label: string;
  enabled: boolean;
  status: string;
  detail: string;
}

export interface DashboardViewModel {
  period: DashboardPeriod;
  periodLabel: string;
  mode: string;
  kpis: DashboardKpiView[];
  daily: DashboardDailyPointView[];
  dailyStats: DashboardStatView[];
  levers: DashboardLeverView[];
  activeLeverCount: number;
  leverTotalDisplay: string;
  drivers: {
    actualTotalDisplay: string;
    team: DashboardDriverView[];
    feature: DashboardDriverView[];
  };
  integrity: DashboardIntegrityView;
  fallbackCoverage: DashboardFallbackCoverageView[];
}

const HIGHER_IS_BETTER = new Set(["net_saved", "gross_saved"]);

const KPI_COPY: Record<string, { label: string; detail: (feePercent: string | null | undefined) => string }> = {
  net_saved: {
    label: "Net Realized Savings",
    detail: () => "After optimization fee",
  },
  gross_saved: {
    label: "Gross Savings",
    detail: () => "Total cost eliminated pre-fee",
  },
  without_varsten: {
    label: "Baseline Cost",
    detail: () => "List-price spend without Varsten",
  },
  actual_spend: {
    label: "Actual Spend",
    detail: () => "Paid to providers this period",
  },
};

export function dashboardViewModel(snapshot: DashboardSnapshot, period: DashboardPeriod): DashboardViewModel {
  return {
    period,
    periodLabel: snapshot.label,
    mode: snapshot.mode,
    kpis: orderedKpis(snapshot.kpis).map((kpi) => kpiView(kpi, snapshot.fee_percent)),
    daily: snapshot.savings_trend.map(dailyPointView),
    dailyStats: [
      { label: "Avg daily spend", value: moneyDisplay(snapshot.trend_stats.avg_spend_per_bucket_usd) },
      { label: "Avg daily savings", value: moneyDisplay(snapshot.trend_stats.avg_saved_per_bucket_usd), positive: true },
      { label: "Effective savings rate", value: percentDisplay(snapshot.trend_stats.effective_savings_rate, 1) },
    ],
    levers: leverViews(snapshot.levers),
    activeLeverCount: snapshot.levers.filter((lever) => lever.enabled).length,
    leverTotalDisplay: moneyDisplay(snapshot.gross_savings_usd),
    drivers: {
      actualTotalDisplay: moneyDisplay(snapshot.drivers.actual_total_usd),
      team: driverViews(snapshot.drivers.team),
      feature: driverViews(snapshot.drivers.feature),
    },
    integrity: integrityView(snapshot.proof_trust),
    fallbackCoverage: snapshot.fallback_coverage.map(fallbackCoverageView),
  };
}

export function numberValue(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = typeof value === "number" ? value : Number.parseFloat(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function moneyDisplay(value: string | number | null | undefined, digits?: number): string {
  const parsed = numberValue(value);
  if (parsed === null) return "—";
  const abs = Math.abs(parsed);
  if (digits === undefined && parsed !== 0 && abs < 0.005) {
    return `${parsed < 0 ? "-" : ""}<$0.01`;
  }
  const resolvedDigits = digits ?? (abs > 0 && abs < 1 ? 2 : 0);
  return parsed.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: resolvedDigits,
    maximumFractionDigits: resolvedDigits,
  });
}

export function moneyExactDisplay(value: string | number | null | undefined): string {
  return moneyDisplay(value);
}

export function compactMoneyDisplay(value: string | number | null | undefined): string {
  const parsed = numberValue(value);
  if (parsed === null) return "—";
  const abs = Math.abs(parsed);
  const sign = parsed < 0 ? "-" : "";
  if (abs >= 1_000_000) return `${sign}$${(abs / 1_000_000).toFixed(2)}M`;
  if (abs >= 10_000) return `${sign}$${(abs / 1000).toFixed(1)}k`;
  return moneyDisplay(parsed);
}

export function percentDisplay(value: string | number | null | undefined, digits = 1): string {
  const parsed = numberValue(value);
  if (parsed === null) return "—";
  return `${(parsed * 100).toFixed(digits)}%`;
}

export function percentWholeDisplay(value: string | number | null | undefined): string {
  const parsed = numberValue(value);
  if (parsed === null) return "—";
  return `${Math.round(parsed * 100)}%`;
}

export function shortChartDate(iso: string): string {
  return iso.slice(5);
}

function orderedKpis(kpis: DashboardKpi[]): DashboardKpi[] {
  const byKey = new Map(kpis.map((kpi) => [kpi.key, kpi]));
  const preferred = ["net_saved", "gross_saved", "without_varsten", "actual_spend"]
    .map((key) => byKey.get(key))
    .filter((kpi): kpi is DashboardKpi => Boolean(kpi));
  const rest = kpis.filter((kpi) => !byKey.has(kpi.key) || !preferred.some((item) => item.key === kpi.key));
  return [...preferred, ...rest];
}

function kpiView(kpi: DashboardKpi, feePercent: string): DashboardKpiView {
  const copy = KPI_COPY[kpi.key];
  return {
    key: kpi.key,
    label: copy?.label ?? kpi.label,
    valueDisplay: compactMoneyDisplay(kpi.value),
    detail: copy?.detail(feePercent) ?? kpi.detail,
    hero: kpi.tone === "brand" || kpi.key === "net_saved",
    delta: deltaView(kpi),
  };
}

function deltaView(kpi: DashboardKpi): DashboardDeltaView | null {
  const value = numberValue(kpi.delta.delta_pct);
  if (value === null) return null;
  return {
    arrow: value === 0 ? "flat" : value > 0 ? "up" : "down",
    favorable: value !== 0 && value > 0 === HIGHER_IS_BETTER.has(kpi.key),
    pctDisplay: `${Math.abs(value * 100).toFixed(1)}%`,
  };
}

function dailyPointView(point: SavingsTrendBucket): DashboardDailyPointView {
  const actual = numberValue(point.optimized_usd);
  const savings = numberValue(point.saved_usd);
  return {
    date: point.date,
    actual,
    savings,
    total: actual === null || savings === null ? null : actual + savings,
    actualDisplay: moneyExactDisplay(point.optimized_usd),
    savingsDisplay: moneyExactDisplay(point.saved_usd),
  };
}

function leverViews(levers: DashboardLever[]): DashboardLeverView[] {
  return levers
    .map((lever, index) => {
      const value = numberValue(lever.value_usd);
      const share = numberValue(lever.share);
      return {
        id: String(index + 1).padStart(2, "0"),
        name: lever.label,
        active: lever.enabled,
        status: lever.status,
        value,
        valueDisplay: moneyExactDisplay(lever.value_usd),
        share,
        shareDisplay: percentDisplay(lever.share, 1),
      };
    })
    .sort((a, b) => (b.value ?? Number.NEGATIVE_INFINITY) - (a.value ?? Number.NEGATIVE_INFINITY));
}

function driverViews(rows: DashboardDriverRow[]): DashboardDriverView[] {
  return rows
    .map((row) => {
      const value = numberValue(row.spend_usd);
      const share = numberValue(row.share);
      return {
        key: row.key ?? "untagged",
        name: row.label,
        value,
        valueDisplay: moneyExactDisplay(row.spend_usd),
        share,
        shareDisplay: percentDisplay(row.share, 1),
        untagged: row.key === null,
      };
    })
    .sort((a, b) => (b.value ?? Number.NEGATIVE_INFINITY) - (a.value ?? Number.NEGATIVE_INFINITY));
}

function integrityView(proof: DashboardProofTrust): DashboardIntegrityView {
  const score = numberValue(proof.score);
  const scoreNumber = score === null ? null : Math.round(score * 100);
  const pricingCoverage = numberValue(proof.pricing_coverage);
  const measuredShare = numberValue(proof.measured_share);
  const attribution = numberValue(proof.attribution_share);
  const verifiedSavings = numberValue(proof.verified_savings_usd);
  const hasMeasuredSignal =
    measuredShare !== null ||
    verifiedSavings !== null ||
    proof.has_direct_ledger ||
    proof.has_ab_holdback;
  const verifiedValue = proof.claimed_savings_usd === null
    ? "—"
    : `${moneyExactDisplay(proof.verified_savings_usd)} · ${moneyExactDisplay(proof.claimed_savings_usd)} claimed`;
  return {
    scoreDisplay: scoreNumber === null ? "—" : String(scoreNumber),
    scoreNumber,
    scoreLevel: trustLevel(scoreNumber),
    confidenceLabel: proof.confidence_label,
    confidenceNote: proof.confidence_note,
    showCheck: proof.confidence_level === "high" && scoreNumber !== null && hasMeasuredSignal,
    rows: [
      {
        label: "Pricing coverage",
        value: percentWholeDisplay(proof.pricing_coverage),
        sub: "Priced against real provider catalogs",
        level: trustLevel(ratioToScore(pricingCoverage)),
      },
      {
        label: "Verified savings",
        value: verifiedValue,
        sub: measuredShare === null
          ? "Measured savings appear once optimization evidence is available"
          : `${Math.round(measuredShare * 100)}% of claimed savings measured end-to-end`,
        level: trustLevel(ratioToScore(measuredShare)),
      },
      {
        label: "Spend attribution",
        value: percentDisplay(proof.attribution_share, 1),
        sub: "Requests tagged to a team or feature",
        level: trustLevel(ratioToScore(attribution)),
      },
    ],
  };
}

function ratioToScore(value: number | null): number | null {
  return value === null ? null : Math.round(value * 100);
}

function trustLevel(score: number | null): TrustLevel {
  if (score === null) return "unknown";
  if (score >= 85) return "confidence";
  if (score >= 60) return "partial";
  return "unknown";
}

function fallbackCoverageView(row: FallbackCoverageRow): DashboardFallbackCoverageView {
  return {
    provider: row.provider,
    label: row.label,
    enabled: row.sdk_enabled,
    status: row.status,
    detail: row.sdk_enabled
      ? row.sdk_client ?? "SDK active"
      : row.key_configured
        ? "Key set · base-URL mode"
        : "Not integrated",
  };
}
