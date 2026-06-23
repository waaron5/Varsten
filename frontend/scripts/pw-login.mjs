// One-time interactive login. Opens a headed browser; you complete the real Auth0
// sign-in; the resulting session is saved so headless screenshot runs can reuse it.
// No app/auth code is touched and nothing is bypassed -- this authenticates exactly
// like a human. The saved state is a credential: it is gitignored and expires with
// the Auth0 session (re-run this when screenshots start bouncing to the login page).

import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const BASE = process.env.BASE_URL ?? "http://localhost:3000";
// Absolute, anchored to this script, so the save location never depends on cwd.
const STATE = path.resolve(import.meta.dirname, "..", "playwright/.auth/state.json");

const browser = await chromium.launch({ headless: false });
const context = await browser.newContext();
const page = await context.newPage();

await page.goto(`${BASE}/dashboard`);
console.log("\nA browser window opened. Complete the Auth0 sign-in there.");
console.log("Waiting for the authenticated dashboard to render (up to 5 minutes)…\n");

// Wait for .dashboard-view specifically: the topbar/sidebar shell renders even on
// the pre-login "Sign in to view" gate, so it is NOT a signed-in signal. The
// dashboard body only renders past the RequireSession gate, i.e. once authenticated.
await page.waitForSelector(".dashboard-view", { timeout: 300_000, state: "visible" });
// Let the session cookies settle before snapshotting storage state.
await page.waitForTimeout(1_000);

fs.mkdirSync(path.dirname(STATE), { recursive: true });
await context.storageState({ path: STATE });
console.log(`\n✓ Saved authenticated session to:\n  ${STATE}\n`);

await browser.close();
