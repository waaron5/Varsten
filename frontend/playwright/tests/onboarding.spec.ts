import { expect, test } from "playwright/test";
import {
  API_BASE,
  createMockState,
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
  await expect(page.getByRole("heading", { name: "Connect Varsten" })).toBeVisible();
  await expect.poll(() => state.projects.length).toBe(1);
  expect(state.projects[0].id).toBe(PROJECT_ID);

  await expect(page.getByRole("heading", { name: "OpenAI" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Anthropic" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Gemini" })).toBeVisible();

  await page.getByRole("button", { name: "Create API key" }).click();
  await expect(page.getByText("vk_test_e2e_first_request")).toBeVisible();

  const openAiCard = page
    .getByRole("heading", { name: "OpenAI" })
    .locator("xpath=ancestor::div[contains(concat(' ', normalize-space(@class), ' '), ' card ')][1]");
  await openAiCard.getByPlaceholder("sk-...").fill("sk-test-openai-provider-key");
  await openAiCard.getByRole("button", { name: "Connect" }).click();

  await expect(openAiCard.getByText("Connected")).toBeVisible();
  expect(state.calls.connectProvider).toBe(1);

  await page.evaluate(async (apiBase) => {
    const response = await fetch(`${apiBase}/v1/chat/completions`, {
      method: "POST",
      headers: {
        authorization: "Bearer vk_test_e2e_first_request",
        "content-type": "application/json",
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

  await expect(page.getByText("First request received. Varsten is observing your AI traffic.")).toBeVisible({
    timeout: 7000,
  });
  await expect(page.getByRole("button", { name: "Continue to dashboard" })).toBeEnabled();
  expect(state.calls.proxy).toBe(1);
  expect(clientErrors).toEqual([]);
});
