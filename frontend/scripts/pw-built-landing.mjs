import { chromium } from "playwright";
import fs from "node:fs";

const BASE = process.env.BASE_URL ?? "http://localhost:3100";
const OUTDIR = "playwright/screenshots";
fs.mkdirSync(OUTDIR, { recursive: true });

const b = await chromium.launch();

// Desktop full page
const dctx = await b.newContext({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 });
const dp = await dctx.newPage();
await dp.goto(`${BASE}/`, { waitUntil: "networkidle" });
await dp.waitForTimeout(600);
await dp.screenshot({ path: `${OUTDIR}/built-desktop-full.png`, fullPage: true });

// Hero first (before any scrolling)
const hero = dp.locator(".lp-hero").first();
await hero.screenshot({ path: `${OUTDIR}/built-hero.png` });

// Per-section element shots
const sections = ["problem","solution","product","levers","ledger","how-it-works","pricing","security"];
for (const id of sections) {
  const el = dp.locator(`#${id}`).first();
  if (await el.count()) { try { await el.screenshot({ path: `${OUTDIR}/built-${id}.png` }); } catch {} }
}

// Docs page (restyled chrome)
await dp.goto(`${BASE}/docs`, { waitUntil: "networkidle" });
await dp.waitForTimeout(400);
await dp.screenshot({ path: `${OUTDIR}/built-docs.png`, clip: { x: 0, y: 0, width: 1440, height: 1000 } });

// Mobile full page
const mctx = await b.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true });
const mp = await mctx.newPage();
await mp.goto(`${BASE}/`, { waitUntil: "networkidle" });
await mp.waitForTimeout(600);
await mp.screenshot({ path: `${OUTDIR}/built-mobile-full.png`, fullPage: true });

console.log("done");
await b.close();
