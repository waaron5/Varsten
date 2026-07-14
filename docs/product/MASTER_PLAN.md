# Varsten Master Plan

Written 2026-07-12, from a full-codebase assessment. This is the shipping plan: current state, target identity, architecture, engine roadmap, compatibility, safety, first customer, enterprise readiness, competition, and execution order.

---

## 1. Current state, honestly

**The code is ahead of the company.** The engine is real and unusually complete for a solo build:

- Six levers execute inline with fail-open on every lookup. Three provider dialects (OpenAI GA, Anthropic and Gemini beta). Holdback A/B on always-valid sequential inference, drift auto-rollback, eval/replay harness, planner authorization, governance objects, canary ramp, circuit breakers, budget caps.
- 783 tests passing, 80.7% coverage, the adversarial validation plan (V0 to V8) complete.
- Self-serve billing implemented end to end (trial, entitlements, Stripe checkout, expiry sweep).
- A fail-open TypeScript SDK (core plus OpenAI/Anthropic/Gemini wrappers) with a frozen origin-header contract that solves the base-URL fail-open problem correctly.

**What is at zero:**

- **Deployment.** The Terraform under `infra/aws/terraform/` has never been applied. No staging, no production, no request has ever been served off the development laptop. "Production-grade" is currently a claim about code, not about operations.
- **Customers and traffic.** Zero design partners, zero real traffic, zero revenue. Every quality and savings mechanism has been proven against mocks and replays, never against a customer's live distribution.
- **Secrets hygiene.** Live values sit in `.env` files in the repo (per CLAUDE.md). Must be rotated and moved before anything touches a remote or a customer.

**Real weaknesses in the built thing:**

- **Hot-path latency.** At 100 RPS locally, passthrough added p99 is +397ms against a +9ms target; at 200 RPS the proxy drops over half the scheduled sends. The cache-hit path beat the direct baseline (-5.5ms), so the machinery can be fast; passthrough, the path that must be near-zero-added, is not. The cause is per-request work against the database (auth resolve, entitlements, planning reads, ledger contention). Opt-in snapshot caches were added but are not the default path.
- **The benchmark itself is suspect.** Load generator, eight backend workers, and the mock provider all share one Mac. That conflates machine contention with product capacity. The numbers are directional signal, not gate-grade evidence. See §10 for the replacement gate.
- **Hot-path concentration.** `app/proxy/router.py` is ~3,000 lines. Both the capacity fix and the future data-plane split require untangling per-request dependencies out of it.
- **Provider maturity is uneven.** Only OpenAI is GA. Anthropic and Gemini are founder-supervised beta. Cross-provider routing is the least-travelled code.
- **No OpenAI Responses API support.** The OpenAI dialect is chat completions only. OpenAI is steering new development (and its Agents SDK) toward `/v1/responses`. This is a looming compatibility cliff for exactly the AI-native ICP Varsten targets.
- **Gain-share billing is manual.** Stripe metering for gain-share is explicitly out of scope so far. Fine for customer #1 (invoice by hand), but it is a gap between the pricing page and the billing system.
- **Solo operator, inline product.** Being in a customer's request path with one person on call is the single largest business risk. The SDK's client-side fallback is the correct structural mitigation and should be treated as the default install, not an option.

Net: the engine deserves more confidence than the docs give it, and the operation deserves less. The binding constraint is not features. It is that Varsten has never run anywhere real.

---

## 2. What Varsten should be

One sentence: **Varsten is the infrastructure-neutral AI savings engine: it attaches to whatever stack a customer already runs, cuts spend with quality-gated levers, and produces a finance-grade verified savings number that no gateway, observability tool, or provider can produce.**

Three claims define the product. Everything else is subordinate:

1. **Attach, don't replace.** Never ask a customer to swap a gateway, a provider, or a framework. Varsten interposes (SDK, base URL, sidecar) or ingests (metadata mode). The moment Varsten demands a migration, it is competing with LiteLLM and Vercel on their turf and losing.
2. **Safe by construction.** Fail open at every layer including the client. The honest pitch: "worst case, we stop saving; we never stop your traffic."
3. **Proof, not estimates.** The concurrent randomized holdback is the only counterfactual a CFO cannot argue with, and it is what makes gain-share pricing possible at all.

What Varsten is **not**: a gateway (commodity, already free), an observability dashboard (commodity, already crowded), or a model-routing point solution (a feature, not a company).

**The moat, in order of durability:**

1. **The proof machinery plus the business model it enables.** Sequential-inference holdbacks, strict verified-vs-estimated vocabulary, and 25%-of-verified-savings pricing form a loop competitors structurally cannot copy: Vercel, LiteLLM hosts, and providers all monetize traffic volume, so charging on savings is against their own book.
2. **Cross-customer priors.** Content-free task classification plus persisted outcome priors means every customer's evidence about which downshifts and compressions hold quality accrues to the engine. This compounds from customer #1, but only if priors are keyed by task class and route shape, not by tenant. Verify the schema generalizes cross-tenant now, while it is cheap to change.
3. **The eval/replay harness.** Routing is a config change. Knowing a change is safe on traffic you have never seen is the IP.

---

## 3. Target architecture and packaging

**Verdict: hybrid, staged. No single packaging wins, and the sequencing matters more than the taxonomy.**

| Tier | Packaging | When | Role |
|---|---|---|---|
| Wedge | **Fail-open SDK wrapper** pointing at hosted Varsten | Now | The first-customer install. True client-side fail-open (direct-to-provider fallback), 15-minute integration, zero infra change. |
| Universal | **Base-URL proxy** | Now | Anything that can set a base URL: LiteLLM upstreams, frameworks, agents, curl. Honest caveat: not fail-open if Varsten is unreachable. |
| On-ramp | **Metadata/observe mode** (ingestion API) | Now | Works with any stack including Bedrock, Foundry, and every gateway. Zero risk, powers analysis and recommendations, top of funnel. |
| Enterprise | **In-VPC sidecar data plane** + hosted control plane | Post-revenue | Content never leaves the boundary; only hashes, counts, and scores flow out. Same codebase. |

**The architectural imperative that unifies everything: the hot path must require zero synchronous database round trips.** Policy snapshots, entitlements, API-key resolution, and circuit state live in memory (Redis-refreshed); every write is async. The opt-in snapshot caches built during capacity remediation become the only path, and the synchronous variants get deleted. This one piece of work simultaneously (a) closes the latency gate, (b) is the prerequisite for the sidecar (a sidecar cannot call home per request), and (c) reduces blast radius when the control plane degrades. It is not a performance patch; it is the data-plane/control-plane split CLAUDE.md already names as load-bearing, executed inside the current monolith.

**Do not build:** gateway feature parity (provider failover matrices, unified-API ergonomics), a Foundry-native app, a Kubernetes operator, or any second deployment topology before the first one has a paying customer on it.

---

## 4. Engine roadmap: levers, quality, learning, observability, moat

The six levers are the right six. The gaps are in what comes next and in operator-grade visibility.

**Lever roadmap (strictly post-pilot; new engine surface competes with shipping, per CLAUDE.md):**

1. **Reasoning-effort / thinking-budget tuning.** Per-route caps on `reasoning_effort` (OpenAI o-series) and thinking budgets (Claude). Reasoning tokens are the fastest-growing cost surface in 2025-26 and nobody optimizes them systematically. Mechanically cheap: it is a request-parameter policy that rides the existing routing/eval/holdback machinery. This should be lever seven.
2. **Output discipline.** `max_tokens` tuning, verbosity control, structured-output enforcement. Output tokens price at 4 to 8x input; a lever that detects and caps overlong outputs is missing from the current set.
3. **Promote prompt-cache prefix restructure** from detect-only to guided apply. Provider-side prompt caching is frequently the single largest real-world saving, it is provider-blessed, and quality risk is zero when the prefix is byte-identical.
4. **Batch auto-detection.** Classify latency-tolerant traffic and propose batch migration (the batch mirror exists; the detection-to-proposal loop does not).
5. **Semantic vector cache default-on** only after in-process embeddings remove the miss-path round trip and per-route thresholds are tuned. Current default-off posture is correct.

**Quality controls:** keep the two inviolable rules as written: judge-scored routes never auto-apply, and prompt compression never auto-applies regardless of evidence. Add per-route quality budgets to reporting so a customer sees "quality spend" the way they see holdback cost.

**Learning loop:** persist savings variance so the bandit graduates from mean-exploit to real Thompson sampling (already a disclosed backlog item). Then the moat work: cross-tenant task-class priors, so customer #2 starts warmer than customer #1 did. That is the compounding asset; treat its schema as a first-class design review, not a byproduct.

**Observability (pre-pilot requirement, not post):** the engine has evidence trails but not operator eyes. Before customer #1: dashboards and alerts for added-latency SLO per path, error rates split by origin (`varsten` vs `provider`), fail-open event stream, per-lever savings counters, and holdback health. Sentry plus CloudWatch logs exist; the dashboards and paging thresholds do not.

---

## 5. Compatibility strategy

- **Providers.** OpenAI stays the GA spearhead. **Add `/v1/responses` support next** on the OpenAI dialect; the ICP's new builds are moving there. Harden **Anthropic to GA second** (AI-native startups skew heavily Claude), Gemini third. Cross-provider routing stays founder-approved until traffic proves it.
- **LiteLLM:** do not compete; interpose and ingest. Ship two documented recipes: Varsten as a LiteLLM upstream (base URL), and a log-ingestion adapter for observe mode. The pitch to LiteLLM shops is "keep LiteLLM; add the savings engine behind it."
- **Vercel AI Gateway:** observe-mode ingestion of its cost data; interpose only where a customer wants it.
- **AWS Bedrock:** metadata mode now (invocation logs / CUR ingestion). Inline later only via the in-VPC sidecar, which is the only credible inline story inside AWS anyway.
- **Foundry / Palantir estates:** observe mode only. Never build platform-native apps pre-revenue.
- Publish the compatibility matrix as a living public doc, with the same honesty as `PROVIDER_COMPATIBILITY.md`. Stated boundaries are a sales asset against competitors who overclaim.

---

## 6. Production-safety strategy

1. **Deploy staging this week, production next.** The Terraform is written; apply it. Nothing else on this list is real until this happens.
2. **Single instance, scale up not out**, until the live Redis smoke passes against staging Redis, exactly as the runbook already states. One scheduler instance is a hard rule.
3. **SLOs, stated:** added p50 ≤ 5ms and added p99 ≤ 25ms on passthrough at pilot traffic; an availability target with the fail-open definition attached (Varsten down does not mean customer down when the SDK path is used).
4. **Drills with the customer, not just internally:** run the kill-switch and project-bypass drill live during onboarding week so the customer has pulled the lever themselves once.
5. **Status page.** One was removed from the marketing site; a paying inline customer requires one, even a manually updated one, plus external uptime monitoring (a $10/month synthetic check, not self-hosted).
6. **Solo-operator honesty:** written support expectations (business hours plus best-effort), aggressive auto-rollback defaults, and the SDK fallback positioned as the structural answer to "what happens while you sleep."
7. **Secrets:** rotate everything currently in `.env`, move to Secrets Manager, add a secret scanner to CI. Before any pilot, no exceptions.
8. **Backups proven, not configured:** one full restore test of RDS PITR on staging, logged in the runbook.

---

## 7. First-customer onboarding plan

**Profile:** AI-native startup where tokens are COGS. OpenAI-dominant chat-completions traffic, $10k to $100k/month spend, a reachable technical founder or platform lead, tolerant of a design-partner relationship. Source from the NYC move and personal network; 10 to 20 targeted conversations, not a launch.

**Offer:** 90-day founding-partner terms. 25% of verified savings (capped as already implemented), white-glove onboarding, weekly savings report, co-built golden sets, case-study rights. No payment until the first verified savings report exists.

**Sequence (four weeks):**

- **Week 0 (before their traffic):** staging benchmark green, production deployed, restore and kill-switch drills done, monitoring paging you.
- **Week 1, observe:** SDK or ingestion install, zero behavior change. Deliverable: a baseline spend report with pricing-trust coverage. This alone must be impressive; it is the trust foundation.
- **Week 2, arithmetic levers:** exact cache and token trim on one or two routes, auto mode. Verify ledger accuracy, added latency, and fail-open in their environment.
- **Week 3, judgment levers:** routing/downshift candidates through the eval gate; approve-mode applies with the customer clicking approve; holdback live.
- **Week 4, proof:** first verified savings report with confidence intervals, holdback cost as a line item, and the fee math. Decide expansion together.

**Success gate:** verified savings at least 3 to 5x the Varsten fee, zero customer-visible incidents, and the customer willing to say so on the record.

---

## 8. Enterprise-readiness checklist

Two tiers. Do not let tier-two items block tier one.

**Pilot-ready (required now):** secrets out of the repo and rotated; staging plus production live; tested database restore; incident-response doc (exists); DPA template; data-flow diagram; security page that discloses the semantic-cache exception plainly; status page; external uptime monitoring; the `ENGINE_RELIABILITY_BOUNDARIES.md` claims list enforced against all marketing copy.

**Enterprise-ready (start clocks early, buy when a deal demands):** SOC 2 Type II (start evidence collection with a compliance platform at first paid customer; the observation window is months, so starting late means losing deals later); third-party pen test; SSO/SAML via Auth0 add-on; audit-log export; RBAC beyond owner/member; customer-managed encryption keys for the cache; the in-VPC sidecar; subprocessor list; SLA with credits; gain-share invoice automation.

---

## 9. Competitive strategy

Positioning sentence: **"Gateways route your traffic. Observability shows your bill. Varsten cuts it and proves the cut."**

- **LiteLLM:** free OSS gateway with cost tracking, budgets, routing; enormous adoption. It shows spend and moves traffic; it does not cut spend safely or prove counterfactual savings. Strategy: full compatibility (upstream recipe, log ingestion) and sell into LiteLLM shops rather than against them.
- **Vercel AI Gateway:** unified API, failover, cost visibility, huge distribution. Same functional counter, plus a structural one: Vercel's margin scales with traffic through the gateway, so savings-aligned pricing works against their book. Gain-share is the wedge they will not match.
- **Palantir (Evolve / AIP estates):** sold top-down into existing accounts with long deployments. Do not fight inside Foundry accounts; win everywhere install velocity and neutrality matter. A one-day, stack-neutral install is the counter.
- **Model-routing startups (Martian, NotDiamond, Unify, OpenRouter):** routing is one of Varsten's seven levers, and none of them prove savings against a live randomized baseline. Subsume, don't chase.
- **Observability tools (Helicone, Langfuse) and gateways with caching (Portkey):** they inform; Varsten acts and proves. Portkey is the closest functional overlap; measurement rigor plus gain-share is the separation.
- **The real competitor is "do nothing":** provider price cuts, provider prompt caching, and batch discounts make passivity cheaper every quarter. Varsten's answer is already built into the design: provider discounts are levers Varsten captures for the customer (batch, prefix restructure), and the concurrent holdback automatically nets provider price cuts out of savings claims. When optimization margins compress, the proof layer is what survives; that is why measurement rigor, not the proxy, is the durable business.

---

## 10. Execution plan

**The decision to make now: replace the local 200 RPS gate with a staging gate at a realistic pilot envelope.**

Reasoning: a $50k/month OpenAI customer at roughly $0.01 per request averages about 2 RPS. 200 RPS sustained is on the order of 17 million requests a day, far beyond any plausible first- or fifth-customer load, and the local benchmark shares one machine between load generator, eight workers, and the mock provider. The gate is measuring laptop contention against a threshold no pilot needs. Replacement gate: **on staging hardware, sustain 50 RPS with added p99 ≤ 25ms on passthrough and zero drops, plus a five-minute 100 RPS soak without error-rate degradation.** Keep the zero-DB-hot-path work regardless, because it is also the sidecar prerequisite, but stop tuning for a local number.

**Days 0 to 14, make it real:**
1. Rotate every secret in `.env`; move to Secrets Manager; secret scanner in CI.
2. `terraform apply` staging; migrations; smoke; live Redis smoke.
3. Run the load benchmark against staging; fix what staging (not the laptop) reveals; make the snapshot caches the default path.
4. Deploy production; external uptime monitoring; restore drill; kill-switch drill.

**Days 15 to 45, first traffic:**
5. Outbound to 10 to 20 design-partner candidates; sign one or two.
6. Run the §7 onboarding sequence end to end.
7. Finish SDK streaming; publish the packages.
8. Weekly savings report template; manual gain-share invoice.

**Days 46 to 90, prove and compound:**
9. First verified-savings case study with the methodology appendix.
10. `/v1/responses` support; Anthropic to GA if the partner's mix demands it.
11. Start SOC 2 evidence collection.
12. Design (not build) the reasoning-effort lever; build only once the pilot is stable.
13. Lock marketing copy against `ENGINE_RELIABILITY_BOUNDARIES.md`.

**Deferred deliberately:** Foundry/Bedrock inline, semantic vector cache default-on, Kubernetes operator, additional providers beyond the three, enterprise RBAC, gain-share metering automation, and any new lever before pilot traffic is stable.

**One sentence:** stop proving the engine to yourself on a laptop; prove it on a staging deployment and one design partner's real traffic, because every remaining risk (capacity, provider maturity, savings credibility, the moat) only resolves against reality.
