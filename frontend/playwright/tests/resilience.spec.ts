import { expect, test } from "playwright/test";
import {
  API_BASE,
  createDashboardSnapshot,
  createMockState,
  createUsageEvent,
  installMockApi,
  watchClientErrors,
} from "./support/mockApi";

test("upstream 502 chaos routes to a safe downshift path and leaves the UI stable", async ({ page }) => {
  const state = createMockState({
    dashboardSnapshot: createDashboardSnapshot({
      gross_savings_usd: "72.00",
      kpis: [
        {
          key: "net_saved",
          label: "Net Realized Savings",
          detail: "Verified savings retained after Varsten's performance fee.",
          value: "54.00",
          delta: { current: "54.00", previous: "0.00", delta_pct: "1.00" },
          tone: "brand",
        },
        {
          key: "gross_saved",
          label: "Gross Savings",
          detail: "Total cost eliminated before the performance fee is applied.",
          value: "72.00",
          delta: { current: "72.00", previous: "0.00", delta_pct: "1.00" },
          tone: null,
        },
        {
          key: "without_varsten",
          label: "Baseline Cost",
          detail: "Projected spend at provider list pricing, without Varsten.",
          value: "420.00",
          delta: { current: "420.00", previous: "420.00", delta_pct: "0" },
          tone: null,
        },
        {
          key: "actual_spend",
          label: "Actual Spend",
          detail: "Amount paid directly to providers this period.",
          value: "348.00",
          delta: { current: "348.00", previous: "420.00", delta_pct: "-0.1714" },
          tone: null,
        },
      ],
      levers: [
        {
          lever: "model_downshift",
          label: "Model downshift",
          enabled: true,
          status: "Active",
          value_usd: "72.00",
          share: "1.00",
          source: "measured",
        },
      ],
      proof_trust: {
        score: "0.97",
        confidence_label: "High Confidence",
        confidence_note: "Every figure is audit-ready.",
        pricing_coverage: "1.00",
        attribution_share: "1.00",
        verified_savings_usd: "72.00",
        claimed_savings_usd: "72.00",
        measured_share: "1.00",
        measurement_method_label: "Ledger + holdback",
        has_direct_ledger: true,
        has_ab_holdback: false,
      },
    }),
  });
  state.proxyHandler = (_request, body, mockState) => {
    mockState.upstreamFailures.push({
      provider: "openai",
      model: body.model,
      status: 502,
      reason: "simulated upstream provider outage",
    });

    const event = createUsageEvent({
      provider: "anthropic",
      model: "claude-3-5-haiku-20241022",
      cost_usd: "0.006000",
      metadata: {
        proxy: true,
        routed: true,
        routed_from: "gpt-4o",
        routed_from_provider: "openai",
        routed_to: "claude-3-5-haiku-20241022",
        routed_to_provider: "anthropic",
        upstream_failure_status: 502,
      },
    });
    (mockState.usageEvents.items as Record<string, unknown>[]).unshift(event);

    return {
      status: 200,
      headers: {
        "x-varsten-mode": "optimize",
        "x-varsten-routed": "openai:gpt-4o -> anthropic:claude-3-5-haiku-20241022",
        "x-varsten-request-id": String(event.id),
      },
      body: {
        id: "chatcmpl_e2e_downshift",
        object: "chat.completion",
        created: 1782241200,
        model: "claude-3-5-haiku-20241022",
        choices: [{ index: 0, message: { role: "assistant", content: "fallback ok" }, finish_reason: "stop" }],
        usage: { prompt_tokens: 800, completion_tokens: 160, total_tokens: 960 },
      },
    };
  };

  const clientErrors = watchClientErrors(page);
  await installMockApi(page, state);

  await page.goto("/dashboard");
  const downshiftLever = page.locator(".dash-lever-item").filter({ hasText: "Model downshift" });
  await expect(downshiftLever).toBeVisible();
  await expect(downshiftLever.locator(".dash-lever-badge")).toHaveText("Active");

  const proxyResult = await page.evaluate(async (apiBase) => {
    const response = await fetch(`${apiBase}/v1/chat/completions`, {
      method: "POST",
      headers: {
        authorization: "Bearer vk_test_e2e_resilience",
        "content-type": "application/json",
      },
      body: JSON.stringify({
        model: "gpt-4o",
        messages: [{ role: "user", content: "Summarize a billing dispute." }],
      }),
    });
    return {
      status: response.status,
      routed: response.headers.get("x-varsten-routed"),
      body: await response.json(),
    };
  }, API_BASE);

  expect(proxyResult.status).toBe(200);
  expect(proxyResult.routed).toBe("openai:gpt-4o -> anthropic:claude-3-5-haiku-20241022");
  expect(proxyResult.body.model).toBe("claude-3-5-haiku-20241022");
  expect(state.upstreamFailures).toEqual([
    expect.objectContaining({ provider: "openai", status: 502 }),
  ]);

  const logPage = await page.evaluate(async (apiBase) => {
    const response = await fetch(`${apiBase}/v1/usage-events?project_id=proj_e2e_production&limit=5`, {
      headers: { authorization: "Bearer e2e-control-plane-token" },
    });
    return response.json();
  }, API_BASE);
  const [event] = logPage.items;
  expect(event.success).toBe(true);
  expect(event.error_code).toBeNull();
  expect(event.provider).toBe("anthropic");
  expect(event.metadata).toMatchObject({
    routed: true,
    routed_from_provider: "openai",
    routed_to_provider: "anthropic",
    upstream_failure_status: 502,
  });
  expect(clientErrors).toEqual([]);
});
