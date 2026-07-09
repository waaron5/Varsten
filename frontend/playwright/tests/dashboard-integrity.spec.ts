import { expect, test } from "playwright/test";
import {
  createDashboardSnapshot,
  createMockState,
  installMockApi,
  watchClientErrors,
} from "./support/mockApi";

test("data integrity card shows no score and no checkmark when there is no measured savings", async ({ page }) => {
  const state = createMockState({
    dashboardSnapshot: createDashboardSnapshot({
      // Traffic has flowed (grid renders), but nothing measured yet — the proof
      // card must degrade to "No score" rather than fabricate confidence.
      mode: "spend_only",
      gross_savings_usd: null,
      proof_trust: {
        score: null,
        confidence_level: "none",
        confidence_label: "No score",
        confidence_note: "No requests have run through Varsten in this period, so there is no integrity score yet.",
        pricing_coverage: null,
        attribution_share: null,
        verified_savings_usd: null,
        claimed_savings_usd: null,
        measured_share: null,
        measurement_method_label: "Not yet active",
        has_direct_ledger: false,
        has_ab_holdback: false,
      },
    }),
  });
  const clientErrors = watchClientErrors(page);
  await installMockApi(page, state);

  await page.goto("/dashboard");

  const card = page.locator(".lv-integrity-panel");
  await expect(card.getByText("No score", { exact: true })).toBeVisible();
  await expect(card.getByText("no integrity score")).toBeVisible();
  await expect(card.getByText("High Confidence")).toHaveCount(0);
  await expect(card.getByText("✓")).toHaveCount(0);
  expect(clientErrors).toEqual([]);
});

test("high confidence checkmark requires a real score and measured signal", async ({ page }) => {
  const state = createMockState({
    dashboardSnapshot: createDashboardSnapshot({
      mode: "spend_only",
      gross_savings_usd: null,
      proof_trust: {
        score: null,
        confidence_level: "high",
        confidence_label: "High Confidence",
        confidence_note: "Backend confidence is inconsistent without a proof score.",
        pricing_coverage: null,
        attribution_share: null,
        verified_savings_usd: null,
        claimed_savings_usd: null,
        measured_share: null,
        measurement_method_label: "Not yet active",
        has_direct_ledger: false,
        has_ab_holdback: false,
      },
    }),
  });
  const clientErrors = watchClientErrors(page);
  await installMockApi(page, state);

  await page.goto("/dashboard");

  const card = page.locator(".lv-integrity-panel");
  await expect(card.getByText("High Confidence", { exact: true })).toBeVisible();
  await expect(card.getByText("✓")).toHaveCount(0);
  await expect(card.locator(".lv-trust-badge").first()).toHaveText("Unknown");
  expect(clientErrors).toEqual([]);
});

test("no-traffic dashboard shows a focused waiting state, not a grid of blanks", async ({ page }) => {
  const state = createMockState({
    dashboardSnapshot: createDashboardSnapshot({ mode: "empty" }),
  });
  const clientErrors = watchClientErrors(page);
  await installMockApi(page, state);

  await page.goto("/dashboard");

  await expect(page.getByRole("heading", { name: "Waiting for your first request" })).toBeVisible();
  await expect(page.getByRole("link", { name: "View setup steps" })).toHaveAttribute("href", "/onboarding");
  await expect(page.getByText(/Listening for your first request/)).toBeVisible();

  // The dead panel grid is replaced entirely, not stacked under a banner.
  await expect(page.locator(".lv-kpi-strip")).toHaveCount(0);
  await expect(page.locator(".lv-integrity-panel")).toHaveCount(0);
  expect(clientErrors).toEqual([]);
});

test("malformed trend values do not render as zero-dollar chart data", async ({ page }) => {
  const state = createMockState({
    dashboardSnapshot: createDashboardSnapshot({
      savings_trend: [
        { date: "2026-06-21", optimized_usd: "not-a-number", saved_usd: "also-invalid", baseline_usd: "2500.00" },
      ],
      trend_stats: {
        avg_spend_per_bucket_usd: null,
        avg_saved_per_bucket_usd: null,
        effective_savings_rate: null,
      },
    }),
  });
  const clientErrors = watchClientErrors(page);
  await installMockApi(page, state);

  await page.goto("/dashboard");

  const panel = page.locator(".lv-daily-panel");
  await expect(panel.getByText("Savings trend is unavailable for this period.")).toBeVisible();
  await expect(panel.locator(".lv-svg-chart")).toHaveCount(0);
  expect(clientErrors).toEqual([]);
});

test("nonzero sub-dollar dashboard values render as cents instead of zero dollars", async ({ page }) => {
  const state = createMockState({
    dashboardSnapshot: createDashboardSnapshot({
      gross_savings_usd: "0.02",
      verified_savings_usd: "0.02",
      verified_gross_savings_usd: "0.02",
      direct_measured_usd: "0.02",
      holdback_measured_usd: null,
      kpis: [
        {
          key: "net_saved",
          label: "Net Realized Savings",
          detail: "After optimization fee",
          value: "0.01",
          delta: { current: "0.01", previous: "10.00", delta_pct: "-0.9990" },
          tone: "brand",
        },
        {
          key: "gross_saved",
          label: "Gross Savings",
          detail: "Total cost eliminated pre-fee",
          value: "0.02",
          delta: { current: "0.02", previous: "20.00", delta_pct: "-0.9990" },
          tone: null,
        },
        {
          key: "without_varsten",
          label: "Baseline Cost",
          detail: "List-price spend without Varsten",
          value: "0.04",
          delta: { current: "0.04", previous: "40.00", delta_pct: "-0.9990" },
          tone: null,
        },
        {
          key: "actual_spend",
          label: "Actual Spend",
          detail: "Paid to providers this period",
          value: "0.02",
          delta: { current: "0.02", previous: "20.00", delta_pct: "-0.9990" },
          tone: null,
        },
      ],
      savings_trend: [
        { date: "2026-07-08", optimized_usd: "0.02", saved_usd: "0.02", baseline_usd: "0.04" },
      ],
      trend_stats: {
        avg_spend_per_bucket_usd: "0.02",
        avg_saved_per_bucket_usd: "0.02",
        effective_savings_rate: "0.5000",
      },
      levers: [
        {
          lever: "semantic_cache",
          label: "Semantic cache",
          enabled: true,
          status: "Active",
          value_usd: "0.02",
          share: "1.0000",
          source: "measured",
        },
      ],
      drivers: {
        actual_total_usd: "0.02",
        team: [
          { key: "growth", label: "growth", spend_usd: "0.00887030", share: "0.4435" },
          { key: "platform", label: "platform", spend_usd: "0.00719970", share: "0.3600" },
          { key: "support", label: "support", spend_usd: "0.00342270", share: "0.1711" },
        ],
        feature: [],
      },
      proof_trust: {
        score: "1.0000",
        confidence_level: "high",
        confidence_label: "High Confidence",
        confidence_note: "Numbers are suitable for board-level reporting and finance decisions.",
        pricing_coverage: "1.0000",
        attribution_share: "1.0000",
        verified_savings_usd: "0.02",
        claimed_savings_usd: "0.02",
        measured_share: "1.0000",
        measurement_method_label: "Direct ledger",
        has_direct_ledger: true,
        has_ab_holdback: false,
      },
    }),
  });
  const clientErrors = watchClientErrors(page);
  await installMockApi(page, state);

  await page.goto("/dashboard");

  await expect(page.locator(".lv-kpi-strip").getByText("$0.01", { exact: true })).toBeVisible();
  await expect(page.locator(".lv-kpi-strip").getByText("$0.04", { exact: true })).toBeVisible();
  await expect(page.locator(".lv-daily-stats").getByText("50.0%", { exact: true })).toBeVisible();
  await expect(page.locator(".lv-list-panel").first().getByText("$0.02", { exact: true })).toHaveCount(2);
  await expect(page.locator(".lv-list-panel").nth(1).getByText("<$0.01", { exact: true })).toBeVisible();
  await expect(page.getByText("$0 · $0 claimed", { exact: true })).toHaveCount(0);
  await expect(page.getByText("$0.02 · $0.02 claimed", { exact: true })).toBeVisible();
  expect(clientErrors).toEqual([]);
});

test("dashboard renders custom backend snapshot values, not Lovable fixtures", async ({ page }) => {
  const state = createMockState({
    dashboardSnapshot: createDashboardSnapshot({
      gross_savings_usd: "8888.00",
      kpis: [
        {
          key: "net_saved",
          label: "Net Realized Savings",
          detail: "Verified savings retained after optimization fee.",
          value: "7777.00",
          delta: { current: "7777.00", previous: "7000.00", delta_pct: "0.111" },
          tone: "brand",
        },
        {
          key: "gross_saved",
          label: "Gross Savings",
          detail: "Total cost eliminated before the performance fee is applied.",
          value: "8888.00",
          delta: { current: "8888.00", previous: "8000.00", delta_pct: "0.111" },
          tone: null,
        },
        {
          key: "without_varsten",
          label: "Baseline Cost",
          detail: "Projected spend at provider list pricing, without Varsten.",
          value: "9999.00",
          delta: { current: "9999.00", previous: "9000.00", delta_pct: "0.111" },
          tone: null,
        },
        {
          key: "actual_spend",
          label: "Actual Spend",
          detail: "Amount paid directly to providers this period.",
          value: "1234.00",
          delta: { current: "1234.00", previous: "1400.00", delta_pct: "-0.1186" },
          tone: null,
        },
      ],
    }),
  });
  const clientErrors = watchClientErrors(page);
  await installMockApi(page, state);

  await page.goto("/dashboard");

  await expect(page.locator(".lv-kpi-strip").getByText("$7,777", { exact: true })).toBeVisible();
  await expect(page.locator(".lv-kpi-strip").getByText("$8,888", { exact: true })).toBeVisible();
  await expect(page.locator(".lv-kpi-strip").getByText("$9,999", { exact: true })).toBeVisible();
  await expect(page.locator(".lv-kpi-strip").getByText("$1,234", { exact: true })).toBeVisible();
  await expect(page.getByText("Ada Lovelace")).toHaveCount(0);
  await expect(page.getByText("$42.2k")).toHaveCount(0);
  await expect(page.getByText("Maya Chen")).toBeVisible();
  await expect(page.getByText(/Maya AI Co · Optimize/)).toBeVisible();
  expect(clientErrors).toEqual([]);
});

test("period tabs refetch backend snapshots and export uses backend CSV", async ({ page }) => {
  const month = createDashboardSnapshot();
  const quarter = createDashboardSnapshot({
    period: "quarter",
    label: "Q2 2026",
    kpis: [
      {
        key: "net_saved",
        label: "Net Realized Savings",
        detail: "Verified savings retained after optimization fee.",
        value: "3210.00",
        delta: { current: "3210.00", previous: "3000.00", delta_pct: "0.07" },
        tone: "brand",
      },
      ...((month.kpis as Record<string, unknown>[]).slice(1)),
    ],
  });
  const state = createMockState({
    dashboardSnapshot: month,
    dashboardSnapshotsByPeriod: {
      month,
      quarter,
      year: createDashboardSnapshot({ period: "year", label: "2026" }),
    },
    dashboardExportCsv: "Varsten dashboard export\nperiod,quarter\nfrom,backend\n",
  });
  const clientErrors = watchClientErrors(page);
  await installMockApi(page, state);

  await page.goto("/dashboard");
  await page.getByRole("tab", { name: "Quarter" }).click();

  await expect(page.locator(".lv-kpi-strip").getByText("$3,210", { exact: true })).toBeVisible();
  expect(state.calls["dashboardSnapshot:quarter"]).toBeGreaterThanOrEqual(1);

  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export CSV" }).click();
  await downloadPromise;

  expect(state.calls.dashboardExport).toBe(1);
  expect(state.calls["dashboardExport:quarter"]).toBe(1);
  expect(clientErrors).toEqual([]);
});

test("non-dashboard pages render inside the new global shell without overlap", async ({ page }) => {
  const state = createMockState();
  const clientErrors = watchClientErrors(page);
  await installMockApi(page, state);

  await page.goto("/upgrade");

  await expect(page.locator(".lv-sidebar")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Optimize Trial Active" })).toBeVisible();

  const sidebar = await page.locator(".lv-sidebar").boundingBox();
  const content = await page.locator(".content").boundingBox();
  expect(sidebar).not.toBeNull();
  expect(content).not.toBeNull();
  expect(content!.x).toBeGreaterThanOrEqual(sidebar!.x + sidebar!.width - 1);
  expect(clientErrors).toEqual([]);
});
