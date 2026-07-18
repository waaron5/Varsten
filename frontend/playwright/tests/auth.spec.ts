import { expect, test } from "playwright/test";

test("invalid callbacks fail closed with a recoverable generic page", async ({ page }) => {
  const reflectedMarker = "phase4-reflection-marker";

  await page.goto(`/auth/callback?error=access_denied&error_description=${reflectedMarker}`);

  await expect(page).toHaveURL(/\/auth\/error$/);
  await expect(page.getByRole("heading", { name: "Sign-in could not be completed" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Try signing in again" })).toHaveAttribute("href", "/auth/login");
  await expect(page.locator("body")).not.toContainText(reflectedMarker);
});
