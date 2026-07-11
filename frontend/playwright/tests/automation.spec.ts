import { expect, test } from "playwright/test";
import { createMockState, installMockApi, watchClientErrors } from "./support/mockApi";

test("automation page renders the project lever controls and toggles a lever", async ({ page }) => {
  const state = createMockState();
  const clientErrors = watchClientErrors(page);
  await installMockApi(page, state);

  await page.goto("/automation");

  await expect(page.getByRole("heading", { name: "Control how Varsten saves money" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Money-saving automations" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Semantic cache" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Model downshift" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Batching" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Token trim" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Smart routing" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Prompt compression" })).toBeVisible();
  await expect(page.getByText("Recommendations")).toHaveCount(0);

  const smartRoutingToggle = page.getByRole("button", { name: "Turn on Smart routing" });
  await expect(smartRoutingToggle).toHaveAttribute("aria-pressed", "false");
  await smartRoutingToggle.click();

  await expect.poll(() => state.engineLevers.find((row) => row.lever === "smart_routing")?.enabled).toBe(true);
  await expect(page.getByRole("button", { name: "Turn off Smart routing" })).toHaveAttribute("aria-pressed", "true");
  expect(clientErrors).toEqual([]);
});

test("legacy engine routes redirect to automation", async ({ page }) => {
  const state = createMockState();
  await installMockApi(page, state);

  await page.goto("/engine");

  await expect(page).toHaveURL(/\/automation$/);
  await expect(page.getByRole("heading", { name: "Control how Varsten saves money" })).toBeVisible();
});
