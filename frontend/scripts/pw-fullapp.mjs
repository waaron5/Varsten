import { chromium } from "playwright";
const STATE = "playwright/.auth/state.json";
const OUT = "playwright/screenshots/app-full.png";
const b = await chromium.launch();
const ctx = await b.newContext({ storageState: STATE, viewport: { width: 1440, height: 1700 }, deviceScaleFactor: 2 });
const p = await ctx.newPage();
await p.goto("http://localhost:3000/dashboard", { waitUntil: "networkidle" });
await p.waitForSelector(".dashboard-view");
await p.waitForTimeout(900);
await p.screenshot({ path: OUT });   // viewport shot incl. sidebar + topbar
console.log("wrote", OUT);
await b.close();
