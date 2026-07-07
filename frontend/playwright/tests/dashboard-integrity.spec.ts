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

  const card = page.locator(".dash-proof-card");
  await expect(card.getByText("No score", { exact: true })).toBeVisible();
  await expect(card.getByText("no integrity score")).toBeVisible();
  await expect(card.getByText("High Confidence")).toHaveCount(0);
  await expect(card.locator(".dash-proof-check")).toHaveCount(0);
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
  await expect(page.locator(".dash-metric-strip")).toHaveCount(0);
  await expect(page.locator(".dash-proof-card")).toHaveCount(0);
  expect(clientErrors).toEqual([]);
});
