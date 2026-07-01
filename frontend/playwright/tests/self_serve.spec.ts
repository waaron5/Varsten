import { expect, test } from "playwright/test";
import {
  API_BASE,
  createEntitlements,
  createOnboardingStatus,
  createMockState,
  installMockApi,
  watchClientErrors,
} from "./support/mockApi";

// Free observe-only features (every behaviour-changing lever locked), for the
// upgrade-path tests where the workspace is NOT on Performance.
const FREE_FEATURES = {
  apply_recommendations: false,
  enable_levers: false,
  enable_routing: false,
  enable_caching: false,
  enable_trimming: false,
  use_batching: false,
  guardrail_automation: false,
  submit_batches: false,
  advanced_proof: false,
  advanced_reports: false,
  extended_retention: false,
};

function freeObserveOnly() {
  return createEntitlements({
    plan_tier: "free",
    observe_only: true,
    observe_only_reason: "free_plan",
    trial: { trial_ends_at: null, trial_expired: true },
    features: FREE_FEATURES,
  });
}

const openAiCardFor = (page: import("playwright/test").Page) =>
  page
    .getByRole("heading", { name: "OpenAI" })
    .locator("xpath=ancestor::div[contains(concat(' ', normalize-space(@class), ' '), ' card ')][1]");

test("self-serve: /start lands on onboarding with an active project and reaches the trial dashboard", async ({
  page,
}) => {
  // Default state mirrors a real signup: a Performance-trialing org that already
  // has a default Production project (no create-project dead-end).
  const state = createMockState();
  const clientErrors = watchClientErrors(page);
  await installMockApi(page, state);

  // 3-5. /start routes an unfinished onboarding straight into the funnel, which
  // opens on Connect Varsten because the project already exists.
  await page.goto("/start");
  await expect(page).toHaveURL(/\/onboarding/);
  await expect(page.getByRole("heading", { name: "Connect Varsten" })).toBeVisible();
  await expect(page.getByText("Create your first project")).toHaveCount(0);

  // 6. Varsten API key.
  await page.getByRole("button", { name: "Create API key" }).click();
  await expect(page.getByText("vk_test_e2e_first_request")).toBeVisible();

  // 7. Provider key connect.
  const openAiCard = openAiCardFor(page);
  await openAiCard.getByPlaceholder("sk-...").fill("sk-test-openai-provider-key");
  await openAiCard.getByRole("button", { name: "Connect" }).click();
  await expect(openAiCard.getByText("Connected")).toBeVisible();

  // 8. Copy the integration snippet -> onboarding event recorded.
  await page.getByRole("button", { name: "Copy snippet" }).click();
  await expect.poll(() => state.calls["event:snippet_viewed"] ?? 0).toBe(1);

  // 9. First gateway request (mocked through the proxy mock).
  await page.evaluate(async (apiBase) => {
    const response = await fetch(`${apiBase}/v1/chat/completions`, {
      method: "POST",
      headers: {
        authorization: "Bearer vk_test_e2e_first_request",
        "content-type": "application/json",
        "x-varsten-metadata": JSON.stringify({ environment: "production", feature: "support" }),
      },
      body: JSON.stringify({ model: "gpt-4o-mini", messages: [{ role: "user", content: "hello" }] }),
    });
    if (!response.ok) throw new Error(`proxy request failed: ${response.status}`);
  }, API_BASE);
  await expect(page.getByText("First request received. Varsten is observing your AI traffic.")).toBeVisible({
    timeout: 7000,
  });

  // 10. Continue -> dashboard_entered event + Performance dashboard renders.
  await page.getByRole("button", { name: "Continue to dashboard" }).click();
  await expect.poll(() => state.calls["event:dashboard_entered"] ?? 0).toBe(1);
  await expect(page).toHaveURL(/\/dashboard/);
  await expect(page.getByText("Net Realized Savings")).toBeVisible();
  expect(clientErrors).toEqual([]);
});

test("self-serve: trial start intent is preserved and shows Performance onboarding copy", async ({ page }) => {
  const state = createMockState();
  await installMockApi(page, state);

  await page.goto("/start?intent=trial");
  await expect.poll(() => state.calls["authSync:trial"] ?? 0).toBeGreaterThanOrEqual(1);
  await expect(page).toHaveURL(/\/onboarding/);
  await expect(page.getByText("Connect Varsten with Performance access")).toBeVisible();
  await expect(page.getByText(/Varsten is observing only/)).toHaveCount(0);
});

test("self-serve: observe-only start intent is preserved and shows Free onboarding copy", async ({ page }) => {
  const state = createMockState({
    onboarding: createOnboardingStatus({ plan_tier: "free", observe_only: true }),
    entitlements: freeObserveOnly(),
  });
  await installMockApi(page, state);

  await page.goto("/start?intent=observe");
  await expect.poll(() => state.calls["authSync:observe"] ?? 0).toBeGreaterThanOrEqual(1);
  await expect(page).toHaveURL(/\/onboarding/);
  await expect(page.getByText("Connect Varsten in observe-only mode")).toBeVisible();
  await expect(page.getByText(/Varsten is observing only/)).toBeVisible();
});

test("self-serve: trial mode shows Performance unlocked with a trial end date", async ({ page }) => {
  const state = createMockState(); // Performance + trial active
  await installMockApi(page, state);
  await page.goto("/upgrade");
  await expect(page.getByRole("heading", { name: "You're on Performance" })).toBeVisible();
  await expect(page.getByText("Trial ends")).toBeVisible();
});

test("self-serve: upgrade is a contact path when billing is disabled", async ({ page }) => {
  const state = createMockState({ entitlements: freeObserveOnly(), billingEnabled: false });
  await installMockApi(page, state);
  await page.goto("/upgrade");

  const upgrade = page.getByRole("button", { name: "Add payment method & activate Performance" });
  await expect(upgrade).toBeVisible();
  await upgrade.click();
  await expect(page.getByText(/Self-serve checkout is not available yet/)).toBeVisible();
  expect(state.calls.billingCheckout).toBe(1);
});

test("self-serve: upgrade starts Stripe checkout when billing is enabled", async ({ page }) => {
  const state = createMockState({ entitlements: freeObserveOnly(), billingEnabled: true });
  await installMockApi(page, state);
  await page.goto("/upgrade");

  await page.getByRole("button", { name: "Add payment method & activate Performance" }).click();
  await expect.poll(() => state.calls.billingCheckout ?? 0).toBe(1);
  // The client redirects to the URL returned by the checkout endpoint.
  await expect(page).toHaveURL(/checkout=stripe-redirect/);
});
