# Inbound Implementation Plan (for Sonnet 5)

Build instructions for the marketing-site work called for in `docs/gtm/INBOUND_PLAYBOOK.md`.
The playbook is the *why*; this document is the *what and how*, ordered for an implementer to
execute end to end. Written 2026-07-20 against the current `marketing/` codebase.

**Read this whole "Ground rules" section before writing any code.** It is the contract every
work package inherits. Then execute the work packages in order; each is self-contained and ends
at an approval gate.

---

## Ground rules (apply to every work package)

### G1. Approval gates are mandatory

Aaron signs off on every new page, every new UI surface, and every change to an existing UI
surface **before it merges to `main`**. Concretely:

- Do all work on a feature branch (one branch per work package, named `inbound/wp-N-slug`).
  Never commit directly to `main`.
- At the end of each work package, **stop.** Post a summary of what was built, how to view it
  (the exact `npm run dev` route), and any decisions that need Aaron's call. Do not start the
  next work package until he approves the current one.
- Work packages that add or change visible UI (WP2, WP3, WP4, WP5, WP6) must be shown running
  — screenshots of the actual rendered route at desktop (1440px) and mobile (390px) widths, in
  the summary — before merge. Use the `run` skill / `npm run dev` on port 3100 (see the
  onboarding-flow memory) to render them.
- Anything that makes a competitive claim (WP3) or a savings claim (WP4) requires Aaron's
  explicit line-by-line approval of the copy, because these are the two places the brand's
  credibility is most exposed.

### G2. The brand style guide is law

`BRAND_STYLE_GUIDE.md` at the repo root is the source of truth for all visual design. Every new
element must pass its section-12 "Is it on-brand?" checklist. The non-negotiables, restated so
you cannot miss them:

- **One accent only:** blueprint `#1447e6`. No gradients, no shadows, no second accent, no color
  outside the ink `#111` / ink-soft `#6b6b6b` / white trio plus blueprint.
- **Sharp corners, hairline borders.** `border border-border` (`#e5e5e5`) does the work that
  shadows do elsewhere. Card grids use the `grid gap-px border border-border bg-border` trick so
  the 1px gaps read as continuous gridlines.
- **Never hard-code hex values in components.** Use the semantic Tailwind tokens already wired in
  `app/globals.css`: `bg-background`, `text-ink`, `text-ink-soft`, `text-blueprint`,
  `border-border`, `bg-muted`, `bg-ink`, `text-primary-foreground`. The one existing exception is
  the near-black code panel `bg-[#0a0a0a]` / `bg-ink`; match that, don't invent new hexes.
- **Mono metadata is a design element.** Eyebrows, labels, tags, spec footers, timestamps use the
  `mono` utility, uppercase, `tracking-[0.18em]`–`tracking-[0.28em]`, sizes `10px`–`12px`. Every
  section gets a document-style code (e.g. `Section 04 · Analyzer`, `Doc / 002`).
- **Status marker is a 6×6 blueprint square** (`inline-block h-1.5 w-1.5 bg-blueprint`), never a
  circle. Trailing arrows are the literal `→` glyph.
- **Motion:** only `transition-opacity` / `transition-colors` at default duration. No transforms,
  no scale-on-hover, no scroll animations.
- **Icons:** `lucide-react` is NOT a dependency of `marketing/` (check `package.json` — it isn't).
  The brand guide mentions it aspirationally, but the shipped site uses typographic marks (`→`,
  `·`, `—`, the blueprint square) and hand-rolled inline SVG (see the chevron in `Nav.tsx`). Do
  the same. **Do not add `lucide-react`** or any icon library.

### G3. Use your judgement for page scaffolding, the home page, docs pages, priving page, and faq page are all complete and should be the first source of truth for scaffolding, but dsign is still fluid and changing overall in terms of layout per page.


### G4. Engineering standards (match what exists, don't regress it)

- **Server/client split:** a route page (`app/*/page.tsx`) stays a **server component** so it can
  `export const metadata` via `pageMetadata()`. Anything interactive (state, file parsing, tabs)
  goes in a **client** component (`"use client"`) under `components/varsten/<feature>/`, imported
  by the server page. The FAQ page → `FaqAccordion`, and the pricing page → `SavingsCalculator`,
  are the pattern to copy. The home page is `"use client"` as a whole; do not use it as your model
  for new pages — prefer the server-page-imports-client-component pattern so metadata stays static.
- **Small, pure functions and small components.** Read `SavingsCalculator.tsx`: it decomposes a
  complex widget into ~20 tiny named functions/components. The codebase is written to a low
  per-function complexity budget (the backend enforces one; the frontend is written to match).
  Follow that granularity. Do not write 200-line components.
- **Metadata:** use `pageMetadata({ title, description, path })` from `lib/seo.ts` for every new
  route. Titles follow the existing `"<Page> — Varsten"` form.
- **Structured data:** use `StructuredData` + the `breadcrumbList()` helper from `lib/seo.ts`.
  Add new JSON-LD builders to `lib/seo.ts`, don't inline raw objects in pages.
- **Analytics:** every new event name must be added to the `ANALYTICS_EVENTS` union in
  `lib/analytics/events.ts` or `trackMarketingEvent` will reject it. **Critical footgun:**
  `events.ts` silently drops any property whose key contains `token`, `name`, `email`, `prompt`,
  `message`, `completion`, `key`, `secret`, `body`, or `form`. So a prop called `model_name` or
  `input_tokens` will vanish. Name analyzer props around this (`top_model`, not `model_name`;
  `estimated_savings_pct`, not `token_savings`). Never send content or per-row data through
  analytics regardless.
- **Routing:** every new route must be added to `staticRoutes` in `app/sitemap.ts` and linked
  from `Nav.tsx` and/or `Footer.tsx` (WP6 handles the nav/footer wiring centrally — but add the
  sitemap entry in the same WP that creates the route).
- **Responsive + no overflow:** every page works at 390px and 1440px. No horizontal scroll (the
  site sets `overflow-x: clip` globally; do not rely on it to hide a real layout bug). Wide
  tables/code scroll inside their own `overflow-x-auto` container.
- **Accessibility:** file inputs, tabs, and buttons need labels, visible focus, and keyboard
  operation. Match the `aria-*` usage already in `Nav.tsx` and `SavingsCalculator.tsx`.
- **No new dependencies without flagging.** CLAUDE.md requires flagging any third-party package.
  The only place a new dep is plausibly justified is CSV parsing in WP4; that decision is called
  out there and needs Aaron's sign-off.

### G5. Claims discipline (this is the whole brand)

From CLAUDE.md and the playbook: Varsten's single differentiator is honesty about numbers. Every
piece of copy you write obeys this:

- **Never** "guaranteed," never a suspiciously exact point estimate, never "40–70%." Use ranges,
  and label every projected number **"estimated."**
- The word **"verified"** is reserved for numbers the product measures with the holdback A/B. A
  heuristic on an uploaded file is **"estimated,"** always. Keep the two words rigidly separate;
  that separation is the product.
- Routing and model-downshift savings are **"estimated, requires eval verification"** — never
  presented as bankable, because they change model behavior and only the eval gate proves them safe.
- Match the real lever vocabulary from `backend/app/levers.py`: Smart routing, Semantic cache,
  Token trim, Model downshift, Batching, Prompt compression. Do not invent lever names.
- Existing copy already models this (see `SavingsCalculator`'s "Estimate only — billing uses
  verified production savings" footer). Reuse that voice.

---

## Work package order and rationale

Ordered by the playbook's ROI logic (§0: convert demand first, then scale the teardown, then plant
compounding assets) and by dependency (later packages link to earlier ones):

1. **WP1 — Technical SEO hygiene.** One afternoon, unblocks everything, playbook §2.
2. **WP2 — Methodology page.** The honesty anchor WP3 and WP4 both link to. Playbook §2/§3.
3. **WP3 — Comparison pages.** Highest-intent search + outbound collateral. Playbook §3.
4. **WP4 — The Waste Analyzer.** The flagship. Depends on WP2 existing to link to. Playbook §1.
5. **WP5 — Integration docs pages.** Compounding Tier-2 search. Playbook §4.
6. **WP6 — Nav, footer, sitemap, and conversion-path wiring.** Ties the new routes into the site
   and makes "run the analyzer" the primary CTA. Playbook §5.
7. **WP7 — (Deferred) pricing-history pages.** Tier 3, only if time. Playbook §2.

---

## WP1 — Technical SEO and answer-engine hygiene

**Why (playbook §2):** A new domain wins by being clean, crawlable, and citable — by Google and by
ChatGPT/Claude. This is cheap and compounds. Do it first so every later page inherits it.

**Build:**

1. **`llms.txt`.** Add `app/llms.txt/route.ts` (a route handler returning `text/plain`), or a
   static `public/llms.txt`. Prefer the route handler so it can reuse `SITE_URL` and enumerate
   docs from `getAllDocs()`. Content: one-paragraph description of Varsten (pull the honest
   framing from CLAUDE.md — savings engine that proves the number, not a dashboard), then a
   curated link list (home, pricing, proof, security, methodology once WP2 lands, the comparison
   pages once WP3 lands, docs quickstart). Keep it factual and short. Add a matching `Allow`
   note; do not disallow it in `robots.ts`.
2. **Organization + Product/SoftwareApplication JSON-LD** on the home page. Add builder functions
   to `lib/seo.ts` (`organizationSchema()`, `softwareApplicationSchema()`) and render them via
   `StructuredData` in `app/page.tsx` (the home page is a client component; add a small
   server-rendered `<StructuredData>` is fine since it's just a script tag — or lift the schema
   into `app/layout.tsx`'s metadata-adjacent area. Cleanest: render `<StructuredData>` inside the
   home `<main>`). Use only claims that are true and on the site already. No fabricated ratings.
3. **`FAQPage` JSON-LD** on `/faq`. The Q&A already lives in `FaqAccordion.tsx`'s `FAQ_ITEMS`.
   Export that array (or lift it to `lib/content/faq.ts`) so both the accordion and a new
   `faqPageSchema()` builder consume one source. Render `<StructuredData>` on the FAQ page.
   **Do not duplicate the Q&A text** — single source, imported twice.
4. **Confirm the sitemap + robots are correct** after each later WP adds routes (WP6 does a final
   pass). No change needed now beyond noting it.

**Acceptance:** `/llms.txt` returns plain text; `curl` of `/` and `/faq` HTML contains the JSON-LD
`<script type="application/ld+json">`; Google's Rich Results structure is valid (paste into the
validator or eyeball the JSON shape against schema.org). No visual change to any page, so no
screenshot gate — but still branch + sign-off per G1.

**Checkpoint — sign-off before merge.**

---

## WP2 — Methodology page (`/methodology`)

**Why (playbook §2, §3, §10):** "How we measure savings" is the single highest-leverage document
in the inbound strategy. It is the honesty anchor the comparison pages and the analyzer both link
to, it is the objection-handler for "how do I know the number is real," and it is the essay you
want HN to argue about. Build it as a real page, not a doc.

**Build a new route `app/methodology/page.tsx`** (server component, `pageMetadata`), composed from
the scaffolding in G3. Suggested structure (adapt within brand, but hit these beats):

- `SecondaryHero` — eyebrow `Methodology`, title along the lines of "How Varsten measures savings,"
  description stating plainly that most savings numbers in this market are modeled counterfactuals
  and Varsten's are a measured A/B result.
- `SecondarySection` "The problem with a savings number" — why a point estimate with no control is
  a marketing number; why "we would have saved anyway" is the objection that kills trust.
- `SecondarySection` "Concurrent randomized holdback" (`tone="muted"`) — explain the mechanism from
  CLAUDE.md's "two load-bearing architecture decisions §1": a small random % of traffic stays on
  the unoptimized incumbent, savings are the measured cost delta between arms, app-level changes
  land on both arms and cancel, provider price moves hit both and cancel. Use a `NumberedList` or
  `CardGrid` for the four properties. This is the intellectual core — get it exactly right against
  CLAUDE.md; do not embellish.
- `SecondarySection` "Estimated vs verified" — a short, sharp definition block (a 2-cell `CardGrid`
  works): *estimated* = a heuristic projection (what the analyzer produces); *verified* = a measured
  holdback result billed against. This section is what the analyzer links back to.
- `SecondarySection` "What you can audit" — raw per-request assignment and costs are exposed;
  confidence intervals, not point estimates; quality drift monitored against the same control arm.
- `PageCta` — `intent="observe"` to `START_OBSERVE_HREF` ("see it on your own traffic, free").

Add a `breadcrumbList` + consider an `Article`/`TechArticle` JSON-LD builder in `lib/seo.ts` so the
essay is answer-engine-citable.

**Copy source of truth:** CLAUDE.md "The two load-bearing architecture decisions" and "Quality is a
measurement loop." Do not exceed what those claim. All numbers ranged and labeled estimated;
"verified" only for the holdback output.

**Acceptance:** route renders at `/methodology`, desktop + mobile screenshots, sitemap entry added,
JSON-LD present, all links resolve. **Requires Aaron's copy approval (G1).**

**Checkpoint — sign-off before merge.**

---

## WP3 — Comparison pages (`/compare/[competitor]`)

**Why (playbook §3):** Bottom-of-funnel "Helicone alternatives" / "LiteLLM vs Portkey" queries are
low-competition and high-intent, and the pages double as outbound collateral. The angle is
**category reframe, not feature war**: gateways/observability are infrastructure you operate;
Varsten is a verified savings outcome.

**Architecture:** one dynamic route `app/compare/[slug]/page.tsx` (server component) driven by a
typed data file `lib/content/comparisons.ts`, exactly mirroring how `docs/[slug]` is driven by
`lib/content/docs.ts`. This keeps all three pages consistent and lets you add a fourth later by
adding a data entry, not a file.

- `lib/content/comparisons.ts` exports a `Comparison` type and a record for `litellm`, `helicone`,
  `portkey`. Each entry: display name, one-line "what they're genuinely good at," the category
  they occupy, a `capabilities` table (rows = capability, cells = factual yes/partial/no for
  them vs Varsten), a "where the category stops" list, and a straight "when to choose them"
  paragraph. `generateStaticParams()` from the record keys; `generateMetadata()` via `pageMetadata`.
- Page layout: `SecondaryHero` (eyebrow `Compare`, title "Varsten vs [Name]"), a `SecondarySection`
  with the capability table (build a small `ComparisonTable` component under
  `components/varsten/compare/` — hairline grid, mono column headers, blueprint square for "yes",
  em-dash for "no", honest "partial" text; wrap in `overflow-x-auto`), a `SecondarySection`
  "Where [Name] stops" (`NumberedList`), the fair "When [Name] is the right call" block, and a
  shared explainer that links to `/methodology` ("Why savings numbers are usually fiction"). End
  with `PageCta intent="observe"`.
- Add `breadcrumbList` JSON-LD.

**Content rules (these protect the brand — enforce them):**

- **Only verifiable public facts.** Every claim about a competitor must come from their public
  docs/pricing as of the build date. Add a dated mono footer per page: `Sourced from public docs ·
  Rev. 07·2026 · corrections: contact@varsten.ai`. Do not assert internal behavior you can't cite.
- **Be genuinely fair.** The "when to choose them" section must be real advice (e.g. recommend
  LiteLLM to teams that want a self-hosted open-source gateway they operate themselves). A page
  that only trashes the competitor is not credible and violates the brand's honesty stance.
- The reframe content (measurement gap: a routing change's savings are unknowable without a
  concurrent control; dashboards show cost dropping but not quality dropping) comes from the
  playbook §3 and CLAUDE.md. Keep it accurate.
- **This WP requires line-by-line copy approval from Aaron before merge (G1)** — competitive claims
  are legal/brand-sensitive. Present the full text of all three pages in the checkpoint summary.

**Acceptance:** `/compare/litellm`, `/compare/helicone`, `/compare/portkey` render; static params
generate all three; desktop + mobile screenshots; sitemap entries added; JSON-LD present; table
scrolls cleanly on mobile.

**Checkpoint — sign-off before merge.**

---

## WP4 — The Waste Analyzer (`/analyzer`) — flagship

**Why (playbook §1):** This is the single highest-ROI inbound build. It productizes the 48-hour
teardown at zero marginal cost, it is the Show HN launch asset, and its client-side execution is
both the differentiator and the security story ("your data never leaves your browser," checkable
in DevTools). Treat client-side as a hard requirement, not a convenience.

**Non-negotiable constraints:**

- **100% client-side.** The uploaded file is parsed and analyzed in the browser. **No byte of file
  content, and no per-row derived data, is ever sent to any server** — not to `/api`, not to
  analytics, not anywhere. Acceptance is verified in the Network tab: uploading a file produces
  zero network requests carrying its content. This is the whole pitch; do not violate it for
  convenience (e.g. don't "just POST it to an endpoint for parsing").
- **No hard gate.** Show the full result without an email. Two CTAs live *below* the result, not in
  front of it (playbook §1). A gate would also kill the HN launch.
- **Claims discipline (G5) applies to every number the analyzer prints.**

**Structure:**

- `app/analyzer/page.tsx` — server component, `pageMetadata`, plus a `SoftwareApplication` or
  `WebApplication` JSON-LD builder. Renders the client component. Keep a short server-rendered
  intro (`SecondaryHero`) above the interactive widget so the page has crawlable copy and the
  "runs entirely in your browser" promise is in the static HTML.
- `components/varsten/analyzer/WasteAnalyzer.tsx` — the `"use client"` root, decomposed into small
  components exactly like `SavingsCalculator` (file dropzone, format detector, results header,
  per-lever table, honesty block, CTA row). Split logic out of the JSX into pure functions under
  `lib/analyzer/`.

**Input formats (be honest that depth scales with input richness):**

1. **OpenAI usage export CSV** — the file every target can produce. Note the important truth: this
   export is **aggregated** (date, model, request counts, context/generated token totals). It has
   **no prompt content**, so cache-dedup is impossible from it. From it you can compute: spend by
   model, input:output ratios, model-mix downshift candidates, and a batchable-share estimate.
   State in the UI what this input can and can't unlock. This honesty is on-brand, not a weakness.
2. **Generic per-request JSONL** — document a schema in a new doc (WP5-adjacent, or inline on the
   page) mirroring the ingestion payload in CLAUDE.md, with **optional** `messages`/`prompt` fields.
   When those are present, dedup hashing and timing analysis become possible — and the copy states
   plainly that hashing happens locally and the text is never transmitted. This unlocks the full
   analysis and is the format to nudge power users toward.
3. Helicone / LiteLLM export formats — **defer to a follow-up** (playbook §1 lists them as "later").
   Structure the format detector so adding them later is a new parser module, not a rewrite.

**Pricing data (build-time snapshot, no runtime backend dependency):**

- Add `scripts/generate-pricing-snapshot.mjs` that fetches the same public LiteLLM dataset
  `backend/scripts/sync_prices.py` uses, filters to the model set the analyzer needs, and writes
  `lib/analyzer/pricing-catalog.json` with `{ generatedAt, source, models: {...} }`. **Commit the
  generated JSON** so the build and the browser never depend on a network fetch. Document a refresh
  command in `marketing/README.md`. This mirrors the "build-time JSON snapshot of the public
  catalog" the playbook §1 specifies and reuses the maintained catalog instead of hand-keying prices.

**Heuristics (all output ranges, all labeled estimated; map each to a real lever from `levers.py`):**

- **Semantic cache / exact cache** — only when per-request content is available (JSONL with
  messages). Hash normalized request signatures locally, estimate avoided cost from duplicate rate.
  If input lacks content (OpenAI CSV), show this lever as "needs per-request logs to estimate" —
  do not fabricate a number.
- **Token trim / prompt-cache restructure** — flag routes/models with a high input:output ratio
  (threshold ~8, matching the product's own detection). Estimate a conservative recoverable share
  of input tokens. Range it.
- **Batching** — estimate the flat batch discount (~50%) on the share of volume that looks
  non-interactive/batchable. From CSV this is a coarse estimate; say so.
- **Model downshift** — expensive frontier model on short, classification-shaped calls → flag as a
  **candidate**, explicitly labeled "estimated · requires eval verification, this is what a pilot
  proves." Never present downshift as bankable savings (G5).

**Output:**

- Headline: `estimated $X–$Y/mo recoverable (~Z% of analyzed spend)` — a range, never a point.
  Use the dark-panel treatment (`bg-ink text-primary-foreground`) like `SavingsCalculator`'s
  estimate panel for visual consistency.
- Per-lever breakdown: a hairline-grid table (lever name, estimated range, one-line basis,
  confidence caveat). Reuse `CardGrid`/`InfoCard` or a small table component in the brand grid style.
- **Honesty block** (required): "These are estimates from heuristics on your file. The product
  measures the real number with a randomized holdback — here's how →" linking `/methodology`. Plus
  the standing "runs entirely in your browser; nothing was uploaded" line, visible near the result.
- **CTA row** (below result): (1) "Get the human teardown" → the existing `LeadForm` with a new
  `source="analyzer"` (reuse the component; no new form). (2) "Watch it live — connect observe
  mode, free" → `START_OBSERVE_HREF`, via `TrackedLink`, `intent="observe"`.

**Analytics (respect the denylist, G4):** register `analyzer file parsed`, `analyzer report viewed`,
`analyzer cta clicked` in `ANALYTICS_EVENTS`. Send only aggregate, non-content signals with safe
key names: detected format, row-count bucket, analyzed-spend bucket, which lever opportunities are
present (booleans), estimated recoverable-percent bucket. Never send raw spend, per-row data,
model names under a `*name*` key, or anything token/prompt/content-derived.

**Dependency decision (needs Aaron's call, G4):** robust CSV parsing (quoted fields, embedded
commas) is the one place a small client-side library (`papaparse`, ~7kB, battle-tested, no runtime
network) is reasonable. Alternative: a tight internal parser for the two known formats. Recommend
`papaparse` for correctness, but **flag it in the checkpoint and let Aaron decide** rather than
adding it silently. JSONL needs no library (split lines, `JSON.parse`).

**Acceptance:**
- Upload an OpenAI usage CSV and a sample JSONL; both parse and produce a labeled, ranged result.
- Network tab shows **zero** requests carrying file content on upload/analyze.
- Every number says "estimated"; downshift says "requires eval verification"; no "guaranteed."
- Keyboard-accessible file input and dropzone; visible focus; works at 390px and 1440px; wide
  result table scrolls in its own container.
- Desktop + mobile screenshots in the checkpoint. **Requires Aaron's copy + dependency sign-off.**

**Checkpoint — sign-off before merge.**

---

## WP5 — Integration docs pages

**Why (playbook §4):** Because Varsten mirrors the OpenAI/Anthropic/Gemini APIs, "integrating" with
LangChain, the Vercel AI SDK, or LlamaIndex is a base-URL + `vk_` key change. So this is
**documentation, not engineering**, and each page is also a Tier-2 search asset ("LangChain cost
tracking," "Vercel AI SDK caching").

**Build:** add markdown files to `content/docs/` — the existing pipeline (`lib/content/docs.ts`,
`app/docs/[slug]/page.tsx`) picks them up automatically into the docs sidebar and sitemap. **No new
route or component is needed.** Read an existing file (`content/docs/integration-paths.md`) for the
exact frontmatter shape (`title, description, slug, category, order, updatedAt`) and voice.

New docs (category `Integrations`, ordered after existing docs):

- `langchain.md` — LangChain (Python + JS): the base-URL config, what the fail-open SDK adds
  (direct-to-provider fallback), what shows up in the dashboard, and the Base CTA.
- `vercel-ai-sdk.md` — same shape for the Vercel AI SDK (OpenAI-compatible provider config).
- `llamaindex.md` — same for LlamaIndex.

**Content rules:**

- Copy-paste-complete, correct snippets. A developer goes from page to dashboard traffic in <10
  minutes (the `SELF_SERVE_WALKTHROUGH.md` proves the path — align with it).
- Reuse the real base URLs and key scheme from the existing `Integrations.tsx` and docs; do not
  invent endpoints. Anthropic/Gemini host-root nuance is in the onboarding memory — respect it.
- Honest posture notes carry over: base-URL mode is not fail-open; the SDK path is. Say so, matching
  `integration-paths.md`.
- **Official framework directory listings (LangChain's registry, Vercel marketplace) are explicitly
  out of scope** (playbook §4: they carry a maintenance SLA not worth taking pre-customer). Do
  community `awesome-*` list PRs instead — but that is an off-repo action for Aaron, not a code task
  here. Note it in the checkpoint; don't attempt it.

**Acceptance:** three docs render under `/docs/*`, appear in the docs sidebar and sitemap, snippets
are copy-complete and accurate. Screenshots of one rendered page. Lower brand risk (docs template is
fixed) but still branch + sign-off.

**Checkpoint — sign-off before merge.**

---

## WP6 — Nav, footer, sitemap, and conversion-path wiring

**Why (playbook §5):** New pages are worthless if nothing links to them, and the landing page should
make "run the analyzer" the primary low-friction action. This WP ties everything together and is
done **after** the pages exist so links never dangle.

**Build:**

1. **Nav (`components/varsten/Nav.tsx`).** Add the new destinations to the existing dropdown data
   arrays — do not restructure the nav. Suggested: add "Analyzer" and "Compare" and "Methodology"
   into the appropriate `RESOURCE_GROUPS`/`INTEGRATE_GROUPS` entries (Analyzer fits an "Evaluate"
   or a new tools slot; Compare + Methodology fit "Learn"/"Evaluate"). Add matching labels to
   `PAGE_LABELS_BY_SEGMENT` so the breadcrumb-style page label renders (`analyzer`, `compare`,
   `methodology`). Keep the dropdown grid columns balanced (the component supports 3 or 4 columns).
   **Any nav change is a visible UI change → screenshot + sign-off.**
2. **Footer (`components/varsten/Footer.tsx`).** Add links to the new pages in the relevant column.
   Read the file first and match its existing grouping.
3. **Primary-CTA review (playbook §5).** The playbook wants "run the analyzer" as the primary
   site-wide low-friction CTA and observe-mode as secondary. **Do not unilaterally rewrite the hero
   or nav CTA** (currently "Start free trial") — that is a high-stakes UX/brand change. Instead,
   propose the specific change to Aaron in the checkpoint (e.g. add a secondary "Analyze my usage"
   CTA to the hero, keep "Start free trial" primary — or swap them) with a screenshot mockup, and
   let him choose. This respects G1's rule that UI changes are his call.
4. **Sitemap (`app/sitemap.ts`).** Confirm every new static route (`/methodology`, `/compare/*`,
   `/analyzer`) is in `staticRoutes` with sensible `priority`/`changeFrequency`. The `/compare/*`
   pages can be added statically (they're a known small set) or enumerated from
   `lib/content/comparisons.ts` the way docs are enumerated from `getAllDocs()` — prefer the latter
   for consistency. Docs added in WP5 are already auto-included.
5. **`llms.txt` refresh** — add the new high-value URLs (analyzer, methodology, comparisons) to the
   WP1 link list.

**Acceptance:** every new page reachable from nav and/or footer; no dangling links; sitemap complete;
desktop + mobile screenshots of nav (open dropdown) and footer; the hero-CTA proposal presented for
Aaron's decision rather than applied unilaterally.

**Checkpoint — sign-off before merge.**

---

## WP7 — (Deferred) Pricing-history pages

**Why (playbook §2, Tier 3):** "GPT-4o price history," "LLM price changes 2026" — modest volume, but
the versioned catalog is a data asset nobody else maintains, and these pages earn the backlinks that
make WP3/WP5 rank. **Only build if WP1–WP6 are shipped and pilots are stable** (per the playbook,
this is the lowest priority and competes with real customer work).

**Sketch (do not build without explicit go-ahead):** generate static pages per model from a catalog
snapshot (extend the WP4 `generate-pricing-snapshot.mjs` to include effective-dated history),
rendered in the brand table style, with `Product`/`Dataset` JSON-LD. Auto-generated, near-zero
maintenance. Full spec to be written when this is greenlit.

**Checkpoint — do not start without Aaron's explicit request.**

---

## Global acceptance checklist (run before every checkpoint)

- [ ] Work is on a `inbound/wp-N-slug` branch, not `main`.
- [ ] Passes the BRAND_STYLE_GUIDE §12 checklist (sharp corners, hairlines, one accent, mono meta,
      no shadows/gradients/rounded cards, tokens not hex).
- [ ] Reuses `SecondaryShell`/`SecondarySection`/`CardGrid`/`PageCta` etc.; no hand-rolled layout.
- [ ] Server page for metadata; interactive logic in a `"use client"` child; small components.
- [ ] New analytics events registered in the union; no property hits the PII denylist; no content
      leaves the browser.
- [ ] New routes in `sitemap.ts`, linked in nav/footer, JSON-LD where applicable.
- [ ] Every projected number is a labeled **estimate** and a **range**; "verified" reserved for
      holdback output; downshift/routing marked "requires eval verification."
- [ ] Responsive at 390px and 1440px; no horizontal overflow; wide content scrolls internally;
      keyboard-accessible; visible focus.
- [ ] `npm run lint` and `npm run build` clean.
- [ ] Desktop + mobile screenshots attached for any visible UI (WP2–WP6).
- [ ] Summary posted; **stopped for Aaron's sign-off.**
