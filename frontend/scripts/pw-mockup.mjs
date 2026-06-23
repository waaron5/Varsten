import { chromium } from "playwright";
const FILE = "file:///Users/aaronwood/dev/Varsten/marketing/public/dashboard-UI.html";
const OUT = "playwright/screenshots/mockup-html.png";
const b = await chromium.launch();
const ctx = await b.newContext({ viewport: { width: 1440, height: 1700 }, deviceScaleFactor: 2 });
const p = await ctx.newPage();
await p.goto(FILE, { waitUntil: "networkidle" });
await p.waitForTimeout(4000); // let the bundler render
// Try to remove the loading chip if present
await p.evaluate(() => { const e = document.getElementById("__bundler_loading"); if (e) e.remove(); });
await p.screenshot({ path: OUT, fullPage: true });
console.log("wrote", OUT);
await b.close();
