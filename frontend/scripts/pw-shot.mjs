// Headless screenshots of the real /dashboard, reusing the session captured by
// pw-login.mjs. Captures the full dashboard plus each panel so the layout can be
// compared against the mockups in public/. Runs against LOCAL dev only -- never
// point BASE_URL at production with a real customer's session.

import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const BASE = process.env.BASE_URL ?? "http://localhost:3000";
const ROOT = path.resolve(import.meta.dirname, "..");
const STATE = path.join(ROOT, "playwright/.auth/state.json");
const OUT = path.join(ROOT, "playwright/screenshots");

if (!fs.existsSync(STATE)) {
  console.error("No saved session. Run `npm run pw:login` first.");
  process.exit(1);
}

const browser = await chromium.launch();
const context = await browser.newContext({
  storageState: STATE,
  viewport: { width: 1440, height: 1600 }, // tall enough that the whole dashboard fits without scroll
  deviceScaleFactor: 2, // crisp, retina-quality captures for pixel comparison
});
const page = await context.newPage();

await page.goto(`${BASE}/dashboard`, { waitUntil: "networkidle" });

// If the session expired we land on a login page and the shell never renders.
try {
  await page.waitForSelector(".dashboard-view", { timeout: 20_000 });
} catch {
  console.error("Dashboard did not render — the session may have expired. Re-run `npm run pw:login`.");
  await browser.close();
  process.exit(1);
}
await page.waitForTimeout(900); // let Recharts finish its first layout

fs.mkdirSync(OUT, { recursive: true });

// Full dashboard content (element shot captures the whole box even past the fold).
await page.locator(".dashboard-view").screenshot({ path: `${OUT}/dashboard-full.png` });

const panels = {
  topbar: ".topbar",
  kpis: ".dash-metric-strip",
  savings: ".dash-trend-card",
  levers: ".dash-levers-card",
  drivers: ".dash-drivers-card",
  proof: ".dash-proof-card",
};
for (const [name, selector] of Object.entries(panels)) {
  const el = page.locator(selector).first();
  if (await el.count()) {
    await el.screenshot({ path: `${OUT}/${name}.png` });
  }
}

console.log(`Wrote screenshots to ${OUT}/`);
await browser.close();
