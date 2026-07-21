# Varsten Inbound Playbook: 0 to 1

Companion to `GTM_PLAYBOOK.md`. That document is the outbound motion; this one is how prospects
find Varsten on their own and convert without a cold email. Written 2026-07-19.

The one-sentence strategy: **ship one remarkable interactive asset (the client-side Waste
Analyzer), surround it with a small set of high-intent pages (comparisons, integrations,
methodology), make the free observe tier genuinely self-serve, and let launches and honest
engineering content drive the first traffic while search compounds in the background.**

---

## 0. Honest framing: what inbound can and cannot do at this stage

A new domain has near-zero search authority. SEO compounds on a 6-12 month horizon, not a
6-week one. So at 0 to 1, inbound has three jobs, in priority order:

1. **Convert the demand outbound creates.** Every cold email recipient and event contact
   Googles you before replying. The site's job is to survive that check and lower the reply
   threshold. This pays off in week one, not month six.
2. **Scale the teardown.** The GTM playbook's Rung 0 (48-hour spend teardown) costs 1-2 hours
   each of your time. The Waste Analyzer is the same offer, self-serve, at zero marginal cost.
   This is the single highest-ROI inbound build.
3. **Plant compounding assets.** Comparison pages, integration docs, and pricing-data pages
   that rank in months 3-12 and convert forever.

What inbound will not do: land customer #1. That comes from the outbound playbook's warm
network and teardowns. Budget accordingly: inbound gets at most 30-40% of GTM time, and the
build items below are scoped in days, not weeks. None of this touches engine surface area;
it is all marketing-site and docs work, so it does not compete with the capacity gate.

## 1. The Waste Analyzer (build it, and build it client-side)

**Verdict: yes.** This is the flagship inbound asset, and the market check confirms the gap:
the "LLM cost calculator" space is saturated (10+ free tools doing hypothetical tokens ×
price), but nothing analyzes a *real traffic export* for savings opportunities. Hypothetical
calculators answer "what would X tokens cost." The analyzer answers "here is what you are
wasting," with the user's own data. Different category, no incumbent, perfectly on-brand.

### Why it works
- It is the teardown productized. The GTM funnel's most expensive step becomes self-serve.
- **Client-side execution is the differentiator and the security story in one.** Parse the
  file in the browser, run every heuristic in JS, never send content to a server. The tagline
  writes itself: "your data never leaves your browser." That claim is checkable in DevTools,
  which is exactly the kind of verifiable honesty the brand runs on. It also previews the
  product's posture (metadata-only ledger, zero retention).
- It is a launchable artifact. "Show HN: I built a client-side analyzer that finds the money
  you're wasting on LLM calls" is a credible HN post in a way "I built another AI startup" is not.
- Every run is a qualified lead signal: anyone who exports their usage and uploads it has
  real spend and real pain.

### Spec (keep it to ~1-2 weeks of marketing-site work)
- **Inputs:** OpenAI usage export CSV first (the one every target can produce), then a
  documented generic JSONL schema. Later: Helicone and LiteLLM log export formats. Accepting a
  competitor's export format is quiet, effective positioning: "already on Helicone? Export your
  logs and see what observability alone is leaving on the table."
- **Analysis, mirroring the levers (heuristics, all labeled estimated):**
  - Duplicate and near-duplicate prompt hashing → cache opportunity, priced at avoided cost.
  - Input:output token ratio per route/model → trim and prompt-cache restructure opportunity.
  - Request timing patterns and non-interactive shapes → batchable volume × the flat batch discount.
  - Model mix vs task shape (e.g. big model on short classification-shaped calls) → downshift
    candidates, explicitly flagged "requires eval verification, this is what the pilot proves."
  - Pricing from a build-time JSON snapshot of the public catalog (`make sync-prices` output).
    The versioned catalog is already maintained; exporting it is nearly free.
- **Output:** headline number ("estimated $X/mo recoverable, Y% of analyzed spend"), then a
  per-lever breakdown table, then the honesty block: "these are estimates from heuristics. The
  product measures the real number with a randomized holdback. Here's how →" linking the
  methodology page.
- **Gating: do not hard-gate.** Show everything without an email. At 0 to 1 you want
  conversations and shares, not a mailing list. Offer two CTAs at the bottom: "get the
  human version: free 48-hour teardown" (email capture with intent) and "watch it live:
  connect observe mode, free." Optionally an email field to send yourself the report PDF.
  A hard email gate would also kill the HN launch.
- **Claims discipline carries over:** every number labeled estimated, never "guaranteed,"
  ranges not point estimates. The analyzer is the brand's honesty, demonstrated.

## 2. Search: high-intent only, three tiers, skip the rest

Do not chase "LLM cost optimization" head terms; nOps, Portkey, and content farms own them
and the intent is mushy. A no-authority domain wins narrow, high-intent, underserved queries.

**Tier 1 (build now): comparison and alternative queries.** "Helicone alternatives,"
"LiteLLM vs Portkey," "Portkey pricing," "[competitor] for cost optimization." Bottom-of-funnel
buyers actively choosing tooling, low competition (competitors rarely write good pages about
each other), and the pages double as sales collateral for outbound (see section 3).

**Tier 2 (build when Tier 1 is live): integration queries.** "LangChain cost tracking,"
"Vercel AI SDK caching," "track OpenAI costs per customer," "OpenAI batch API discount."
Served by the integration docs in section 4. Developers searching these are mid-integration
with money on the line.

**Tier 3 (only if cheap): pricing-data pages from the versioned catalog.** The generic
calculator space is saturated, so do not build a me-too calculator. The catalog's unique
angle is *versioned history*: "GPT-4o price history," "what did Claude cost in 2025," "LLM
price changes 2026." Nobody maintains this well because nobody else has effective-dated
pricing as a first-class data asset. Auto-generate from the catalog, near-zero marginal
maintenance. Modest volume, but the pages earn citations and backlinks from people writing
about price drops, and backlinks are what make Tiers 1-2 rank.

**Answer-engine optimization matters as much as Google now.** Your buyers ask ChatGPT and
Claude "how do I cut my OpenAI bill" and "Helicone vs Portkey." What gets cited: clean,
crawlable, factual pages with tables and dates; an `llms.txt`; being mentioned in the
comparison listicles that already rank (pitch the authors of "best LLM gateway 2026" posts
to include Varsten; those articles are answer-engine source material). Same work as SEO,
second payoff channel.

**Technical hygiene (one afternoon):** SSG every marketing page, sitemap.xml, schema.org
(Organization, Product, FAQPage on the FAQ), OG images, `llms.txt`, fast LCP. The site is
Next.js on Vercel; none of this is hard. **Skip paid search entirely**: CAC math cannot work
pre-case-study, and the head terms are bid up by funded competitors.

## 3. Comparison pages: yes, honest, category-reframing

Build `/compare/litellm`, `/compare/helicone`, `/compare/portkey`. The angle is not "we're
better," it is **"different category, and here's the gap nobody talks about."**

The reframe each page teaches: gateways and observability are infrastructure you operate;
Varsten is a savings outcome with verified measurement. The "interesting knowledge the others
are missing" is the measurement gap, and it is a genuinely underwritten topic:

- A cache hit's savings are directly measurable. A routing change's savings are not, unless
  you ran a concurrent randomized control. No gateway does this. Their "40-70% savings"
  claims are modeled counterfactuals that can't survive a CFO asking "how do you know we
  wouldn't have saved anyway?"
- Quality regression from routing is invisible without a live baseline. Dashboards show cost
  going down; they cannot show quality going down with it.
- A savings number without a confidence interval is a marketing number.

Structure per page: what [competitor] is genuinely good at (be specific and fair), where the
category stops (you operate it, you interpret it, you own the quality risk, you can't verify
the number), a factual capability table, and the "when to choose them" section written
straight. Recommending LiteLLM to self-hosters who want infrastructure is what makes the rest
of the page believable. Facts only from their public docs, dated, corrected on request.

One shared explainer underneath: "Why LLM savings numbers are usually fiction" (the
methodology one-pager from the GTM playbook, expanded). Every comparison page links it; it is
the page you want HN to argue about.

## 4. Integrations as distribution: mostly documentation, ship it

**Verdict: yes, and it is cheaper than it sounds.** Varsten mirrors the OpenAI, Anthropic,
and Gemini APIs, so "integrating" with LangChain, the Vercel AI SDK, LlamaIndex, or any
OpenAI-compatible client is base URL + `vk_` key. The work is documentation, not engineering:

- One docs page per framework: LangChain (Python/JS), Vercel AI SDK, LlamaIndex, plus raw
  OpenAI/Anthropic SDK pages (partly written already in `marketing/content/docs/`). Each page:
  the 2-4 line diff, what the fail-open SDK adds (direct-to-provider fallback), what shows up
  in the dashboard, and the free observe-mode CTA. Each page is also a Tier 2 search page.
- Copy-paste-complete snippets. A developer should go from the page to traffic in the
  dashboard in under 10 minutes; the self-serve walkthrough already proves the path.
- **Official directory listings are phase 2, not now.** Getting into LangChain's integrations
  docs or Vercel's marketplace carries a review process and an implicit maintenance SLA.
  Solo, pre-first-customer, that commitment is premature. Do it once a customer exists and
  the pilot cadence is stable. Community "awesome-llm" GitHub lists, however, are free
  backlinks with no SLA: PR yourself into them this month.

## 5. The conversion path (make the landing page one funnel)

The existing hero ("Cut your AI bill without changing your code.") holds. Order the page as one
argument: claim → interactive proof (Waste Analyzer, embedded or one click away) → how the
number is verified (methodology) → what it costs (25% of verified, $0 if $0) → two CTAs.

- **Primary CTA everywhere: run the analyzer.** It is the lowest-friction high-signal action.
  Secondary: "connect observe mode free" for the already-convinced.
- Observe-mode signup must be genuinely self-serve end to end (MASTER_PLAN Phase 8 finishes
  this). Every hour between "convinced" and "data flowing" leaks leads you cannot afford.
- Add the security page prominently in the nav path: for this product, the security story is
  a conversion feature, not compliance boilerplate.
- Analytics: a privacy-respecting tool (Plausible/Fathom class), events on analyzer runs,
  teardown requests, and observe signups. No creepy tracking on a site whose pitch is
  "we don't even look at your data."

## 6. Launch and distribution calendar (traffic before SEO exists)

Traffic in the first 90 days comes from launches and communities, not search:

1. **Show HN: the Waste Analyzer.** The client-side angle is the hook. Tuesday morning ET,
   plain title, first comment from you explaining heuristics and inviting correction.
2. **The methodology essay** ("why LLM savings numbers are fiction") as a separate HN/X post.
3. **Product Hunt for the analyzer** (not "Varsten the platform"), a few weeks after HN.
4. **Listicle outreach:** the "best LLM gateway 2026" articles already ranking. Short pitch,
   the honest one-liner, the analyzer as the demo link.
5. **Community answers, not community spam:** when LLM-cost threads appear on HN/r/LocalLLaMA/
   X, answer with substance and link the analyzer only when it genuinely fits.
6. Every launch, listicle mention, and awesome-list PR is a backlink; backlinks are the input
   that makes sections 2-4 rank. The channels feed each other.

## 7. Metrics

Weekly, alongside the GTM scorecard: unique visitors, analyzer runs, analyzer → teardown
requests, analyzer → observe signups, observe signups total, ranking movement on the ~15
target queries (check monthly, not weekly). The number that matters most at 0 to 1:
**analyzer runs by people you did not email.** That is inbound existing.

## 8. 90-day inbound plan (interleaved with the GTM playbook's plan)

**Weeks 1-2 (alongside GTM packaging):** technical SEO hygiene afternoon; publish methodology
page; PR into 3-5 awesome-lists; analytics wired.
**Weeks 3-5:** build the Waste Analyzer (OpenAI CSV + generic JSONL first). Publish the three
comparison pages while the analyzer is in progress (they are writing, not building).
**Week 6:** Show HN launch. Teardown CTAs ready to absorb the spike, 48-hour SLA held.
**Weeks 7-10:** integration docs pages (LangChain, Vercel AI SDK, LlamaIndex). Methodology
essay launch. Listicle outreach.
**Weeks 11-13:** Product Hunt. Helicone/LiteLLM import formats for the analyzer. Tier 3
pricing-history pages only if pilots are stable and time allows. Review metrics; kill what
produced nothing, double what produced analyzer runs.

## 9. What NOT to do

- A me-too token pricing calculator (saturated; ten free ones exist).
- Paid search or social ads pre-case-study.
- A high-volume AI-generated blog. Ten thin posts hurt the domain and the brand; the brand
  is rigor.
- Hard email-gating anything. Optimize for conversations, launches, and shares.
- Official framework directory listings before the first paying customer (maintenance SLA
  you cannot yet honor). Community lists yes, official registries later.
- Building analyzer features server-side for convenience. Client-side is the point; the
  moment content touches your server, the best line in the pitch dies.
