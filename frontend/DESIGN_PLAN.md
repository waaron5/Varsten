# Command Center — Redesign Plan (v2)

Status: proposal, awaiting approval. No React/CSS until signed off.

## Reality check first (read this before the asks)

The v1 plan in this file's history was approved and **shipped** (commit
`b529b66`, refined since). The Command Center running today already is:

- a single-viewport, no-scroll, fluid dashboard (`.cc-canvas`, 12-col × 3-row grid,
  `overflow:hidden`, `height: calc(100dvh - var(--header-h))`),
- that reflows when the sidebar collapses (the shell's `.app` grid animates
  `grid-template-columns: var(--sidebar-w) 1fr` → collapsed width; the inner
  `repeat(12, minmax(0,1fr))` canvas absorbs it for free),
- rendering all three narratives — Margin engine, Proxy traffic (hit-rate +
  latency), Quality guardrails — plus a headline KPI strip,
- with Recharts isolated behind `next/dynamic({ ssr:false })` in a Client Component
  (`lazyCharts.tsx`), themed entirely through CSS custom properties, custom
  `.chart-tip` tooltips, `ResponsiveContainer` with `debounce` + `initialDimension`.

So three of your four asks (1 nav fluidity, 2 overview structure, 4 hydration) are
**already solved** in the codebase. Section 3's three narratives **exist**. This v2
plan does not re-propose them. It states the shipped baseline honestly, then scopes
the **deltas** that actually move the product forward: density that responds to
collapse (not just width), persisted nav state done hydration-safe, a p99 band, and
table density. If you want a from-scratch rebuild instead, say so and I'll justify
the cost, but I do not recommend throwing away working, tested layout.

The newly-seeded demo tenant (`scripts/seed_demo_tenant.py`) now gives this redesign
a data-dense narrative to design against: 30 days of reconciled proxy traffic,
warming hit-rate, holdback arms, latency percentiles. Every number below can be seen
live with `make seed-demo-tenant`.

---

## 1. Collapsible navigation fluidity

**Shipped baseline.** Pure CSS-grid reflow, no JS resize handling:
```css
.app { display:grid; grid-template-columns: var(--sidebar-w) 1fr;
       transition: grid-template-columns 0.22s var(--ease); }
.app.sidebar-collapsed { grid-template-columns: var(--sidebar-collapsed-w) 1fr; }
```
The `1fr` main column reflows; `.cc-canvas` (`repeat(12, minmax(0,1fr))`) redivides;
each `ResponsiveContainer` fires its ResizeObserver and re-lays-out once after the
0.22s transition (the `debounce` already absorbs the in-flight frames). Working.

**Delta A — density, not just width (the real upgrade).** Today collapsing the
sidebar only makes panels *wider*. A Datadog-grade dashboard should also get
*denser*: more ticks, more KPI tiles visible, tighter gaps. CSS container queries
(not media queries) let the canvas respond to its own width, which is exactly what
the sidebar toggle changes:
```css
.cc-canvas { container-type: inline-size; container-name: cc; }
@container cc (min-width: 1280px) {
  .cc-kpi-strip { /* reveal a 7th tile / wider sparklines */ }
  .cc-pos-margin { grid-column: 1 / 9; }      /* more room to the hero */
}
@container cc (max-width: 1080px) {
  .cc-canvas { gap: 10px; }                    /* tighten when cramped */
}
```
This is the load-bearing new idea: the layout reacts to the *container*, so the same
breakpoints serve both sidebar-collapse and window-resize with one mechanism. No
`container-type` exists in the CSS today; this is net-new.

**Delta B — persist the collapse state.** `AppShell` holds `sidebarCollapsed` in
`useState(false)`, so the sidebar snaps back to expanded on every reload/navigation.
A real product remembers it. Persisting it is what creates a hydration risk — see §4
for the SSR-safe approach. These two asks (1 and 4) are the same problem.

---

## 2. The high-signal overview (Datadog/Tableau density, vintage-modern)

**Shipped baseline.** The 12×3 composition, fixed and clip-fit:
```
Row 1 (auto)          KPI strip — Gross · Net · Run-rate · Hit-rate · p95 · Trust
Row 2 (1.3fr)         Margin engine (cols 1–8)        Proxy hit-rate (cols 9–12)
Row 3 (1fr)           Quality guardrails (cols 1–8)   Proxy latency  (cols 9–12)
```
Honest empty/null states already carry (no painted $0; "capture pending"; cache-only
message). This is the clean overview the v1 plan promised.

**Delta C — KPI tiles earn their height.** Today each tile is a label + a single
big number. At this density we can add a 28px inline sparkline (cache hit-rate trend,
gross-saved trend) per tile from the data we already fetch — a Tableau "BAN with
spark" move. Keeps the strip one row, raises signal sharply. Sparkline is a tiny
`ssr:false` Recharts `<Area>` with no axes, reusing the same lazy-load discipline.

**Delta D — vintage-modern density rules (codify, don't reinvent).** The aesthetic
is already established in tokens (warm paper `--bg`, restrained `--c1/c2/c3`,
`--font-mono` axis labels, hairline `--border`). v2 formalizes the density grammar:
one accent per panel, grids off except a single dashed horizontal on latency,
uppercase micro-labels, tabular-nums everywhere, zero legends (series read from
inline color-keyed stats). This is a 1-page style contract the panels conform to,
not new chrome.

---

## 3. Visual architecture of the three narratives

### 3.1 Margin engine — shipped, minor delta
Hero cumulative-savings `<Area>` (`--brand` gradient fill), KPI tiles for Gross/Net/
Run-rate. **Delta:** add a faint baseline (naive-retail) reference line so the
"saved vs would-have-spent" gap is visual, not just a tooltip number. The data
(`baseline_usd`, `optimized_usd`) is already in the `savings-trend` payload.

### 3.2 Proxy traffic — shipped, one real gap
Hit-rate `<Area>` (`--c2`) over time; latency `<Line>` chart drawing **p50 (`--c1`)
and p95 (`--c3`)**, with p50/p95/p99 shown as inline stats in the panel head.
**Delta:** we now capture p99 (the seeder and `/metrics/proxy-traffic` expose it) but
the chart only plots p50/p95. Add a p99 series as a faint upper band (or a third
line) so the tail is visible, not just a header stat. This is the "percentiles we
just unlocked" made visual.

### 3.3 Quality guardrails — shipped, density delta
Dense `.tbl` of active routes: incumbent→candidate, holdback %, control/treatment
counts, measured savings (A/B), treat-vs-control quality, status pill
(saving/watch/drift/gathering). **Delta:** at the new density, add a measured-savings
**confidence interval** column (the `/engine/routes` payload already returns
`measured_savings_ci_low/high_usd`) — a CI is the difference between a number finance
trusts and one it argues with (CLAUDE.md). Keep it to one extra column; the table
stays inside its cell and scrolls internally if rows exceed the row-2 height.

---

## 4. Hydration-mismatch mitigation

**Shipped baseline (charts) — already correct.** Per the bundled app-router docs
(`node_modules/next/dist/docs/01-app/02-guides/lazy-loading.md`), `ssr:false` with
`next/dynamic` is only valid inside a Client Component. `lazyCharts.tsx` is
`"use client"` and wraps every chart, so Recharts never runs during SSR → no
hydration mismatch, and a sized skeleton fills the cell during chunk-load (no layout
shift). Any new chart (sparklines §2, p99 §3) goes through this same wrapper. Nothing
to fix here; the discipline just extends.

**The actual new hydration risk — persisted nav state (§1 Delta B).** The wrong way
is `useState(() => localStorage.getItem(...))`: the server has no `localStorage`, so
it renders expanded, the client renders collapsed, and React throws a hydration
mismatch (or flickers via a `useEffect` correction). The right way, and the one I'll
build:

1. Store the collapse preference in a **cookie** (`cc_sidebar=collapsed`), not
   localStorage. Cookies are readable on the server.
2. Read it in the **Server Component** layout (`cookies()` from `next/headers`) and
   render the shell with the correct `sidebar-collapsed` class on first paint.
3. The client `AppShell` initializes its `useState` from a prop seeded by that same
   cookie value — server and client agree on the first render, so **no mismatch and
   no flash**. The toggle writes the cookie (and updates state) on click.

This makes the sidebar remember its state across reloads without a hydration error —
the one place this redesign actually touches SSR/CSR correctness.

---

## 5. Component / CSS impact (scope)

Additive, within the existing module tree — no rebuild:
- `components/command-center/`: extend `charts.tsx` (sparkline, p99 series, baseline
  ref line), `panels.tsx` (KPI sparkline tiles, CI column), `lazyCharts.tsx` (sparkline
  wrapper). No new top-level architecture.
- `globals.css`: add `container-type`/`@container` rules to `.cc-canvas`, sparkline
  cell styles, one table column. All consume existing tokens. No Tailwind.
- `AppShell.tsx` + the Server Component layout: cookie-seeded collapse state (§4).
- Verify chain unchanged: `tsc --noEmit`, `eslint`, `next build`, then `npm run dev`
  against the seeded demo tenant at 1280/1440/1920 widths × 720/900/1080 heights,
  sidebar both states.

---

## 6. Open decisions for your sign-off

1. **Scope (most important):** confirm this is an *iteration* on the shipped CC
   (my recommendation), not a from-scratch rebuild. If you want a rebuild, I'll cost
   it honestly first.
2. **Density mechanism (§1 Delta A):** adopt CSS container queries so collapse adds
   density, not just width? (Recommended; it's the headline upgrade.)
3. **KPI sparklines (§2 Delta C):** add inline sparklines to the KPI tiles, or keep
   the tiles single-number-clean?
4. **Persisted nav state (§1B/§4):** persist sidebar collapse via cookie (SSR-safe)?
   Worth the small layout-component change?
5. **Quality CI column (§3.3):** surface the measured-savings confidence interval in
   the routes table now, or hold it for the Proof page?

No code until you pick. I'll build to whatever you choose.
