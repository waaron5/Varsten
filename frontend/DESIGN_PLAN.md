# Command Center — Architecture & Design Plan

Status: proposal, awaiting approval. No implementation until approved.

Goal: rebuild the Command Center (Home) as a single-viewport, no-scroll, fluid
dashboard at Datadog/Tableau data-density but cleaner and more opinionated, that
expands elegantly as the sidebar collapses, and that presents the three core
narratives (Margin, Proxy Traffic, Quality) without breaking chart aspect ratios
or wrapping text.

---

## 1. Current-state analysis

### 1.1 The shell already solves two of the hard problems

From `globals.css` and `AppShell.tsx`:

- **Sidebar fluidity is solved.** `.app` is a CSS grid:
  ```
  .app { display:grid; grid-template-columns: var(--sidebar-w) 1fr;
         grid-template-rows: minmax(0,1fr); height:100dvh; overflow:hidden;
         transition: grid-template-columns 0.22s var(--ease); }
  .app.sidebar-collapsed { grid-template-columns: var(--sidebar-collapsed-w) 1fr; }
  ```
  Collapsing the sidebar (React state `sidebarCollapsed` → `.sidebar-collapsed`)
  animates `grid-template-columns`; the `1fr` main column reflows automatically.
  **The dashboard inherits this for free** as long as it uses fluid widths
  (`fr`/`%`/`minmax`) and never fixed pixels.
- **No-scroll is enforced at the shell.** `html,body{overflow:hidden}`,
  `.app{height:100dvh;overflow:hidden}`, and the only scroll container is
  `.content { flex:1; min-height:0; overflow-y:auto; scrollbar-gutter:stable }`.
  `scrollbar-gutter:stable` already prevents a width jump when a scrollbar would
  appear, so collapse won't shift content sideways.
- `.main` is `flex-direction:column; min-width:0; min-height:0`; `.topbar` is a
  fixed `var(--header-h)` (62px) with `flex-shrink:0`. So the content box height
  is exactly `100dvh - 62px`, and `min-height:0` is correctly set up the chain
  (the precondition for a child to fill and clip instead of overflow).

### 1.2 What the current Command Center does wrong

The page renders `CommandCenterView` (buried in the 1,400-line `EngineViews.tsx`)
through two layers that actively defeat the shell:

- `.view { max-width:1340px; margin:0 auto; padding:24px 26px 60px }` — caps width
  at 1340px and centers it, so on a wide screen (sidebar collapsed) the dashboard
  **does not** fill the viewport, and the 60px bottom padding guarantees overflow.
- `.command-center-stack` is a flex column of six full-width cards; it grows past
  the viewport and relies on `.content`'s scrollbar. That is the scroll we are
  eliminating.
- Command Center logic is entangled with Engine logic in one file.

### 1.3 CSS architecture (what we build on)

Hand-rolled design system in `globals.css`: CSS custom properties for color
(`--brand`, `--c1..--c6`, `--pos/--neg/--warn` + `-soft`), surfaces/borders/text
(`--surface`, `--border`, `--text/-2/-3/-faint`), geometry (`--radius*`,
`--header-h`, `--sidebar-*`), motion (`--ease`), and fonts (`--font-sans/-mono`).
Reusable classes: `.card`, `.card-head`, `.kpi`, `.pill(.green/.amber/.red...)`,
`.tbl`, `.eval-note`. **No Tailwind, no UI kit.** The plan adds a small,
self-contained `cc-*` namespace and reuses these tokens and primitives.

---

## 2. Layout strategy (the no-scroll, fluid core)

### 2.1 The Command Center opts out of `.view`

The page renders a dedicated full-bleed canvas instead of `.view`:

```
.cc-canvas {
  height: 100%;            /* fills .content exactly */
  width: 100%;
  padding: 16px 18px;
  display: grid;
  grid-template-columns: repeat(12, minmax(0, 1fr));
  grid-template-rows: auto minmax(0, 1.3fr) minmax(0, 1fr);
  gap: 14px;
  overflow: hidden;        /* clip-fit, never scroll */
}
```

- No `max-width`, no centering → it fills the viewport and grows when the sidebar
  collapses.
- `minmax(0, 1fr)` on **both** columns and rows is the load-bearing trick: it lets
  grid items shrink below their content size, which is exactly what stops charts
  and tables from forcing a "grid blowout" (the same reason `.main`/`.content`
  already set `min-height:0`).
- `overflow:hidden` on the canvas means any internal excess clips inside a panel
  rather than triggering the `.content` scrollbar. The page never scrolls.

### 2.2 The 12-column / 3-row composition

```
Row 1 (auto)            ┌───────────────────────────────────────────────┐
KPI strip (span 12)     │ KPI · KPI · KPI · KPI · KPI · KPI              │
                        └───────────────────────────────────────────────┘
Row 2 (minmax 0,1.3fr)  ┌───────────────── cols 1–8 ─────┐┌── cols 9–12 ─┐
                        │ Margin engine (hero savings)   ││ Proxy: hit-  │
                        │ cumulative area chart          ││ rate chart   │
                        └────────────────────────────────┘└──────────────┘
Row 3 (minmax 0,1fr)    ┌───────────────── cols 1–8 ─────┐┌── cols 9–12 ─┐
                        │ Quality guardrails (A/B table) ││ Proxy: lat-  │
                        │                                ││ ency p50/p95 │
                        └────────────────────────────────┘└──────────────┘
```

- Left column = the two "big read" widgets (the hero cumulative-savings line and
  the dense quality table). Right column = the two proxy charts (hit-rate, latency)
  stacked. Balanced, dense, and every narrative is present in one viewport.
- The KPI strip is the headline tiles (Margin Gross/Net + Proxy hit-rate + latency
  percentiles), satisfying the "KPI tiles for Gross/Net Saved" and "latency health
  percentiles" requirements without spending a chart row on them.

### 2.3 Panels fill and clip

Every grid item is a panel that fills its cell and clips:

```
.cc-panel { min-width:0; min-height:0; display:flex; flex-direction:column; overflow:hidden; }
.cc-panel-head { flex:none; }                 /* fixed-height title row */
.cc-panel-body { flex:1; min-height:0; }      /* charts/tables live here */
```

`flex:1; min-height:0` on the body is what lets a Recharts `ResponsiveContainer`
(height `100%`) measure and fill the remaining space, and what lets a dense table
clip (or scroll *internally*, contained) without growing the page.

### 2.4 Fluidity on sidebar collapse — concretely

Nothing extra is required for the resize itself; the shell grid does it. The
dashboard cooperates by:

- using only `fr`/`%`/`minmax` widths (no fixed px on cards),
- charts via `ResponsiveContainer width="100%" height="100%"` (ResizeObserver-based),
- `debounce` on `ResponsiveContainer` (~150ms) so the SVG re-renders once after the
  0.22s grid transition settles instead of thrashing every animation frame,
- text that cannot wrap on width change: KPI values `white-space:nowrap;
  font-variant-numeric:tabular-nums`; long model names in the table use
  `max-width` + ellipsis.

### 2.5 No-scroll budget and honest fallback

Height math: content = `100dvh − 62`. Canvas padding 32 + two 14px gaps = 60.
KPI strip ≈ 96. Remaining for the two chart rows ≈ `100dvh − 218`, split 1.3:1.

- At 900px tall: ~390/292 px rows → ~300px charts. Comfortable.
- At 720px tall: ~250/195 px rows → legible but tight.
- Below ~680px tall **or** ~1100px wide: strict no-scroll stops being legible. The
  plan degrades gracefully with a scoped media query that (a) collapses the 12-col
  grid to a single column and (b) re-enables scrolling **for this page only**:
  ```
  @media (max-height: 680px), (max-width: 1100px) {
    .cc-canvas { height:auto; min-height:100%; overflow:visible;
                 grid-template-columns:1fr; grid-template-rows:none; }
  }
  ```
  This honors "everything fits in view if possible" without producing an unusable
  squeeze on small windows. I will call this out for sign-off rather than pretend
  strict no-scroll holds at every size.

---

## 3. Information architecture decision (needs your call)

`CLAUDE.md` specifies the Command Center panels as *live savings, decision queue,
recent auto-actions, top waste now*. This redesign's requirements list only the
three analytical narratives. Those two sets do not both fit a no-scroll viewport
legibly.

**My recommendation:** make the Command Center the clean, no-scroll **overview**
(the three narratives + headline KPIs), and relocate the **operational** widgets
(decision queue, recent actions, top-waste) to the **Engine** page. Rationale from
CLAUDE.md itself: "you land at the top, you work in the Engine" and "Command Center
and Engine should cover ninety percent of daily use." The overview proves; the
Engine decides. This keeps each surface single-purpose and the Command Center
strictly no-scroll.

**Alternative if you want the decision queue on Home:** drop the right column's
latency chart to a compact KPI (p50/p95/p99 tiles only) and add a narrow
right-rail "Decision queue" (cols 11–12) that scrolls *internally*. This preserves
"every screen produces a decision" at the cost of smaller proxy charts.

This is the one open product decision in the plan. I will build to whichever you
pick.

---

## 4. Component hierarchy

Decouple the Command Center from `EngineViews.tsx` into its own module tree.

```
app/command-center/page.tsx
  └─ <CommandCenter/>                         (Server Component shell → renders client root)

components/command-center/
  CommandCenter.tsx          "use client"  — RequireSession + <CommandCenterProvider> + <CommandCenterGrid/>
  CommandCenterProvider.tsx  "use client"  — parallel fetch of all endpoints, per-resource loading flags, context
  CommandCenterGrid.tsx      "use client"  — the .cc-canvas 12×3 grid; places the panels
  panels/
    KpiStrip.tsx                            — headline tiles (Gross, Net, Run-rate, Hit-rate, p95, Trust)
    MarginEnginePanel.tsx                   — hero cumulative-savings area chart
    ProxyHitRatePanel.tsx                   — hit-rate area chart over time
    ProxyLatencyPanel.tsx                   — p50/p95 line chart + p50/p95/p99 inline stats
    QualityGuardrailsPanel.tsx              — A/B routes table (win/quality/drift)
  charts.tsx                 "use client"  — raw Recharts components (no dynamic here)
  lazyCharts.ts              "use client"  — next/dynamic({ssr:false}) wrappers + sized skeletons
  primitives.tsx             "use client"  — <Panel>, <KpiTile>, <PanelSkeleton>, <PanelEmpty>
```

Migration of existing work: the chart bodies I already wrote in
`components/DashboardCharts.tsx` move into `components/command-center/charts.tsx`
(largely as-is). `components/CommandCenterDashboard.tsx` (the stacked sections) is
**replaced** by the panel components above and deleted. The three lines inserted
into `EngineViews.CommandCenterContent` are reverted so Command Center no longer
depends on the Engine module.

---

## 5. Data layer (no layout shift)

Four reads back the page: `commandCenter` (gross/net/run-rate/trust/requests),
`savingsTrend`, `proxyTraffic`, `engineRoutes`. To avoid the current staggered
pop-in (which, in a fixed-height grid, would otherwise flash skeletons unevenly):

- `CommandCenterProvider` fetches all four **in parallel** (`Promise.allSettled`)
  on mount, and exposes both the data and a per-resource `loading`/`error` flag via
  context. One fetch each — no double-fetching `proxyTraffic` across the three
  proxy consumers.
- The **grid is fixed regardless of data state**. Each panel renders a
  `<PanelSkeleton/>` sized to fill its cell until its slice resolves, then swaps in
  the chart/table. Because the cells are fixed (`fr`/`minmax`), nothing reflows and
  the page never gains/loses height → no scroll flicker.
- Honest empty/null states carry over: latency shows "capture pending" when no
  latency is captured; the quality panel shows the cache-only state when no routes
  are live. We do not fabricate the exact-vs-semantic cache split.

This reuses the existing `useProjectResource` pattern internally (token +
`activeProjectId` from `useSession`), just hoisted into one provider.

---

## 6. Charting strategy (Recharts + next/dynamic + CSS vars)

### 6.1 Lazy, client-only, hydration-safe

Per the bundled app-router docs (`node_modules/next/dist/docs/01-app/02-guides/
lazy-loading.md`): `ssr:false` with `next/dynamic` is **only valid inside a Client
Component**. So `lazyCharts.ts` is `"use client"` and wraps each raw chart:

```ts
export const CumulativeSavingsChart = dynamic(
  () => import("./charts").then(m => m.CumulativeSavingsChart),
  { ssr: false, loading: () => <ChartSkeleton/> },   // skeleton fills 100% — no layout shift
);
```

This keeps Recharts out of SSR entirely (no hydration mismatch) and lets the KPI
strip + panel chrome paint before the chart chunk loads. The `loading` skeleton is
sized to the cell so the swap is invisible.

### 6.2 Passing CSS custom properties into the SVG

Recharts forwards `stroke`/`fill`/`tick` straight to SVG attributes, and the
browser resolves `var(--token)` against `:root`. So the look comes entirely from
our design system, not from Recharts:

```tsx
<Area dataKey="cumulative" stroke="var(--brand)" fill="url(#savingsFill)" strokeWidth={2} dot={false}/>
<defs><linearGradient id="savingsFill" x1="0" y1="0" x2="0" y2="1">
  <stop offset="0%"  stopColor="var(--brand)" stopOpacity={0.28}/>
  <stop offset="100%" stopColor="var(--brand)" stopOpacity={0.02}/>
</linearGradient></defs>
<XAxis tick={{ fill:"var(--text-3)", fontSize:11, fontFamily:"var(--font-mono)" }} tickLine={false} axisLine={{stroke:"var(--border)"}}/>
```

Palette mapping: hero savings line `--brand`; hit-rate `--c2`; latency p50 `--c1`,
p95 `--c3`; positive/negative deltas `--pos`/`--neg`. Tooltip is a custom `content`
component using our `.chart-tip` classes (no default Recharts chrome).

### 6.3 Fluid aspect ratio (the collapse requirement)

Each chart is `<ResponsiveContainer width="100%" height="100%" debounce={150}>`
inside a `.cc-panel-body` (`flex:1; min-height:0`). The aspect ratio is dictated by
the grid cell, which resizes with the viewport and the sidebar state — so there is
**no fixed aspect ratio to break**. On collapse, the cell widens, the
ResizeObserver fires, and (after the debounce) the SVG re-lays-out once at the new
size.

### 6.4 Aesthetic rules (Datadog density, cleaner)

Grids off (or a single faint dashed horizontal on the latency chart only); minimal
2-tick axes; tabular-nums everywhere; uppercase micro-labels; hairline
`var(--border)` separators; restrained color (one accent per chart); custom minimal
tooltip; no legends (series are obvious from the two-line latency chart's inline
labels). High signal-to-noise, zero chrome.

---

## 7. CSS plan (scope and naming)

All additions live in a single `cc-*` block appended to `globals.css`, consuming
existing tokens only:

- Layout: `.cc-canvas` (the 12×3 grid), grid placements `.cc-pos-margin`,
  `.cc-pos-quality`, `.cc-pos-hitrate`, `.cc-pos-latency`, `.cc-kpi-strip`.
- Panel: `.cc-panel`, `.cc-panel-head`, `.cc-panel-body`, `.cc-panel-empty`.
- KPI: `.cc-kpi`, `.cc-kpi-label`, `.cc-kpi-value(.pos/.neg)`, `.cc-kpi-sub`.
- Skeleton: `.cc-skeleton` (a token-colored shimmer), sized to fill.
- Tooltip: reuse the `.chart-tip*` classes already added.
- One scoped media query (§2.5) for the small-viewport fallback.

The Command Center page stops using `.view`; no global CSS changes to the shell,
`.content`, or other pages.

The full-height chain to verify: `.content` (already `min-height:0`) → page root →
`.cc-canvas { height:100% }`. If `RequireSession` introduces a wrapper element, it
must be `display:contents` (or `height:100%`) so the 100% height propagates
unbroken.

---

## 8. Build sequence (after approval)

1. Scaffold `components/command-center/` (provider, grid, primitives, lazyCharts);
   move chart bodies from `DashboardCharts.tsx`.
2. Add the `cc-*` CSS block; switch `app/command-center/page.tsx` to `<CommandCenter/>`.
3. Build panels in narrative order: KPI strip → Margin hero → Proxy (hit-rate,
   latency) → Quality table, each with skeleton + empty/null states.
4. Revert the Command Center insertions from `EngineViews.tsx`; delete
   `CommandCenterDashboard.tsx`. If you approve §3's relocation, add the
   decision-queue/recent-actions/top-waste to the Engine page.
5. Verify: `tsc --noEmit`, `eslint`, `next build`; then run `npm run dev` against a
   seeded project and check no-scroll + fluid collapse at 1280/1440/1920 widths and
   720/900/1080 heights.

---

## 9. Open decisions for your approval

1. **IA (§3):** relocate decision-queue/recent-actions/top-waste to Engine
   (recommended), or keep a compact decision-queue right-rail on Home?
2. **Small-viewport fallback (§2.5):** accept the graceful scroll fallback below
   ~680px tall / ~1100px wide, or hold a stricter constraint?
3. **Row weighting (§2.2):** default `1.3fr / 1fr` (favor the hero savings chart) —
   adjust if you want the quality table taller.

No code is written until you sign off on these three.
