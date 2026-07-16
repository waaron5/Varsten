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
// upgrade-path tests where the workspace is NOT on Optimize.
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
    subscription_status: "active",
    observe_only: true,
    observe_only_reason: "free_plan",
    trial: {
      trial_ends_at: null,
      trial_expired: false,
      payment_method_ready: false,
      payment_method_ready_at: null,
    },
    features: FREE_FEATURES,
  });
}

function expiredObserveOnly() {
  return createEntitlements({
    plan_tier: "free",
    subscription_status: "expired",
    observe_only: true,
    observe_only_reason: "trial_expired",
    trial: {
      trial_ends_at: "2026-07-07T19:00:00.000Z",
      trial_expired: true,
      payment_method_ready: false,
      payment_method_ready_at: null,
    },
    features: FREE_FEATURES,
  });
}

test("self-serve: /start lands on onboarding with an active project and reaches the trial dashboard", async ({
  page,
}) => {
  // Default state mirrors a real signup: an Optimize-trialing org that already
  // has a default Production project (no create-project dead-end).
  const state = createMockState();
  const clientErrors = watchClientErrors(page);
  await installMockApi(page, state);

  // 3-5. /start routes an unfinished onboarding straight into the funnel, which
  // opens on the stack chooser because the project already exists.
  await page.goto("/start");
  await expect(page).toHaveURL(/\/onboarding/);
  await expect(page.getByRole("heading", { name: "Connect your stack" })).toBeVisible();
  await expect(page.getByText("Create your first project")).toHaveCount(0);
  await page.getByRole("button", { name: "Continue", exact: true }).click();

  // 6-7. Keys step: Varsten API key (plaintext shown exactly once) plus the
  // provider key. Continue stays locked until both exist.
  await expect(page.getByRole("heading", { name: "Add your keys" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Continue", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "Create API key" }).click();
  await expect(page.getByText("vk_test_e2e_first_request")).toBeVisible();

  await page.getByPlaceholder("sk-...").fill("sk-test-openai-provider-key");
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await expect(page.getByText(/Connected/)).toBeVisible();
  await page.getByRole("button", { name: "Continue", exact: true }).click();

  // 8. Copy the integration snippet -> onboarding event recorded. The default
  // path is the production fail-open SDK.
  await page.getByRole("button", { name: "Copy OpenAI SDK snippet" }).click();
  await expect.poll(() => state.calls["event:snippet_viewed"] ?? 0).toBe(1);
  await expect(page.getByRole("button", { name: "Waiting for verification" })).toBeDisabled();

  // 9. First gateway request (mocked through the proxy mock).
  await page.evaluate(async (apiBase) => {
    const response = await fetch(`${apiBase}/v1/chat/completions`, {
      method: "POST",
      headers: {
        authorization: "Bearer vk_test_e2e_first_request",
        "content-type": "application/json",
        "x-varsten-client": "@varsten/openai@0.1.0",
        "x-varsten-metadata": JSON.stringify({ environment: "production", feature: "support" }),
      },
      body: JSON.stringify({ model: "gpt-4o-mini", messages: [{ role: "user", content: "hello" }] }),
    });
    if (!response.ok) throw new Error(`proxy request failed: ${response.status}`);
  }, API_BASE);
  await expect(page.getByText("Verified live: first request received through the selected integration.")).toBeVisible({
    timeout: 7000,
  });

  // 10. Continue -> dashboard_entered event + Optimize dashboard renders.
  await page.getByRole("button", { name: "Finish setup" }).click();
  await expect.poll(() => state.calls["event:dashboard_entered"] ?? 0).toBe(1);
  await expect(page).toHaveURL(/\/dashboard/);
  await expect(page.getByText("Net Realized Savings")).toBeVisible();
  expect(clientErrors).toEqual([]);
});

test("self-serve: trial start intent is preserved and shows Optimize onboarding copy", async ({ page }) => {
  const state = createMockState();
  await installMockApi(page, state);

  await page.goto("/start?intent=trial");
  await expect.poll(() => state.calls["authSync:trial"] ?? 0).toBeGreaterThanOrEqual(1);
  await expect(page).toHaveURL(/\/onboarding/);
  await expect(page.getByText(/move up the ladder later without re-integrating/)).toBeVisible();
  await expect(page.getByText(/nothing changes in production/)).toHaveCount(0);
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
  await expect(page.getByText(/nothing changes in production/)).toBeVisible();
});

test("self-serve: trial mode shows Optimize unlocked with a trial end date", async ({ page }) => {
  const state = createMockState(); // Optimize + trial active
  await installMockApi(page, state);
  await page.goto("/upgrade");
  await expect(page.getByRole("heading", { name: "Optimize Trial Active" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Add payment method to continue after trial" })).toBeVisible();
  await expect(page.getByText("Trial ends")).toBeVisible();
  await expect(page.getByText("60 priced requests")).toBeVisible();
});

test("self-serve: payment-ready trial is distinct from paid active", async ({ page }) => {
  const state = createMockState({
    entitlements: createEntitlements({
      subscription_status: "trialing",
      trial: {
        trial_ends_at: "2026-07-07T19:00:00.000Z",
        trial_expired: false,
        payment_method_ready: true,
        payment_method_ready_at: "2026-06-24T12:00:00.000Z",
      },
    }),
  });
  await installMockApi(page, state);
  await page.goto("/upgrade");
  await expect(page.getByRole("heading", { name: "Payment Method Ready" })).toBeVisible();
  await expect(page.getByText(/continues on verified-savings pricing/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Manage payment method" })).toBeVisible();
});

test("self-serve: active and past-due billing states render distinct actions", async ({ page }) => {
  const state = createMockState({
    entitlements: createEntitlements({ subscription_status: "active" }),
    billingEnabled: true,
  });
  await installMockApi(page, state);
  await page.goto("/upgrade");
  await expect(page.getByRole("heading", { name: "Optimize Active" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Manage billing" })).toBeVisible();

  state.entitlements = createEntitlements({
    subscription_status: "past_due",
    observe_only: true,
    observe_only_reason: "past_due",
    features: FREE_FEATURES,
  });
  await page.goto("/upgrade?state=past_due");
  await expect(page.getByRole("heading", { name: "Resolve Billing" })).toBeVisible();
  await page.getByRole("button", { name: "Resolve billing" }).click();
  await expect.poll(() => state.calls.billingPortal ?? 0).toBe(1);
});

test("self-serve: upgrade is a contact path when billing is disabled", async ({ page }) => {
  const state = createMockState({ entitlements: expiredObserveOnly(), billingEnabled: false });
  await installMockApi(page, state);
  await page.goto("/upgrade");

  const upgrade = page.getByRole("button", { name: "Add payment method and reactivate Optimize" });
  await expect(upgrade).toBeVisible();
  await upgrade.click();
  await expect(page.getByText(/Self-serve billing is not available/)).toBeVisible();
  expect(state.calls.billingCheckout).toBe(1);
});

test("self-serve: upgrade starts Stripe checkout when billing is enabled", async ({ page }) => {
  const state = createMockState({ entitlements: expiredObserveOnly(), billingEnabled: true });
  await installMockApi(page, state);
  await page.goto("/upgrade");

  await page.getByRole("button", { name: "Add payment method and reactivate Optimize" }).click();
  await expect.poll(() => state.calls.billingCheckout ?? 0).toBe(1);
  // The client redirects to the URL returned by the checkout endpoint.
  await expect(page).toHaveURL(/checkout=stripe-redirect/);
});
