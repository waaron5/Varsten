import type { Dashboard, LeverConfig, MetricsOverview, ProofDataQuality, ProofSavings } from "@/lib/types";
import { leverLabel } from "@/components/viewPrimitives";

export type SavingsMode = "verified" | "estimated" | "projected" | "empty";

export interface SavingsComparison {
  withoutLabel: string;
  withLabel: string;
  withoutValue: number;
  withValue: number;
  gapValue: number;
  netValue: number | null;
}

export interface DashboardMetric {
  label: string;
  value: number | string | null;
  kind: "money" | "percent" | "compact" | "text";
  detail: string;
  tone?: "brand";
}

export interface DashboardLeverRow {
  enabled: boolean;
  impactValue: number;
  lever: string;
  share: number | null;
  status: string;
}

export interface DashboardTrustMetric {
  label: string;
  value: number | string | null;
  kind: "percent" | "score" | "text";
  tone?: "brand" | "positive";
}

export interface DashboardViewModel {
  accountingMetrics: DashboardMetric[];
  comparison: SavingsComparison | null;
  headline: string;
  headlineSuffix?: string;
  headlineValue: number | null;
  levers: DashboardLeverRow[];
  leversRunning: number;
  mode: SavingsMode;
  nextAction: {
    body: string;
    href: string;
    impactLabel: string | null;
    impactValue: number | null;
    label: string;
    qualityLabel: string | null;
    qualityValue: string | null;
    title: string;
  };
  proofTrust: {
    note: string;
    score: number | null;
    metrics: DashboardTrustMetric[];
  };
  statusLabel: string;
  subheading: string;
}

function num(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined) return null;
  const parsed = typeof value === "string" ? parseFloat(value) : value;
  return Number.isFinite(parsed) ? parsed : null;
}

function positive(value: string | number | null | undefined): number | null {
  const parsed = num(value);
  return parsed !== null && parsed > 0 ? parsed : null;
}

function pricingCoverage(dataQuality: ProofDataQuality | null): number | null {
  if (!dataQuality) return null;
  const total = dataQuality.priced_event_count + dataQuality.unpriced_event_count;
  return total > 0 ? dataQuality.priced_event_count / total : null;
}


const LEVER_ORDER = ["smart_routing", "semantic_cache", "token_trim", "cheaper_model", "batching"];

function leverRank(value: string): number {
  const rank = LEVER_ORDER.indexOf(value);
  return rank === -1 ? 99 : rank;
}

function qualityValue(value: string | number | null | undefined): string | null {
  const n = num(value);
  if (n === null) return null;
  const percent = `${n > 0 ? "+" : ""}${n.toFixed(1)}%`;
  return `${percent} (within tolerance)`;
}

function bestActionImpact(dashboard: Dashboard | null, fallback: number | null): number | null {
  return positive(dashboard?.top_waste_now?.estimated_monthly_savings_usd) ?? fallback;
}

function openOpportunityNet(proofSavings: ProofSavings | null): number | null {
  return positive(proofSavings?.estimated.open_opportunity_net_usd);
}

function leverRows(levers: LeverConfig[] | null | undefined): DashboardLeverRow[] {
  const rows = [...(levers ?? [])]
    .map((lever) => ({
      enabled: lever.enabled,
      impactValue: num(lever.savings_to_date_usd) ?? 0,
      lever: leverLabel(lever.lever),
      rank: leverRank(lever.lever),
      status: lever.enabled ? "Active" : "Off",
    }))
    .sort((a, b) => Number(b.enabled) - Number(a.enabled) || b.impactValue - a.impactValue || a.rank - b.rank);
  const total = rows.reduce((sum, lever) => sum + Math.max(0, lever.impactValue), 0);
  return rows.map((lever) => ({
    enabled: lever.enabled,
    impactValue: lever.impactValue,
    lever: lever.lever,
    share: total > 0 ? Math.max(0, lever.impactValue) / total : null,
    status: lever.status,
  }));
}

function proofTrustMetrics({
  dataQuality,
  levers,
  overview,
  proofSavings,
}: {
  dataQuality: ProofDataQuality | null;
  levers: LeverConfig[] | null | undefined;
  overview: MetricsOverview | null;
  proofSavings: ProofSavings | null;
}): DashboardViewModel["proofTrust"]["metrics"] {
  const qualityDeltas = (levers ?? []).map((lever) => num(lever.quality_delta_percent)).filter((value) => value !== null);
  const worstQuality = qualityDeltas.length ? Math.min(...qualityDeltas) : null;
  const qualityLabel =
    worstQuality === null
      ? "No drift reported"
      : `${worstQuality > 0 ? "+" : ""}${worstQuality.toFixed(1)}% worst delta`;

  return [
    {
      label: "Pricing coverage",
      value: pricingCoverage(dataQuality),
      kind: "percent",
    },
    {
      label: "Authoritative spend share",
      value: num(overview?.authoritative_spend_share_month),
      kind: "percent",
    },
    {
      label: "Holdback A/B",
      value: proofSavings?.verified?.holdback_has_signal ? "Signal active" : "Collecting",
      kind: "text",
    },
    {
      label: "Quality drift",
      value: qualityLabel,
      kind: "text",
      tone: worstQuality === null || worstQuality >= -1 ? "positive" : undefined,
    },
  ];
}

function proofTrustNote(score: number | null): string {
  if (score === null) {
    return "Based on pricing coverage, metadata completeness, and available measurement signals.";
  }
  return "Based on measurement completeness, pricing-source authority, and available holdback evidence.";
}

function emptyModel({
  dataQuality,
  levers,
  overview,
  proofSavings,
  trustScore,
}: {
  dataQuality: ProofDataQuality | null;
  levers: LeverConfig[] | null | undefined;
  overview: MetricsOverview | null;
  proofSavings: ProofSavings | null;
  trustScore: number | null;
}): DashboardViewModel {
  return {
    accountingMetrics: [
      { label: "Net saved", value: null, kind: "money", detail: "Awaiting traffic", tone: "brand" },
      { label: "Gross saved", value: null, kind: "money", detail: "No baseline yet" },
      { label: "Counterfactual spend", value: null, kind: "money", detail: "No counterfactual yet" },
      { label: "Actual spend", value: null, kind: "money", detail: "No observed spend yet" },
    ],
    comparison: null,
    headline: "No traffic yet",
    headlineValue: null,
    levers: leverRows(levers),
    leversRunning: (levers ?? []).filter((lever) => lever.enabled).length,
    mode: "empty",
    nextAction: {
      body: "Connect a provider and send your first request to unlock this view.",
      href: "/onboarding",
      impactLabel: null,
      impactValue: null,
      label: "Finish setup",
      qualityLabel: null,
      qualityValue: null,
      title: "Finish setup",
    },
    proofTrust: {
      note: proofTrustNote(trustScore),
      score: trustScore,
      metrics: proofTrustMetrics({ dataQuality, levers, overview, proofSavings }),
    },
    statusLabel: "Awaiting traffic",
    subheading: "Once requests route through Varsten, we'll measure your spend and surface estimated opportunities here.",
  };
}

interface DashboardBuildInput {
  dashboard: Dashboard | null;
  dataQuality: ProofDataQuality | null;
  isPerformance: boolean;
  levers?: LeverConfig[] | null;
  overview: MetricsOverview | null;
  proofSavings: ProofSavings | null;
}

interface DashboardBuildContext extends DashboardBuildInput {
  allLeverRows: DashboardLeverRow[];
  opportunityNet: number | null;
  requests: number;
  runningLevers: number;
  spendMonth: number;
  topWaste: Dashboard["top_waste_now"];
  topWasteQuality: string | null;
  trustScore: number | null;
}

function proofTrust(ctx: DashboardBuildContext): DashboardViewModel["proofTrust"] {
  return {
    note: proofTrustNote(ctx.trustScore),
    score: ctx.trustScore,
    metrics: proofTrustMetrics({
      dataQuality: ctx.dataQuality,
      levers: ctx.levers,
      overview: ctx.overview,
      proofSavings: ctx.proofSavings,
    }),
  };
}

function sharedFields(ctx: DashboardBuildContext, mode: SavingsMode) {
  return {
    levers: ctx.allLeverRows,
    leversRunning: ctx.runningLevers,
    mode,
    proofTrust: proofTrust(ctx),
  };
}

function openOpportunityTitle(opportunityNet: number | null): string {
  if (!opportunityNet) return "Review remaining optimization opportunities.";
  return `${Math.round(opportunityNet).toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 })} in open estimated opportunity remains.`;
}

function verifiedModel(ctx: DashboardBuildContext): DashboardViewModel | null {
  if (!ctx.isPerformance || !ctx.proofSavings?.verified) return null;
  const verifiedGross = num(ctx.proofSavings.verified.verified_savings_usd);
  const verifiedNet = num(ctx.proofSavings.verified.verified_net_usd);
  const counterfactual = num(ctx.proofSavings.counterfactual_spend_usd);
  const actual = num(ctx.proofSavings.actual_spend_usd);
  if (verifiedGross === null || verifiedNet === null || counterfactual === null || actual === null) return null;
  const comparison = {
    withoutLabel: "Counterfactual",
    withLabel: "Actual",
    withoutValue: counterfactual,
    withValue: actual,
    gapValue: verifiedGross,
    netValue: verifiedNet,
  };
  return {
    ...sharedFields(ctx, "verified"),
    accountingMetrics: [
      { label: "Net saved", value: verifiedNet, kind: "money", detail: "Verified after Varsten share", tone: "brand" },
      { label: "Gross saved", value: verifiedGross, kind: "money", detail: "Verified before Varsten share" },
      { label: "Counterfactual spend", value: comparison.withoutValue, kind: "money", detail: "Direct from Proof comparison" },
      { label: "Actual spend", value: comparison.withValue, kind: "money", detail: "Observed optimized spend" },
    ],
    comparison,
    headline: "Verified savings:",
    headlineSuffix: " this month",
    headlineValue: verifiedNet,
    nextAction: {
      body: ctx.topWaste ? `${ctx.topWaste.title} is ready to review in Engine.` : "Review remaining recommendations in Engine.",
      href: "/engine/recommendations",
      impactLabel: "Estimated monthly impact",
      impactValue: bestActionImpact(ctx.dashboard, ctx.opportunityNet),
      label: "Review opportunities",
      qualityLabel: "Quality drift",
      qualityValue: ctx.topWasteQuality ?? "Within tolerance",
      title: openOpportunityTitle(ctx.opportunityNet),
    },
    statusLabel: "Verified - measured from the ledger",
    subheading: "Measured from the ledger, including holdback A/B where available. You only pay on verified savings.",
  };
}

function estimatedModel(ctx: DashboardBuildContext): DashboardViewModel | null {
  const estimatedGross = num(ctx.proofSavings?.estimated.gross_savings_usd);
  const estimatedNet = num(ctx.proofSavings?.estimated.net_savings_usd);
  const estimatedCounterfactual = num(ctx.proofSavings?.estimated.counterfactual_spend_usd);
  const observedSpend = num(ctx.proofSavings?.observed_spend_usd ?? ctx.proofSavings?.actual_spend_usd);
  if (!ctx.isPerformance || estimatedGross === null || estimatedNet === null || estimatedCounterfactual === null || observedSpend === null) return null;
  const comparison = {
    withoutLabel: "Counterfactual",
    withLabel: "Actual",
    withoutValue: estimatedCounterfactual,
    withValue: observedSpend,
    gapValue: estimatedGross,
    netValue: estimatedNet,
  };
  return {
    ...sharedFields(ctx, "estimated"),
    accountingMetrics: [
      { label: "Net saved", value: estimatedNet, kind: "money", detail: "Estimated after Varsten share", tone: "brand" },
      { label: "Gross saved", value: estimatedGross, kind: "money", detail: "Estimated before Varsten share" },
      { label: "Counterfactual spend", value: estimatedCounterfactual, kind: "money", detail: "Direct from Proof estimate" },
      { label: "Actual spend", value: observedSpend, kind: "money", detail: "Observed optimized spend" },
    ],
    comparison,
    headline: "Estimated impact under measurement",
    headlineValue: null,
    nextAction: {
      body: `${ctx.requests.toLocaleString("en-US")} requests are running under measurement. Check Proof for early results.`,
      href: "/proof/savings",
      impactLabel: "Estimated monthly impact",
      impactValue: estimatedNet,
      label: "View proof",
      qualityLabel: "Quality drift",
      qualityValue: ctx.topWasteQuality ?? "Within tolerance",
      title: "Let the proof mature",
    },
    statusLabel: "Measuring - changes are live",
    subheading: "Changes are live. We're measuring actual savings against a counterfactual.",
  };
}

function projectedModel(ctx: DashboardBuildContext): DashboardViewModel | null {
  const forecast = positive(ctx.overview?.monthly_forecast_usd);
  const opportunityGross = positive(ctx.proofSavings?.estimated.open_opportunity_gross_usd ?? ctx.proofSavings?.estimated.open_opportunity_usd);
  if (ctx.isPerformance || forecast === null || opportunityGross === null || ctx.opportunityNet === null) return null;
  const comparison = {
    withoutLabel: "Observed forecast",
    withLabel: "Projected with Varsten",
    withoutValue: forecast,
    withValue: Math.max(0, forecast - opportunityGross),
    gapValue: opportunityGross,
    netValue: ctx.opportunityNet,
  };
  return {
    ...sharedFields(ctx, "projected"),
    accountingMetrics: [
      { label: "Monthly spend (measured)", value: ctx.spendMonth, kind: "money", detail: "Based on observed traffic" },
      { label: "Estimated opportunity", value: ctx.opportunityNet, kind: "money", detail: "Projected net after Varsten share", tone: "brand" },
      { label: "Requests (30d)", value: ctx.requests, kind: "compact", detail: "Observed this month" },
      { label: "Pricing coverage", value: pricingCoverage(ctx.dataQuality), kind: "percent", detail: "Priced events in the ledger" },
    ],
    comparison,
    headline: "Estimated opportunity:",
    headlineSuffix: "/mo",
    headlineValue: ctx.opportunityNet,
    nextAction: {
      body: ctx.topWaste ? `${ctx.topWaste.title} is ready to review in Engine.` : "Review your top estimated opportunities in Engine.",
      href: "/engine/recommendations",
      impactLabel: "Estimated monthly impact",
      impactValue: bestActionImpact(ctx.dashboard, ctx.opportunityNet),
      label: "View recommendations",
      qualityLabel: "Quality drift",
      qualityValue: ctx.topWasteQuality ?? "Awaiting eval",
      title: "Review your top estimated opportunities.",
    },
    statusLabel: "Projected - observe-only",
    subheading: "Based on observed traffic. Nothing has changed in production.",
  };
}

function fallbackModel(ctx: DashboardBuildContext): DashboardViewModel {
  const fallback = emptyModel({
    dataQuality: ctx.dataQuality,
    levers: ctx.levers,
    overview: ctx.overview,
    proofSavings: ctx.proofSavings,
    trustScore: ctx.trustScore,
  });
  return {
    ...fallback,
    headline: ctx.isPerformance
      ? "Estimated impact under measurement"
      : "Estimated opportunity pending",
    mode: ctx.isPerformance ? "estimated" : "projected",
    nextAction: {
      ...fallback.nextAction,
      body: ctx.isPerformance
        ? "Check Engine for active levers and recommendations while the Dashboard waits for measured savings."
        : "Open Engine to see what Varsten has learned from observe-only traffic.",
      href: "/engine/recommendations",
      label: "Open Engine",
      title: ctx.isPerformance ? "Review optimization status" : "Review recommendations",
    },
    statusLabel: ctx.isPerformance ? "Measuring" : "Projected opportunity pending",
    subheading: ctx.isPerformance
      ? "Changes are live. Verified savings will appear when measurement completes."
      : "Varsten is observing traffic. Projected savings will appear as recommendations mature.",
  };
}

function buildContext(input: DashboardBuildInput, requests: number, trustScore: number | null, spendMonth: number): DashboardBuildContext {
  const { dashboard, levers, proofSavings } = input;
  return {
    ...input,
    allLeverRows: leverRows(levers),
    opportunityNet: openOpportunityNet(proofSavings),
    requests,
    runningLevers: (levers ?? []).filter((lever) => lever.enabled).length,
    spendMonth,
    topWaste: dashboard?.top_waste_now ?? dashboard?.decision_queue?.[0] ?? null,
    topWasteQuality: qualityValue((dashboard?.top_waste_now ?? dashboard?.decision_queue?.[0] ?? null)?.quality_delta_percent),
    trustScore,
  };
}

export function buildDashboardViewModel(input: DashboardBuildInput): DashboardViewModel {
  const requests = input.dashboard?.requests_month ?? input.overview?.requests_month ?? 0;
  const trustScore = num(input.dataQuality?.trust_score ?? input.dashboard?.live_savings.trust_score);
  const spendMonth = num(input.overview?.spend_month);

  if (requests <= 0 || spendMonth === null) {
    return emptyModel({
      dataQuality: input.dataQuality,
      levers: input.levers,
      overview: input.overview,
      proofSavings: input.proofSavings,
      trustScore,
    });
  }

  const ctx = buildContext(input, requests, trustScore, spendMonth);
  return verifiedModel(ctx) ?? estimatedModel(ctx) ?? projectedModel(ctx) ?? fallbackModel(ctx);
}
