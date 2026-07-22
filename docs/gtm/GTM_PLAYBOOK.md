# Varsten GTM Playbook: 0 to 1

The exact playbook for landing the first paying clients. Written 2026-07-19. This is a living
document: update the funnel numbers and the prospect list as reality reports back.

The one-sentence strategy: **sell a free, quantified savings teardown to founders of AI-native
products bleeding margin on inference, convert the teardown into an observe-only connect, convert
the observed number into a gain-share pilot on the safe levers, and turn the first verified
savings number into the case study that sells everyone after.**

---

## 1. Honest starting position

Strategy has to fit the actual constraints, so name them.

**Assets:**
- A working inline proxy with six levers, a randomized holdback that measures savings as an A/B
  experiment, and a metadata-only ledger. Nobody in the commodity gateway space does concurrent
  holdback measurement. This is the differentiator.
- Gain-share pricing (25% of verified savings, free observe mode). Zero-budget ask.
- Free observe-only mode already built. This is a productized audit, not a promise of one.
- Production infrastructure is most of the way there; backup and restore proof remains in progress.

**Constraints:**
- Solo founder, no brand, no references, no SOC 2 Type II. Enterprise is out of reach and should
  not be attempted. Target buyers who can say yes without procurement.
- The 200 RPS capacity gate is open. Pilots must run on routes comfortably below the proven
  ceiling (treat ~50 RPS sustained per pilot route as the working limit until the gate closes).
- Inline proxy = trust ask. The first conversation can never be "point your production traffic
  at my proxy." The ladder in section 5 exists to defer that ask until trust is earned.
- Time: you are relocating to NYC. Outreach volume must be small and high-quality, not spray.

## 2. Why there is a real wedge (market, mid-2026)

The pain is structural and worsening, and the tooling that exists does not solve it:

- AI-first SaaS companies are spending 40-50%+ of revenue on inference; average AI product gross
  margin is ~52% vs the 80% SaaS benchmark, and the fastest-growing AI startups run at ~25%
  gross margin. Inference is COGS, it scales with every user action, and boards have started
  asking about it. This is not a "nice to have savings" pitch, it is a margin-survival pitch.
- The gateway/observability layer is fully commoditized: LiteLLM (open source, self-host),
  Portkey (managed gateway + semantic cache), Helicone (observability + low-overhead proxy),
  OpenRouter, plus Datadog/Vantage on the visibility side. Several claim "40-70% savings."
- What none of them sell: a **verified** number. They sell infrastructure the customer operates
  and dashboards the customer interprets. The customer still does the work, still guesses whether
  routing hurt quality, and still can't tell finance what was actually saved vs what would have
  happened anyway.

**The falling-price objection, answered up front:** "model prices drop 10x/year, why pay you?"
Because margin is a ratio, not a bill. Prices fall, but usage and agent-loop volume grow faster,
and competitors get the same price cuts, so the margin problem persists. Also the holdback
design makes this concrete: provider price cuts land on both arms and cancel, so Varsten only
ever claims the delta it caused. That honesty is itself a differentiator against "we cut your
bill 60%" marketing.

## 3. Target buyer

### Primary ICP (the wedge)

**Company:** AI-native product companies, seed to Series B, 5-50 people, where LLM calls are in
the product's serving path and token spend is COGS.

**Spend band: $5k-$75k/month on LLM APIs.**
- Below $5k the 25% gain-share on maybe 20-30% savings is < $500/mo. Not worth either side's time
  except as a design partner with growth trajectory.
- Above ~$75k you start hitting security review, SOC 2 demands, and platform teams who think
  "we'll build it with LiteLLM." Come back for them after the case study and SOC 2.

**Segments where the levers bite hardest (in priority order):**
1. **AI customer support / CX agents** (Fin competitors, vertical support bots). Huge repeat-query
   overlap (cache), stable system prompts (compression/trim), classification steps (downshift).
2. **Document processing / extraction** (legal, insurance, health admin, finance ops). High
   input-token ratios (trim, prompt-cache restructure), batchable jobs (batching = arithmetic
   savings, no trust required).
3. **AI SDR / sales and marketing content generation.** Batchable, template-heavy, non-latency-
   sensitive. Batching + cache land immediately.
4. **Agent products** (coding agents, browser agents, workflow automation). Redundant-call
   detection and loop waste; spend grows superlinearly with usage so pain is acute.
5. **Consumer AI apps with per-seat or freemium pricing** (tutoring, companions, writing tools).
   Thin or negative per-user margin; the Analysis > Customers negative-margin view lands here.

**Person:** the technical founder or CTO. At this size they read the OpenAI invoice themselves,
they feel the margin problem personally (their board asks about it), and they can say yes in one
call. Do not sell to a FinOps persona yet; that persona barely exists at this company size.

### Disqualifiers (walk away fast)
- Spend under $2k/mo with no growth story.
- Enterprise procurement or a hard SOC 2 requirement today.
- Traffic dominated by a single route above the capacity ceiling.
- Content cannot transit a third party at all (defense, some health). Revisit when in-VPC ships.
- "We already run LiteLLM/Portkey and a platform team owns it." Long conversation, low odds now.
  Note them for later; the pitch to them eventually is "keep your gateway, we're the savings and
  proof layer," but do not spend pilot slots on it.

## 4. Positioning and differentiation

**One-liner:** Varsten cuts your AI bill and proves every dollar. You pay 25% of verified
savings. If we save you nothing, you pay nothing.

**The three claims, in order:**
1. **It executes, not reports.** Dashboards tell you you're bleeding; Varsten stops the bleeding.
   Cache, trim, batch, route, downshift, compress, applied for you with guardrails.
2. **The number is verified, not modeled.** A concurrent randomized holdback measures savings as
   an A/B experiment against your own live traffic. Confidence intervals, auditable per-request
   assignment, quality drift auto-rollback against the same control arm. No one else sells this.
3. **Incentives are aligned.** No seat license, no platform fee. 25% of verified savings, with
   the fee and net-to-you shown on the same page.

**Positioning against each alternative (know these cold):**

| Alternative | Their story | Your counter |
|---|---|---|
| Do nothing / wait for price drops | "Prices drop 10x/year" | Margin is a ratio; usage grows faster; your competitors get the same cuts. Free audit costs you nothing to check. |
| DIY (LiteLLM + own caching) | "It's open source, we'll build it" | You'll spend eng-months building the easy 20% and never build the measurement. Who on your team is going to run a randomized holdback and defend the number to your board? Your engineers should ship product. |
| Portkey / Helicone / gateways | "Gateway with caching built in" | They sell you tools and you do the work and own the risk. Varsten sells the outcome and proves it. Also: gain-share vs their subscription means your CFO does no ROI math. |
| Observability (Datadog, Vantage, Langfuse) | "See where money goes" | Seeing is not saving. Varsten includes the seeing (observe mode, free) and then acts on it. |

**Claims discipline.** Never say "guaranteed 40-70%." Say: "we typically find 20-40% in the
audit; whatever we actually save is measured, and you only pay on what's verified." Underclaiming
plus a rigorous number is the brand. One inflated claim kills the only differentiator you have.

## 5. The offer ladder (this is the funnel)

Each rung asks for a little more trust and gives a concrete deliverable. Never skip a rung in
outbound; skipping is fine when a prospect pulls you forward.

**Rung 0: the 48-hour Spend Teardown (the outbound hook).**
- Ask: "export your OpenAI/Anthropic usage CSV (or screenshot the usage page) and 15 minutes on
  what your routes do." No code, no integration, no meeting required to start.
- Deliverable: a 2-3 page teardown, their numbers, lever by lever: "your support-agent route
  re-answers ~N% near-duplicate queries: cache saves ~$X/mo. Your extraction jobs are sync but
  not latency-sensitive: batch API saves a flat 50% on $Y. Estimated total: $Z/mo, which we'd
  verify, not estimate, in a pilot." Every number labeled estimated. The teardown models the
  honesty of the product.
- Cost to you: 1-2 hours each once templated. Build the template after the first two manual ones.
- Why this beats "free consulting" positioning: it is consulting, but productized, bounded, and
  always ending in the same CTA. You are not selling hours and must not drift into it.

**Rung 1: observe-only connect (free plan, already built).**
- SDK or proxy in metadata mode. No behavior changes possible on the free tier (enforced at the
  backend, which is a security talking point). Now the teardown numbers become their live
  dashboard, and unpriced/untagged traffic gets surfaced (data-quality page).
- Exit criteria: 2+ weeks of data, a credible waste number on a named route.

**Rung 2: the pilot (30-60 days, safe levers first).**
- Scope: 1-3 named routes, all below the capacity ceiling. Levers: exact cache, batching, token
  trim only. These are objective, direct-measured, autonomous-cleared per LEVER_READINESS. No
  model swaps in the first two weeks of any pilot, period. Routing/downshift come after the first
  clean savings report, through the eval gate, in approve mode, with the customer clicking
  approve.
- Terms for the first 3 pilots (design partners): fee waived or 10% instead of 25% for 6 months,
  in exchange for (a) a named, quotable case study with real numbers, (b) a weekly 30-minute
  feedback call, (c) permission to name them as a customer. Get this in writing.
- Safety story, stated proactively: fail-open on every lever, kill switch they control, per-route
  latency SLO treated as a quality gate, canary ramp, circuit breakers. Demo the kill switch on
  the onboarding call. Show FAILURE_MODES.md if they're technical enough to want it.
- Success criteria agreed in writing on day 0: e.g. "≥15% verified net savings on scoped routes,
  zero quality regressions per the drift monitor, added p99 within SLO." Defined success is what
  converts a pilot into a contract instead of a stall.

**Rung 3: Performance plan.** 25% of verified savings, monthly, Stripe. The Proof page (realized
savings, fee, net-to-you) is the renewal document. Expand from scoped routes to full traffic,
then introduce approve-mode routing/downshift recommendations from the sweep.

## 6. Product and packaging adjustments before selling hard

The product mostly matches demand. The adjustments are packaging and sequencing, not features.
Do not add engine surface area for GTM reasons.

1. **Productize the teardown.** A repeatable internal recipe: CSV in, teardown doc out, with the
   per-lever estimation heuristics written down. First two done by hand, then templated.
2. **Security one-pager, honest version.** No SOC 2 yet, so lead with architecture: metadata-only
   ledger with a content denylist, zero-retention hot path, cache as the documented TTL'd
   exception, fail-open design, tenant isolation, key vaulting. Plus a plain DPA and a data-flow
   diagram. This packet answers 90% of what a seed-stage CTO asks. Start SOC 2 Type I only when
   a deal actually blocks on it.
3. **Pilot capacity rule.** Until the load gate closes: no pilot route above ~50 RPS sustained,
   and say so internally, not apologetically to the customer ("we scope pilots to named routes"
   is normal). Closing the capacity gate stays the top engineering priority in parallel.
4. **A one-page "How we measure savings" methodology doc**, public. Holdback design, why
   point estimates are suspicious, what verified vs estimated means, what the customer can audit.
   This is sales collateral, content marketing, and objection handling in one artifact. Highest
   leverage single document you can write.
5. **Keep consulting out of the product.** The teardown is the only consulting-shaped object.
   If a prospect wants ongoing hands-on optimization help, that is the product's job; do not
   take retainers that turn you into an agency with a side project.

## 7. Outreach: channels ranked by expected ROI

Ranked for a solo, no-brand founder. Budget roughly: 40% ch.1, 30% ch.2, 20% ch.3, 10% ch.4.

### Channel 1: Warm and semi-warm network (highest hit rate)
- **BYU network.** The Provo/SLC startup scene is dense (Qualtrics, Podium, Lucid, Route, Divvy
  alumni networks) and unusually founder-generous. Email every founder, professor, and Sandbox/
  Crocker-adjacent contact you have: "I'm looking for 3 AI product companies spending $5k+/mo on
  LLMs for a free spend teardown. Who should I talk to?" Ask for intros, not customers.
- **Investors and accelerator platform teams.** One VC platform person forwarding "free AI spend
  teardown, gain-share pricing" to a portfolio is 30 warm leads in one email. Target seed funds
  with AI-heavy portfolios; the pitch to them is "I make your portfolio's margins better for free."
- **NYC on arrival.** AI Tinkerers NYC, NY Tech Meetup, founder dinners, Latent Space and MLOps
  community events. Give a 5-minute talk titled "How to actually verify LLM savings (and why
  every savings number you've seen is made up)." The talk is the methodology doc, spoken.

### Channel 2: Targeted cold outbound with the teardown hook
Small volume, deep personalization. 15-25 sends/week, hand-written. Not 500 automated.

**Sourcing the list (build 150 names):**
- YC directory: last 4 batches, filter AI, keep companies matching section 3 segments.
- Product Hunt AI launches from the past 12 months that show real traction.
- Job boards: companies hiring for roles whose posts mention "LLM cost," "inference
  optimization," "prompt engineering at scale." A job post about cost = budget-level pain.
- Founders posting about API bills on X/Twitter and HN ("Ask HN" threads on LLM costs). Reply
  publicly with something useful, then DM.
- Pricing pages with usage caps or "AI credits": signals per-unit COGS anxiety.

**The email (template, tune per segment):**

> Subject: your [route/feature] token spend
>
> [Name], I build Varsten, an engine that cuts AI spend and proves the number with a live
> randomized holdback (an actual A/B test, not a modeled estimate).
>
> Guess based on [specific observation about their product: "Fin-style support agents usually
> re-answer 20-30% near-duplicate queries"]: you're leaving $X-$Y/mo on the table across cache,
> batch pricing, and prompt trim.
>
> I'll do a free 48-hour teardown of your actual usage export, numbers per fix, no integration,
> no call required. If I can't find at least 15%, I'll say so in writing. Worth a CSV?
>
> Pricing if you ever go further: 25% of verified savings, $0 if we save you $0.

Rules: one specific observation about *their* product per email (this is the whole game), one
CTA, no deck attached, 2 follow-ups max (day 4: one new specific observation; day 10: "closing
the loop, here's the methodology doc if useful later").

### Channel 3: Content that compounds (credibility engine)
You cannot out-spend anyone; you can out-honest them. Everything publishable from the build:
- "How we measure LLM savings with a randomized holdback (and why your vendor's savings number
  is fiction)." The methodology doc as a post. Aim it at HN.
- Anonymized teardown write-ups: "I audited an AI support product's $18k/mo spend. Here's the
  $6k we found." Each audit you do becomes content (with permission, anonymized).
- Honest negative results: "Why we keep semantic (vector) caching off by default." Engineers
  share vendor posts that admit tradeoffs; it is rare enough to be remarkable.
- Cadence: 2/month. Cross-post to X and LinkedIn. Every post ends with the teardown CTA.

### Channel 4: Referral loops and partners
- Every delivered teardown, ask: "which two founders you know are getting killed by their AI
  bill?" The teardown is free; the ask is normal and it works.
- Dev shops and fractional CTOs building AI products for clients: they get to hand their clients
  "we cut your costs too"; offer them a referral cut (10% of year-1 fees) or just reciprocity.
- Post-case-study: offer the pilot customer's investors the portfolio email from channel 1.

### What NOT to do
- Paid ads, SEO plays, cold LinkedIn automation, outsourced SDRs. Wrong stage, wrong economics,
  and mass outbound with a security-sensitive inline product poisons the well.
- Conferences/sponsorships. Attend free NYC events; sponsor nothing.
- Building "lead magnet" product features. The observe tier already is one.

## 8. Funnel math and metrics

Assumed conversion at hand-written quality (update with real data monthly):

| Stage | Rate | From 150 touches |
|---|---|---|
| Touch → teardown accepted | ~10-15% | 15-20 teardowns |
| Teardown → observe connect | ~40% | 6-8 connected |
| Observe → pilot | ~50% | 3-4 pilots |
| Pilot → paying (criteria met) | ~50-70% | 2-3 paying |

Weekly scorecard (keep it in this file or a sheet, review every Friday):
- personalized touches sent, teardowns delivered, orgs in observe mode, active pilots,
  verified savings $/mo across all customers, MRR (25% share), case studies published.

**The single 90-day goal: one named case study with a verified savings number and a quote.**
Two paying customers is the target; the case study is the requirement. It converts every later
conversation from "trust me" to "here's what happened at [Company]."

## 9. 90-day execution plan

**Weeks 1-2: package.**
- Finish backup and restore proof; keep the remaining production-readiness work moving in parallel.
- Write: methodology one-pager (public), security one-pager + DPA + data-flow diagram, teardown
  template v1, design-partner terms one-pager, pilot success-criteria template.
- Build the 150-name prospect list with the specific-observation column filled in.
- Send the network ask (channel 1) to 20 people. This starts before the collateral is perfect.

**Weeks 3-6: outbound wave 1.**
- 15-25 cold touches/week. Deliver every teardown inside 48 hours, no exceptions; speed is the
  product demo.
- Publish the methodology post; submit to HN on a Tuesday morning.
- Target: 8+ teardowns delivered, 3+ observe connects.

**Weeks 5-10: pilots.**
- Convert the 2-3 best observe accounts into design-partner pilots (safe levers only, terms
  signed, success criteria written).
- Week 1 of each pilot: onboarding call, kill-switch demo, canary ramp on one route. Weekly
  savings report every Friday, even when the number is small. The report cadence is the trust.
- Keep outbound at reduced volume (10/week); the funnel dies if it empties.

**Weeks 10-13: proof.**
- First pilot hits criteria → convert to Performance plan, publish the case study, ask for the
  investor-network intro and 2 referrals.
- Post the case study version of the teardown content. Restart full outbound volume with the
  case study in the email.
- Reassess this document against actuals and rewrite the funnel numbers.

## 10. Objection handling (the six you will hear)

1. **"I'm not putting a proxy in my hot path."** Never asked to on day one. Teardown needs a CSV;
   observe mode is metadata-only and can't change behavior (enforced server-side). When you do go
   inline: fail-open everywhere, your kill switch, canary ramp, per-route latency SLO. Worst case
   is "savings stop, traffic doesn't."
2. **"We'll build it ourselves with LiteLLM."** Sure, the gateway is the easy part. The eval/
   replay harness, the holdback measurement, and the drift rollback are eng-quarters, and without
   them you're guessing whether routing hurt quality. Your margin problem is now; your engineers
   have a roadmap.
3. **"How do I know the savings number is real?"** That's the product. Randomized concurrent
   holdback, confidence intervals, per-request assignment you can audit, and anything app-side
   you ship lands on both arms and cancels. Here's the methodology doc.
4. **"Model prices are falling anyway."** Both arms get the price cut; we only claim our delta.
   And your margin is a ratio: usage grows faster than prices fall, and your competitors get the
   same cuts.
5. **"Will it degrade quality?"** Quality is measured, not promised: replay evals on your own
   traffic before any change, live drift monitoring against the holdback, auto-rollback. Anything
   subjective stays approve-mode with you clicking the button. First pilots don't touch model
   choice at all.
6. **"Do my prompts leave my infrastructure?"** Today: content transits the proxy in memory and
   is never persisted; the ledger is metadata-only; the cache is the one documented TTL'd
   exception. In-VPC deployment is on the roadmap for when that answer must be "content never
   leaves your boundary." If that's a blocker today, we're honest that we're not the fit yet.

## 11. Risks and honest caveats

- **Gain-share disputes.** The verified/estimated vocabulary and the holdback exist to prevent
  this, but write the definition of "verified savings" into the pilot terms verbatim so the
  invoice never surprises anyone. Revenue will be lumpy and small at first; that is fine at this
  stage, but consider a small monthly minimum once past design partners.
- **A pilot failure in public is fatal at n=1.** This is why the first pilots run safe levers
  only, scoped routes only, under the capacity ceiling, with the weekly report cadence. Do not
  let an eager design partner talk you into bandit routing in week 2.
- **The teardown can get commoditized too.** Fine. The teardown is a door, not the moat. The
  moat is the measurement + eval harness, and it compounds with every route observed.
- **Solo-founder bus factor will come up.** Answer honestly: fail-open design means the worst
  case for them is losing savings, not losing uptime, and their provider keys stay usable
  without Varsten. Don't oversell continuity you can't promise.
