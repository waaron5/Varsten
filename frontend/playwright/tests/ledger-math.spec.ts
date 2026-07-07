import { expect, test } from "playwright/test";
import {
  API_BASE,
  createDashboardSnapshot,
  createMockState,
  createProofSavings,
  createUsageEvent,
  installMockApi,
  moneyNumber,
  watchClientErrors,
} from "./support/mockApi";

test("verified and net savings reconcile after a high-volume proxy burst", async ({ page }) => {
  const directMeasured = 1200;
  const holdbackMeasured = 800;
  const verifiedSavings = directMeasured + holdbackMeasured;
  const serviceFee = 500;
  const netCustomerSavings = verifiedSavings - serviceFee;
  const burstSize = 125;

  const state = createMockState({
    dashboardSnapshot: createDashboardSnapshot({
      gross_savings_usd: String(verifiedSavings),
      kpis: [
        {
          key: "net_saved",
          label: "Net Realized Savings",
          detail: "Verified savings retained after Varsten's performance fee.",
          value: String(netCustomerSavings),
          delta: { current: String(netCustomerSavings), previous: "0.00", delta_pct: "1.00" },
          tone: "brand",
        },
        {
          key: "gross_saved",
          label: "Gross Savings",
          detail: "Total cost eliminated before the performance fee is applied.",
          value: String(verifiedSavings),
          delta: { current: String(verifiedSavings), previous: "0.00", delta_pct: "1.00" },
          tone: null,
        },
        {
          key: "without_varsten",
          label: "Baseline Cost",
          detail: "Projected spend at provider list pricing, without Varsten.",
          value: "8000.00",
          delta: { current: "8000.00", previous: "7600.00", delta_pct: "0.0526" },
          tone: null,
        },
        {
          key: "actual_spend",
          label: "Actual Spend",
          detail: "Amount paid directly to providers this period.",
          value: "6000.00",
          delta: { current: "6000.00", previous: "6000.00", delta_pct: "0" },
          tone: null,
        },
      ],
      proof_trust: {
        score: "0.99",
        confidence_level: "high",
        confidence_label: "High Confidence",
        confidence_note: "Every figure is audit-ready.",
        pricing_coverage: "1.00",
        attribution_share: "1.00",
        verified_savings_usd: String(verifiedSavings),
        claimed_savings_usd: String(verifiedSavings),
        measured_share: "1.00",
        measurement_method_label: "Ledger + holdback",
        has_direct_ledger: true,
        has_ab_holdback: true,
      },
    }),
    proofSavings: createProofSavings({
      verified: {
        label: "Verified savings, measured from the ledger",
        direct_measured_usd: String(directMeasured),
        holdback_measured_usd: String(holdbackMeasured),
        holdback_ci_low_usd: "700.00",
        holdback_ci_high_usd: "900.00",
        holdback_has_signal: true,
        verified_savings_usd: String(verifiedSavings),
        verified_fee_usd: String(serviceFee),
        verified_net_usd: String(netCustomerSavings),
        billable_savings_usd: String(verifiedSavings),
      },
      gross_savings_usd: String(verifiedSavings),
      varsten_fee_usd: String(serviceFee),
      net_savings_usd: String(netCustomerSavings),
      estimated: {
        label: "Estimated impact of applied optimizations (modeled, not measured)",
        gross_savings_usd: String(verifiedSavings),
        net_savings_usd: String(netCustomerSavings),
        varsten_fee_usd: String(serviceFee),
        counterfactual_spend_usd: "8000.00",
        open_opportunity_usd: "0.00",
        open_opportunity_gross_usd: "0.00",
        open_opportunity_fee_usd: "0.00",
        open_opportunity_net_usd: "0.00",
      },
    }),
  });

  state.proxyHandler = (_request, body, mockState) => {
    const index = mockState.calls.proxy;
    const event = createUsageEvent({
      id: `evt_burst_${String(index).padStart(3, "0")}`,
      provider: "openai",
      model: String(body.model ?? "gpt-4o-mini"),
      input_tokens: 1800,
      output_tokens: 420,
      total_tokens: 2220,
      cost_usd: "0.024000",
      metadata: {
        proxy: true,
        saved_usd: index % 2 === 0 ? "9.60" : "6.40",
        burst: true,
      },
    });
    (mockState.usageEvents.items as Record<string, unknown>[]).unshift(event);

    return {
      status: 200,
      headers: {
        "x-varsten-mode": "optimize",
        "x-varsten-request-id": String(event.id),
      },
      body: {
        id: `chatcmpl_burst_${index}`,
        object: "chat.completion",
        created: 1782241200,
        model: event.model as string,
        choices: [{ index: 0, message: { role: "assistant", content: "ok" }, finish_reason: "stop" }],
        usage: { prompt_tokens: 1800, completion_tokens: 420, total_tokens: 2220 },
      },
    };
  };

  const clientErrors = watchClientErrors(page);
  await installMockApi(page, state);

  await page.goto("/dashboard");
  await expect(page.getByText("Verified savings", { exact: true })).toBeVisible();

  const statuses = await page.evaluate(async ({ apiBase, count }) => {
    const requests = Array.from({ length: count }, (_, index) =>
      fetch(`${apiBase}/v1/chat/completions`, {
        method: "POST",
        headers: {
          authorization: "Bearer vk_test_e2e_burst",
          "content-type": "application/json",
        },
        body: JSON.stringify({
          model: "gpt-4o-mini",
          messages: [{ role: "user", content: `Burst request ${index}` }],
        }),
      }).then((response) => response.status),
    );
    return Promise.all(requests);
  }, { apiBase: API_BASE, count: burstSize });

  expect(statuses).toHaveLength(burstSize);
  expect(statuses.every((status) => status === 200)).toBe(true);
  expect(state.calls.proxy).toBe(burstSize);

  const verifiedDashboardMetric = page.locator(".dash-proof-metric").filter({ hasText: "Verified savings" });
  await expect(verifiedDashboardMetric).toContainText("$2,000 of $2,000");

  await page.goto("/proof/savings");
  const grossCard = page.locator(".card.kpi").filter({ hasText: "Gross saved" });
  const netCard = page.locator(".card.kpi").filter({ hasText: "Net to customer" });

  await expect(grossCard.locator(".value")).toHaveText("$2,000");
  await expect(netCard.locator(".value")).toHaveText("$1,500");
  await expect(netCard.locator(".foot")).toHaveText("after $500 Varsten fee");

  const proof = await page.evaluate(async (apiBase) => {
    const response = await fetch(`${apiBase}/v1/proof/savings?project_id=proj_e2e_production`, {
      headers: { authorization: "Bearer e2e-control-plane-token" },
    });
    return response.json();
  }, API_BASE);

  const exactVerified =
    Number(proof.verified.direct_measured_usd) + Number(proof.verified.holdback_measured_usd);
  const exactNet = Number(proof.gross_savings_usd) - Number(proof.varsten_fee_usd);

  expect(Number(proof.verified.verified_savings_usd)).toBe(exactVerified);
  expect(Number(proof.net_savings_usd)).toBe(exactNet);
  expect(moneyNumber(await grossCard.locator(".value").innerText())).toBe(exactVerified);
  expect(moneyNumber(await netCard.locator(".value").innerText())).toBe(exactNet);
  expect(clientErrors).toEqual([]);
});
