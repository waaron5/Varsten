import { expect, test } from "playwright/test";
import {
  API_BASE,
  NOW,
  createMockState,
  createOnboardingStatus,
  installMockApi,
  PROJECT_ID,
  watchClientErrors,
} from "./support/mockApi";

test("signup, project creation, provider connection, and first proxy request activate onboarding", async ({ page }) => {
  const state = createMockState({
    projects: [],
  });
  const clientErrors = watchClientErrors(page);
  await installMockApi(page, state);

  await page.goto("/onboarding");

  await expect(page.getByText("Create your first project")).toBeVisible();
  await expect.poll(() => state.calls.authSync ?? 0).toBe(1);

  await page.getByRole("button", { name: "Create project" }).click();
  await expect.poll(() => state.projects.length).toBe(1);
  expect(state.projects[0].id).toBe(PROJECT_ID);

  // A fresh workspace opens on the connection chooser — the first step is the
  // user's choice, never pre-completed. The recommended Production SDK is
  // pre-selected, so Continue advances to the API key step.
  await expect(page.getByRole("heading", { name: "How do you want to connect?" })).toBeVisible();
  await page.getByRole("button", { name: "Continue", exact: true }).click();

  await expect(page.getByRole("heading", { name: "Create your Varsten key" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Connect your provider" })).toHaveCount(0);

  await page.getByRole("button", { name: "Create API key" }).click();
  await expect(page.getByText("vk_test_e2e_first_request")).toBeVisible();

  // The plaintext key is shown exactly once; the wizard must not auto-advance
  // past it. Only after the explicit Continue does the next step open.
  await expect(page.getByRole("heading", { name: "Connect your provider" })).toHaveCount(0);
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Connect your provider" })).toBeVisible();

  await expect(page.getByText("OpenAI", { exact: true })).toBeVisible();
  await expect(page.getByText("Anthropic", { exact: true })).toBeVisible();
  await expect(page.getByText("Gemini", { exact: true })).toBeVisible();

  const openAiCard = page.locator(".onb-provider").filter({ has: page.getByText("OpenAI", { exact: true }) });
  await openAiCard.getByPlaceholder("sk-...").fill("sk-test-openai-provider-key");
  await openAiCard.getByRole("button", { name: "Connect" }).click();

  await expect(openAiCard.getByText("Verified")).toBeVisible();
  expect(state.calls.connectProvider).toBe(1);

  // A successful provider connect enables Continue; advancing is an explicit
  // click, not a magic auto-jump.
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Send your first request" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Waiting for verification" })).toBeDisabled();
  await page.getByRole("button", { name: "Copy OpenAI SDK snippet" }).click();
  await expect.poll(() => state.calls["event:snippet_viewed"] ?? 0).toBe(1);

  await page.evaluate(async (apiBase) => {
    const response = await fetch(`${apiBase}/v1/chat/completions`, {
      method: "POST",
      headers: {
        authorization: "Bearer vk_test_e2e_first_request",
        "content-type": "application/json",
        "x-varsten-client": "@varsten/openai@0.1.0",
        "x-varsten-metadata": JSON.stringify({
          environment: "production",
          feature: "support",
          task_type: "support_reply.billing",
          workflow: "support_reply",
        }),
      },
      body: JSON.stringify({
        model: "gpt-4o-mini",
        messages: [{ role: "user", content: "Say hello from Varsten" }],
      }),
    });
    if (!response.ok) throw new Error(`proxy request failed: ${response.status}`);
  }, API_BASE);

  await expect(page.getByText("Verified live: first request received through the selected integration.")).toBeVisible({
    timeout: 7000,
  });
  await expect(page.getByRole("button", { name: "Finish setup" })).toBeEnabled();
  expect(state.calls.proxy).toBe(1);
  expect(clientErrors).toEqual([]);
});

test("metadata-only path skips provider connection and shows the ingest snippet", async ({ page }) => {
  const state = createMockState();
  const clientErrors = watchClientErrors(page);
  await installMockApi(page, state);

  await page.goto("/onboarding");

  // The wizard opens on the connection chooser. Pick the metadata-only path.
  await expect(page.getByRole("heading", { name: "How do you want to connect?" })).toBeVisible();
  await page.getByRole("button", { name: /Metadata only/ }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();

  // The metadata path needs no provider key, so that step is skipped and the
  // wizard lands back on the API key step.
  await expect(page.getByRole("heading", { name: "Create your Varsten key" })).toBeVisible();
  await page.getByRole("button", { name: "Create API key" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();

  await expect(page.getByRole("heading", { name: "Connect your provider" })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Send a usage record" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Copy ingest snippet" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Waiting for verification" })).toBeDisabled();
  await page.getByRole("button", { name: "Copy ingest snippet" }).click();
  await page.evaluate(async (apiBase) => {
    const response = await fetch(`${apiBase}/v1/usage-events`, {
      method: "POST",
      headers: {
        authorization: "Bearer vk_test_e2e_first_request",
        "content-type": "application/json",
      },
      body: JSON.stringify({
        provider: "openai",
        model: "gpt-4o-mini",
        input_tokens: 10,
        output_tokens: 2,
      }),
    });
    if (!response.ok) throw new Error(`ingest failed: ${response.status}`);
  }, API_BASE);
  await expect(page.getByText("Verified live: first usage record received. Varsten is measuring your AI traffic.")).toBeVisible({
    timeout: 7000,
  });
  await expect(page.getByRole("button", { name: "Finish setup" })).toBeEnabled();
  expect(clientErrors).toEqual([]);
});

test("base-url snippets render the configured proxy base", async ({ page }) => {
  const state = createMockState();
  await installMockApi(page, state);

  await page.goto("/onboarding");
  await page.getByRole("button", { name: /Quick eval/ }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Create API key" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();

  const openAiCard = page.locator(".onb-provider").filter({ has: page.getByText("OpenAI", { exact: true }) });
  await openAiCard.getByPlaceholder("sk-...").fill("sk-test-openai-provider-key");
  await openAiCard.getByRole("button", { name: "Connect" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();

  const snippet = page.locator("pre").filter({ hasText: "baseURL" });
  await expect(snippet).toBeVisible();
  await expect(snippet).toContainText(/baseURL: "http:\/\/(localhost|127\.0\.0\.1):8000\/v1"/);
  await expect(snippet).not.toContainText("https://api.varsten.ai/v1");
});

test("sdk path stays locked and warns when only base-url traffic arrives", async ({ page }) => {
  const state = createMockState({
    onboarding: createOnboardingStatus({
      has_api_key: true,
      has_provider_connection: true,
      selected_path: "sdk",
      selection_saved: true,
      selected_provider: "openai",
      provider_connections: [
        {
          provider: "openai",
          status: "connected",
          last_verified_at: NOW,
          last_error: null,
        },
      ],
      integration: {
        providers: [
          { provider: "openai", method: "none", sdk_client: null, key_configured: true },
          { provider: "anthropic", method: "none", sdk_client: null, key_configured: false },
          { provider: "gemini", method: "none", sdk_client: null, key_configured: false },
        ],
        any_sdk: false,
        base_url_without_sdk: false,
      },
      verification_status: "waiting",
      missing_steps: [
        { key: "first_request", label: "Send a verified first request" },
      ],
      checklist: [
        { key: "selected_path", complete: true },
        { key: "has_api_key", complete: true },
        { key: "has_provider_connection", complete: true },
        { key: "integration_snippet_viewed", complete: false },
        { key: "first_request", complete: false },
        { key: "dashboard_entered", complete: false },
      ],
    }),
  });
  const clientErrors = watchClientErrors(page);
  await installMockApi(page, state);

  await page.goto("/onboarding");

  await expect(page.getByRole("heading", { name: "Send your first request" })).toBeVisible();
  await page.getByRole("button", { name: "Copy OpenAI SDK snippet" }).click();
  await expect.poll(() => state.calls["event:snippet_viewed"] ?? 0).toBe(1);

  await page.evaluate(async (apiBase) => {
    const response = await fetch(`${apiBase}/v1/chat/completions`, {
      method: "POST",
      headers: {
        authorization: "Bearer vk_test_e2e_first_request",
        "content-type": "application/json",
      },
      body: JSON.stringify({
        model: "gpt-4o-mini",
        messages: [{ role: "user", content: "This request intentionally has no SDK marker" }],
      }),
    });
    if (!response.ok) throw new Error(`proxy request failed: ${response.status}`);
  }, API_BASE);

  await expect(page.getByText("We detected OpenAI base-URL traffic, but you chose the Production SDK.")).toBeVisible({
    timeout: 7000,
  });
  await expect(
    page.getByText("Detected base URL traffic, but not the selected Production SDK setup yet."),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Waiting for verification" })).toBeDisabled();
  expect(state.calls.proxy).toBe(1);
  expect(state.calls.completeOnboarding ?? 0).toBe(0);
  expect(clientErrors).toEqual([]);
});

test("verified traffic can finish onboarding without clicking copy", async ({ page }) => {
  const state = createMockState();
  const clientErrors = watchClientErrors(page);
  await installMockApi(page, state);

  await page.goto("/onboarding");
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Create API key" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();

  const openAiCard = page.locator(".onb-provider").filter({ has: page.getByText("OpenAI", { exact: true }) });
  await openAiCard.getByPlaceholder("sk-...").fill("sk-test-openai-provider-key");
  await openAiCard.getByRole("button", { name: "Connect" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();

  await page.evaluate(async (apiBase) => {
    const response = await fetch(`${apiBase}/v1/chat/completions`, {
      method: "POST",
      headers: {
        authorization: "Bearer vk_test_e2e_first_request",
        "content-type": "application/json",
        "x-varsten-client": "@varsten/openai@0.1.0",
      },
      body: JSON.stringify({ model: "gpt-4o-mini", messages: [{ role: "user", content: "hello" }] }),
    });
    if (!response.ok) throw new Error(`proxy request failed: ${response.status}`);
  }, API_BASE);

  await expect(page.getByRole("button", { name: "Finish setup" })).toBeEnabled({ timeout: 7000 });
  await page.getByRole("button", { name: "Finish setup" }).click();
  await expect(page).toHaveURL(/\/dashboard/);
  expect(state.calls["event:snippet_viewed"] ?? 0).toBe(0);
  expect(clientErrors).toEqual([]);
});
