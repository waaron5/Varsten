# Varsten Cost Engine Technical Audit

Date: 2026-06-30

> **Superseded.** This audit predates the roadmap A–F completion and adversarial validation work completed on 2026-07-04/05. Its central verdict — "does not yet learn in a meaningful closed loop," "most optimization decisions are policy- and heuristic-driven" — no longer holds: the planner is the live authorization layer, outcome evidence promotes into recommendations, bandit routing and prompt compression are real executing levers, and `ChangeRequest` governance exists natively. Kept as the historical point-in-time record it was written to be, not current status. For current status read `docs/ENGINE_FINAL_PROOF_STATUS.md`.

Reviewer stance: hostile technical diligence. Comments, TODOs, mocked product screenshots, and marketing copy are not treated as proof.

## Executive Verdict

Varsten is not a fake wrapper, but it is not yet a production-grade quality-preserving AI cost optimizer.

What exists today is a real inline proxy with exact cache, optional vector semantic cache, static policy routing/downshift, token trimming, an off-path OpenAI Batch API workflow, usage/cost ledgers, request decision evidence, eval replay for routing/downshift, live holdback assignment, and objective drift rollback.

What does not exist today is the hard part: a unified optimization planner that understands task risk, customer intent, tool requirements, freshness, personalization, business ontology, agent loops, output acceptance criteria, and per-task quality outcomes. Most optimization decisions are policy- and heuristic-driven. The product can often prove "we spent less." It usually cannot prove "we preserved quality" except for the narrow subset of routing/downshift policies that went through replay evals and/or holdback with objective health metrics.

The core question:

> Does Varsten actually know how to reduce LLM cost without degrading output quality, or is it merely applying simplistic rules that could break customer workflows?

Answer: Varsten has the scaffolding to become a credible cost-control system, but today the engine mostly applies simplistic and partially gated rules. Some levers are real but narrow. Some claims are overstated. Semantic cache and token trim are the most dangerous if marketed broadly. Batching is real only for offline OpenAI Batch jobs, not online request-path optimization. Model downshift has the best path to credibility because it has an eval gate and holdback, but the classifier/risk/policy/eval substrate is too shallow to justify enterprise-grade "best model for every request" claims.

## Evidence Map

Primary code paths inspected:

- Request lifecycle: `backend/app/proxy/router.py`
- Cache: `backend/app/proxy/cache.py`, `backend/app/proxy/embedding.py`, `backend/app/models/proxy_cache.py`, `backend/alembic/versions/d4e5f6a7b8c9_proxy_cache_embedding.py`
- Routing/downshift: `backend/app/proxy/routing.py`, `backend/app/proxy/predicate.py`, `backend/app/proxy/routing_eligibility.py`
- Token trim: `backend/app/proxy/trim.py`
- Batch: `backend/app/proxy/batch.py`, `backend/app/proxy/openai_batch.py`, `backend/app/api/v1/batches.py`, `backend/app/models/batch.py`
- Ledger/evidence/quality: `backend/app/proxy/ledger.py`, `backend/app/proxy/evidence.py`, `backend/app/models/evidence.py`, `backend/app/proxy/quality.py`, `backend/app/proxy/drift.py`
- Eval: `backend/app/eval/gate.py`, `backend/app/eval/capture.py`, `backend/app/eval/runner.py`, `backend/app/models/eval.py`
- Recommendations/pricing: `backend/app/recommendations.py`, `backend/app/pricing/*`, `backend/app/savings_measurement.py`, `backend/app/savings.py`
- Product/API surfaces: `backend/app/api/v1/product_sections.py`, `backend/app/api/v1/metrics.py`
- Public claims: `marketing/app/page.tsx`, `marketing/app/content-page.tsx`, `marketing/app/security/page.tsx`, `marketing/app/privacy/page.tsx`
- Internal readiness doc: `docs/LEVER_READINESS.md`

External competitive sources used:

- LiteLLM proxy, routing, caching, budgets: https://docs.litellm.ai/docs/proxy/quick_start, https://docs.litellm.ai/docs/proxy/reliability, https://docs.litellm.ai/docs/proxy/caching
- Cloudflare AI Gateway: https://developers.cloudflare.com/ai-gateway/
- Portkey AI Gateway and semantic cache: https://portkey.ai/docs/product/ai-gateway, https://portkey.ai/docs/product/ai-gateway/cache-simple-and-semantic
- Helicone Gateway, caching, sessions/evals: https://docs.helicone.ai/gateway/overview, https://docs.helicone.ai/features/advanced-usage/caching, https://docs.helicone.ai/features/sessions
- TrueFoundry: https://www.truefoundry.com/
- Maxim/Bifrost: https://www.getmaxim.ai/bifrost
- LangSmith eval/observability: https://docs.langchain.com/langsmith/observability, https://docs.langchain.com/langsmith/evaluation-concepts
- Braintrust eval workflow: https://www.braintrust.dev/docs/evaluate
- vLLM semantic router papers: https://arxiv.org/abs/2603.21354, https://arxiv.org/abs/2603.04444
- RouteLLM and related learned routing papers: https://arxiv.org/abs/2406.18665, https://arxiv.org/abs/2605.18796

I did not find a reliable public official Palantir AIP Evolve technical document during browsing. The AIP Evolve comparison below uses the user's described capability model and public AIP positioning only as contextual inference, not as independently verified product documentation.

## Full Request Path

Actual lifecycle for OpenAI-compatible chat completions:

1. Authenticate project/API key.
2. Parse body into an OpenAI chat-completion request.
3. Parse optional request metadata from `X-Varsten-Metadata` and `X-Varsten-*` headers.
4. Determine bypass/Base/performance entitlement.
5. Compute exact cache key from selected request fields.
6. Look up exact cache entry.
7. If exact miss and semantic cache is enabled, embed prompt text and run pgvector cosine nearest-neighbor search.
8. If cache hit, return cached response immediately and meter avoided cost.
9. If no cache hit, enforce budget.
10. Resolve model routing/downshift policy.
11. If routing policy applies, assign holdback arm and possibly replace provider/model.
12. If no routing policy applies, resolve token-trim policy, assign holdback arm, and possibly trim request.
13. Check cross-provider dialect eligibility for routed requests.
14. Call provider, streaming or non-streaming.
15. Capture usage, request decision evidence, cache store, optional eval replay sample, and objective quality flag.

Actual optimization order:

`cache lookup -> budget -> routing/downshift -> token trim -> provider execution -> ledger/evidence/cache-store/eval-capture`

Important consequences:

- Cache fires before routing and token trimming. A cache hit prevents every later lever.
- Routing/downshift and token trim are mutually exclusive in the hot path. Token trim only runs when no routing policy applies.
- Batching is not in this lifecycle. It is a separate customer-driven OpenAI Batch API workflow.
- There is no formal planner that reasons across levers.

### Request Path Answers

| Question | Actual answer |
| --- | --- |
| What information does Varsten extract? | Provider/model/body messages, selected model params, token usage from response, latency, optional business metadata headers, cache status, routing/trim arm, usage cost. |
| What metadata does it require? | Almost none beyond API key/project. Feature, workflow, task type, risk, quality threshold, customer/user/team are optional and fail-open. |
| What does it infer? | Very little. It does not infer task type, risk, complexity, freshness, personalization, or required correctness. Smart-routing predicate infers only prompt char length/tool/schema/max-output constraints. |
| What does it store? | UsageEvent, RequestDecisionEvent, ProxyCacheEntry with response payload, optional EvalSample, BatchJob/BatchItem, feedback events, recommendations, policies, prices. |
| Decision points before provider execution | Cache hit, entitlement/observe/bypass, budget, routing/downshift policy, smart predicate, holdback arm, cross-provider eligibility, token-trim policy/arm, circuit breaker. |
| Optimization levers that can fire | Exact cache, optional vector semantic cache, model_downshift, smart_routing, token_trim. Batch is off-path. |
| Order | Cache, then routing/downshift, then token trim. Batch separate. |
| Conflict prevention | Routing and trim are made mutually exclusive. Cross-provider routing has dialect safety checks. No general policy conflict engine. |
| Unsafe optimization prevention | Eval gate for routing/downshift recommendations, holdback, drift rollback, bypass/observe flags, limited dialect checks. No task-risk safety gate for cache/trim. |
| Money saved evidence | UsageEvent costs, `saved_usd`, RequestDecisionEvent counterfactual fields, price version IDs, batch ledger. |
| Quality maintained evidence | Routing/downshift eval runs and holdback objective quality flags. Cache and trim generally lack semantic quality proof. |
| Low confidence | There is no general confidence score. Eval gate blocks unsafe/insufficient routing/downshift. Unknown metadata does not block cache/trim by default. |
| Novel request | Cache miss; policy may still route/trim based on model/predicate; no novelty-specific safe default except no semantic hit. |
| Unknown task type | Treated as normal traffic. Task type is optional metadata, not a gating input. |
| Wrong optimization logic | Possible provider failure/circuit breaker, drift rollback after objective failures, feedback can be stored. No automatic per-request recovery for semantically bad cached/trimmed/routed output. |

## Section 1 - Semantic Caching

Verdict: **Prototype-grade for vector semantic cache; exact-match cache is real; broad "semantic cache" claims are dangerous/misleading.**

What is real:

- Exact cache is enabled by default: `settings.proxy_cache_enabled=True`.
- Vector semantic cache exists behind `settings.semantic_cache_enabled=False` by default.
- Embedding model: `text-embedding-3-small` with 1536 dimensions.
- Embeddings are stored in Postgres `proxy_cache_entries.embedding` using pgvector.
- The migration creates a pgvector HNSW index with `vector_cosine_ops`.
- Similarity metric: cosine distance.
- Threshold: global `settings.semantic_cache_threshold=0.08` cosine distance, equivalent to very high cosine similarity. It is not per-org, per-route, per-task, or learned.
- Semantic search is scoped to `project_id` and `model`, so cross-project cache leakage is structurally blocked by query scope.

What is not real enough:

- No cache eligibility classifier.
- No per-task cache-safety policy.
- No "do not cache unless proven eligible" default. Exact cache is enabled by default for all proxy traffic, and response payloads are stored when cache is enabled.
- No freshness detection.
- No personalization detection.
- No domain-risk detection for legal, medical, financial, HR, safety-critical, or regulated prompts.
- No user-level cache namespace unless user metadata changes the exact request body. The cache query is project-scoped, not user-scoped.
- No versioning against prompt-template version, policy version, retrieval corpus version, or business data snapshot.
- No explicit cache invalidation beyond TTL and purge.
- The exact cache key includes `model`, `messages`, temperature/top_p, max tokens, tools/tool_choice, response_format, seed, stop, and n. It does not include every provider parameter or hidden route context.
- Semantic embedding input is only role/content text. It strips much of the structured request context and ignores non-text multimodal content.
- Semantic hit evidence does not include similarity score, matched prompt, matched cache entry ID, threshold, eligibility reason, or cache-safety decision.
- The cache-hit response path does not include the normal request ID header, weakening feedback correlation.
- Semantic cache recommendations appear to depend on `UsageEvent.event_metadata["semantic_cache_key"]`, which the inline proxy does not obviously populate.

Answers to the user's hard questions:

| Question | Answer |
| --- | --- |
| Actual semantic lookup or exact only? | Both exist, but exact is default. Semantic vector lookup is off by default. |
| Embedding model | `text-embedding-3-small`. |
| Embedding storage | Postgres pgvector column on `proxy_cache_entries`. |
| Vector index | HNSW pgvector index from migration, not declared in ORM model. |
| Similarity metric | Cosine distance. |
| Threshold | Global cosine-distance threshold, default 0.08. |
| Threshold scope/learning | Global config only. Not per-org/per-task/per-route/learned. |
| Cache safety | Mostly exact key matching and project/model scope. No semantic safety classifier. |
| Avoid similar-but-different prompt failure | It does not, except by strict threshold and exact param match for model. This is insufficient. |
| Personalized/time-sensitive/legal/medical/financial prompts | Not handled. |
| System/developer/user/tools/params/context in key | Messages and selected params/tools included in exact key. Semantic embedding ignores params and mostly sees text. Retrieved context only included if embedded in messages. |
| Intent/freshness/user/compliance/output format | Output format in exact key. Intent/freshness/user/compliance not first-class. |
| Cross-org leak | Project scoping blocks normal cross-project hits. Tenant isolation is materially better than many prototypes. |
| Versioning | Not implemented beyond model string and TTL. |
| Invalidation | TTL/purge only. |
| Safe default | No. Exact cache is on by default; vector semantic off by default. |
| Audit | Cache hit is logged, but semantic score/matched prompt/matched entry are not. |
| Holdback/shadow eval | No cache-specific holdback or quality eval. |
| Safe task classes only | No task-class restriction. |

Worst failure modes:

- Returning stale factual answers for time-sensitive prompts.
- Returning a cached answer for a semantically close but materially different user request.
- Returning personalized/account-specific data across users inside the same project.
- Caching tool- or retrieval-grounded answers after upstream data changes.
- Serving cached outputs after prompt/policy/template changes.
- Reporting avoided cost without evidence that the answer was still correct.

Required changes:

1. Add `CacheEligibilityDecision` before store and before semantic lookup.
2. Default to `no-store` unless a route/policy explicitly opts in.
3. Require namespace dimensions: org, project, route, environment, user/account scope, task type, prompt template version, retrieval corpus version, output schema version, policy version.
4. Store semantic hit evidence: cache entry ID, prompt hash, matched prompt hash, distance/similarity, threshold, embedding model/version, eligibility reason, freshness policy, namespace.
5. Add high-risk deny list and classifier: legal, medical, financial, HR, safety, user-personalized, real-time factual, tool-dependent, retrieval-dependent.
6. Add customer override headers: `no-store`, `no-cache`, `cache-namespace`, `cache-max-age`, `cache-scope`.
7. Add semantic mismatch tests and cache poisoning tests.
8. Add cache holdback/shadow replay for routes where semantic cache is enabled.

## Section 2 - Batching

Verdict: **Real but off-path. Do not market as automatic online batching.**

What exists:

- Customer stages a batch job.
- Customer uploads JSONL to object storage/local storage.
- Varsten submits the file to OpenAI Files and Batch APIs.
- Varsten polls/syncs/finalizes output.
- Varsten records batch savings using batch pricing when available.

What does not exist:

- No online queue-based request batching in the proxy path.
- No latency-budget batching for live chat completions.
- No grouping of live requests by SLA/provider/model/task/priority.
- No automatic backpressure or head-of-line blocking control for inline traffic.
- No provider-general batching abstraction.
- No batching for Anthropic/Gemini online chat.

Answers:

| Question | Answer |
| --- | --- |
| Implemented in request path? | No. |
| What requests can be batched? | Offline OpenAI Batch API compatible JSONL jobs. |
| Provider/application/queue/embedding/eval? | Provider-level OpenAI Batch API mirror, customer-driven. |
| Can request wait? | Only because customer submits a batch job with offline semantics. |
| Latency budget | OpenAI batch completion window, not online latency budget. |
| Grouping | Customer-provided JSONL. |
| Ordering/traceability | Batch items and output records provide traceability. |
| Quality impact | Should not alter request content, but not generally evaluated. |
| Safe for chat completions? | Safe only for offline batch-compatible jobs. Not safe to imply for live chat. |
| Reduces cost directly? | Yes where provider batch pricing is lower. |
| Providers with lower batch cost | Implemented for OpenAI. Other providers not proven here. |
| Distinguishes online/offline? | Yes architecturally, by separate API. Product copy does not always make this clear. |
| Low traffic | No automatic benefit. |
| Burst traffic | Batch only if customer routes it through the batch workflow. |
| Backpressure/retries/idempotency | Batch workflow has job/item tracking; not an inline backpressure solution. |
| Separate savings? | Batch ledger is separate. |
| Marketable? | Yes as "offline batch job optimization for eligible OpenAI workloads." No as generic "batching optimizes your traffic." |

Positioning recommendation:

Remove "batching" from the main automatic optimizer list unless qualified. Use: "OpenAI Batch API workflow for offline, non-latency-sensitive jobs, with separate savings accounting."

## Section 3 - Model Downshift

Verdict: **Readiness score: 4/10.**

What "downshift" means in code:

- A `ProxyPolicy` with lever `model_downshift` maps requested model to cheaper candidate model/provider.
- Recommendations seed candidate substitutions from curated catalog mappings and pricing deltas.
- Applying a downshift recommendation requires the eval gate to pass for routing levers.
- Live traffic can use holdback control/treatment arms.
- Drift sweep can rollback if objective quality drops.

What is credible:

- There is a model catalog with provider/model/capability flags and cheaper substitute keys.
- Prices are versioned and usage events record price version IDs.
- Replay eval exists for model candidates.
- Holdback exists.
- Objective drift rollback exists.

What is missing:

- No real task classifier.
- No complexity scorer.
- No risk scorer.
- No customer-specific acceptance criteria by task.
- No per-route/task taxonomy beyond "requested model" route key.
- No model capability depth for context length, JSON-schema reliability, latency distribution, region/compliance, tool semantics, rate limits, deprecation, provider outage history.
- No cheaper-first cascade with confidence-based escalation.
- No automatic learning from failures or feedback.
- No proof that a cheaper model preserves quality for this customer's task unless eval samples/golden data are present and sufficient.

Answers:

| Question | Answer |
| --- | --- |
| Equivalent candidates | Curated `cheaper_substitute_key` mappings plus same-route historical cheaper model usage for smart routing. |
| Capability representation | Sparse flags: mode/tier/vision/function/reasoning and pricing. |
| Pricing freshness/versioning | Pricing is versioned and can sync from LiteLLM feed. Freshness depends on sync process. |
| Provider price changes | New prices can be synced/versioned; historical usage keeps price version. No automatic policy invalidation seen. |
| Eligible tasks | Not task-based. Eligibility is policy/model based, with simple predicates for smart routing only. |
| Classification/complexity/risk | Not implemented as actual decision signals. |
| Output quality predicted before execution | Replay eval can compare candidate. No live predictive model. |
| Cheaper first then escalate | No. |
| Frontier holdback | Control arm can stay incumbent for comparison after policy applied. Replay eval uses incumbent response samples. |
| Candidate output evals | Yes, for routing/downshift replay samples. |
| Knows cheaper likely to fail | Only through eval outcomes or objective drift after traffic. |
| Learns from failures | Stores failure registry/feedback but does not update policy automatically. |
| Historical task outcomes vs static rules | Mostly static/policy. Historical usage informs recommendations at a coarse route/model level. |
| Customer preferences | Project policies exist. No rich customer policy DSL for endpoint/task constraints. |
| "Never downshift endpoint" | Bypass/project controls and absence of policy can achieve this, but not as mature endpoint-level policy. |
| Explainability | RequestDecisionEvent can explain model requested/chosen/counterfactual/policy. It cannot explain task-level quality confidence. |

Hard answer:

If a customer uses GPT-4.1, Claude Sonnet, Gemini Pro, or another premium model, Varsten has no hard evidence that a cheaper model preserves output quality for that specific task until it has captured or imported representative samples, run replay evals, and/or run controlled holdback traffic. Generic "simple tasks can use cheaper models" is not implemented as a reliable classifier or proof system.

Blockers to 8/10:

1. Task taxonomy and route identity beyond requested model.
2. Customer golden datasets and acceptance criteria.
3. Risk/complexity/format/tool classifier.
4. Model capability and reliability catalog.
5. Learned or calibrated router with confidence and escalation.
6. Policy versioning and customer-visible explanation.
7. Automated rollback tied to semantic quality metrics, not only objective response health.

## Section 4 - Smart Routing

Verdict: **Mostly static policy routing. "Smart" is overstated.**

What makes it "smart" today:

- It can choose a cheaper candidate based on stored policies.
- A simple predicate can block routing for long prompts, tools, strict JSON/schema, or large max-output requests.
- Cross-provider translation checks can block dialect-unsafe routes.
- Holdback and drift provide some post-activation safety.

What it is not:

- Not learned routing.
- Not latency-aware in a meaningful live way.
- Not rate-limit-aware.
- Not region/compliance-aware.
- Not tool-capability complete.
- Not multimodal-aware beyond limited dialect checks.
- Not agent-loop-aware.
- Not task-risk-aware.
- Not JSON-reliability-aware beyond a crude schema predicate.
- Not a multi-objective optimizer.

Actual routing decision tree:

```text
Request received
  -> parse OpenAI body and optional metadata
  -> if bypass/observe/no performance entitlement: no route
  -> query enabled ProxyPolicy for project + requested_model + routing lever
  -> if no policy: no route
  -> if lever is smart_routing:
       evaluate predicate:
         prompt chars <= max_prompt_chars
         no tools if disallowed
         no JSON schema if disallowed
         max completion tokens <= configured cap
       if predicate fails: log route-ineligible, no route
  -> candidate provider/model from policy
  -> if cross-provider:
       check provider-specific unsupported headers/tools/multimodal content
       if ineligible: log route-ineligible, no route
  -> assign random holdback arm
  -> treatment: replace model/provider
  -> control: keep requested model/provider
  -> call provider
  -> record usage, decision evidence, arm, cost delta, objective quality
```

Credible routing decision tree needed:

```text
Request received
  -> authenticate project and endpoint policy
  -> normalize provider dialect into canonical request model
  -> classify task type, domain, risk, freshness, personalization, tool/schema needs
  -> compute context features: token count, modality, tool calls, retrieval corpus, output schema, latency SLO
  -> load customer policy: allow/deny models/providers/regions, no-cache/no-trim/no-downshift, data-retention, compliance
  -> load model catalog: price, context, modality, tool support, JSON reliability, latency, rate limits, outage state, deprecation
  -> load historical route outcomes: quality, cost, latency, feedback, eval coverage, confidence intervals
  -> decide eligibility per lever
  -> build optimization plan:
       maybe exact cache
       maybe safe semantic cache
       maybe deterministic answer/tool lookup instead of LLM
       maybe trim/summarize/retrieve context
       maybe route/downshift/cascade
       maybe provider fallback
       maybe no optimization
  -> run conflict checks and savings threshold checks
  -> execute with holdback/shadow if policy requires
  -> record full decision evidence and quality/savings ledger
  -> capture feedback and feed offline/online eval loop
```

Hard answer:

Varsten is not routing intelligently in the enterprise sense. It is replacing a model with another model based on policies, price, sparse predicates, and eval gating. That can be useful, but "smart routing" should not be claimed as a learned, multi-objective, quality-aware router.

## Section 5 - Token Trimming

Verdict: **Incomplete and unsafe for broad production use.**

What exists:

- Rule-based prompt transform.
- Keeps all system messages.
- Keeps last N non-system turns.
- Deduplicates exact role/text repeats.
- Collapses whitespace in text content.
- Can run under holdback.
- Logs original vs trimmed prompt character counts and token estimates.

What gets trimmed:

- Older non-system conversation history.
- Exact duplicate role/text messages.
- Whitespace.

What does not get safely handled:

- Developer messages may not be protected if represented as non-system roles.
- Retrieved context relevance is not preserved by retrieval-aware logic.
- Tool outputs can be dropped if they are older non-system messages.
- Few-shot examples can be dropped.
- Output schema/citation/grounding requirements are not explicitly protected unless embedded in kept messages.
- No semantic summarization or fact-preservation check.
- No max compression ratio.
- No pre/post output quality comparison.
- No risk detection before trim.
- No customer-facing "never trim this endpoint/task" policy beyond whether a trim policy exists.

Answers:

| Question | Answer |
| --- | --- |
| Implemented? | Yes. |
| What exactly gets trimmed? | Older non-system turns, exact duplicate text, redundant whitespace. |
| System prompt | Preserved. |
| Developer prompt | Not explicitly protected unless represented as system. |
| User message/history | Old user/assistant/tool turns can be dropped. |
| Retrieved context/tool outputs/few-shot | Can be dropped if old. |
| Attachments/multimodal | Mostly untouched or not deeply understood. |
| Method | Rule-based. |
| Before/after classification | There is no real classification. Routing runs before trim. |
| Required facts/safety/schema/citations | Not provably preserved. |
| Detect task change | No. |
| Compare quality | No direct pre/post compare. |
| Max compression | Not formalized. |
| Customer override | Policy-level only, not mature endpoint/task override. |
| Logged? | Trim counts and savings metadata are logged. |
| Failures attributable? | Objective quality can be arm-tagged; semantic failures are not attributed automatically. |

Hard answer:

Varsten cannot prove it is not deleting context the model needed. It only proves it removed characters and that the response was not obviously malformed. That is not enough.

Required changes:

1. Protect system/developer/policy/schema/citation messages explicitly.
2. Distinguish chat history, retrieved context, tool output, examples, attachments.
3. Add task-risk and output-format gates.
4. Add retrieval-aware selection or summarization with citation preservation.
5. Add max compression ratio and minimum retained facts.
6. Add eval gate for trim, not just routing/downshift.
7. Add per-route/customer "no trim" and "trim only these fields" policies.

## Section 6 - Lever Orchestration

Verdict: **There is a hot-path sequence, not a unified optimization engine.**

What exists:

- A single request path coordinates cache, routing, and trim.
- It deliberately avoids applying routing and token trim together.
- It records one experiment lever at a time to avoid obvious savings double-counting.
- Bypass/observe/entitlement checks are present.

What is missing:

- Formal policy engine.
- Unified optimization plan object.
- Per-lever eligibility decisions.
- Cross-lever conflict resolution.
- Savings threshold gating.
- Quality confidence gating.
- Latency risk gating.
- High-risk default "do nothing."
- Unknown task default "do nothing."
- Customer policy vs global policy precedence resolution.
- Provider reliability/deprecation policy.

Actual lifecycle:

```text
ingress
  -> auth and project context
  -> parse metadata
  -> cache exact lookup
  -> optional semantic lookup
  -> cache hit response OR continue
  -> budget guard
  -> routing/downshift resolution
  -> routing holdback/candidate OR no route
  -> token trim resolution only if no route
  -> trim holdback/apply OR no trim
  -> provider call
  -> ledger/evidence/cache-store/eval-sample
  -> response
```

Naive/brittle spots:

- Cache before risk classification means unsafe cached responses can bypass every later safety check.
- Token trim is not eval-gated despite being quality-risky.
- Smart routing predicate is a static heuristic.
- Unknown task is not protected.
- Missing eval coverage blocks downshift but not cache/trim.
- Quality guardrail config exists but is not a hot-path policy decision system.
- Provider reliability/capability/rate limits do not drive decisions.
- Savings attribution avoids some double-counting by limiting routing vs trim, but cache savings can still be claimed without quality proof.

## Section 7 - Quality Preservation

Verdict: **Quality preservation is not proven broadly.**

What "quality" means in code:

- For live request objective health: response exists, choices exist, finish reason is acceptable, content/tool call is present, JSON is valid when requested.
- For eval replay: exact match, JSON equality, incumbent JSON comparison, short-answer exact, or pairwise LLM judge depending on sample shape.
- For drift: treatment objective quality rate vs control objective quality rate.

What is credible:

- Routing/downshift recommendations can be gated by replay evals.
- Eval runs store sample-level results and cost deltas.
- Holdback control/treatment data can detect objective degradation.
- Manual/human review state exists in eval gate.

What is not enough:

- Objective quality is not semantic correctness.
- Route identity is mostly requested model, not task.
- Eval capture is opt-in and disabled by default.
- Customer-specific rubrics are thin.
- Golden datasets exist as a concept but are not a mature workflow.
- LLM-as-judge is not calibrated against human preference.
- Cache and trim have no robust quality gate.
- No confidence intervals are surfaced as a hard precondition for dashboard savings claims except in eval internals.
- No automatic rollback from user feedback or semantic judge failures.

Hard answer:

Varsten can sometimes prove "we saved money while the response did not obviously break." It cannot generally prove "we saved 37% while maintaining quality." For routing/downshift with sufficient customer-specific eval samples and holdback, it can begin to make a narrow claim. For cache/trim, no.

Unsupported quality implications found:

- Marketing "Cut spend safely" overstates global safety.
- Marketing "without changing what the model returns" for token trim is unsupported.
- Marketing "where it produces equivalent output, and only where it does" is true only for eval-gated downshift routes with enough coverage, not generally.
- "Quality guardrails and automatic rollback" is partly true but not a complete quality system.
- Security page "quality decision behind a billable optimization" is overbroad for cache/trim/batch.

## Section 8 - Savings Measurement

Verdict: **Engineering-estimate-grade overall; measured-subset-grade for direct cache/batch and holdback routing. Not finance-grade yet.**

What is strong:

- Price rows are versioned.
- Usage events can store actual/counterfactual costs.
- Cache hits and batch jobs can record direct avoided API cost.
- Routing/downshift can estimate counterfactual cost and use holdback experiments.
- Request decision evidence links request ID, usage event, chosen/counterfactual model/provider, lever, policy, and price version.
- Verified savings are separated from estimated savings in newer code paths.

What is weak:

- Baseline often uses candidate response token counts as if incumbent would have produced the same output length.
- It does not include infrastructure cost, eval overhead, embedding cost, cache storage, queue/object storage, customer engineering overhead, or latency business cost.
- It does not consistently distinguish exact vs semantic cache in UsageEvent metadata.
- Routing lever attribution can fall back to currently enabled policies rather than immutable per-event policy metadata.
- Quality evidence is not a precondition for all claimed savings.
- Finance export/audit package is not mature.
- Provider-specific pricing quirks are only as good as the catalog sync and model mapping.
- Failed calls/retries/tool calls/reasoning/image tokens are not comprehensively accounted for across all providers/workloads.

Answers:

| Question | Answer |
| --- | --- |
| Baseline | Original/requested model for routing; direct avoided provider cost for cache/batch; estimates for recommendations. |
| Shadow call? | Eval replay/holdback for some routing; not generally per-request. |
| Historical/simulated/list price | Recommendations use estimates; ledger uses catalog prices. |
| Token classes | Basic input/output; provider cache-read and batch rates in pricing. Reasoning/image/tool costs incomplete. |
| Retries/failed calls | Not finance-grade complete. |
| Varsten infra/eval/cache cost | Not deducted from verified savings. |
| Per-lever attribution | Exists but imperfect; exact/semantic conflated in usage metadata. |
| Double-counting | Routing vs trim avoided by mutual exclusivity; estimates and verified savings can still confuse if displayed poorly. |
| Per-request audit | RequestDecisionEvent is a good start. Not complete enough for semantic cache or CFO-grade billing. |

If Varsten charges 25% of verified savings:

"Verified" must mean direct or randomized-control-measured API savings with immutable baseline, price version, policy version, token classes, overhead exclusions explicitly stated, quality gate status, and exportable request-level evidence. Today it means something narrower and less finance-grade.

## Section 9 - Learning Over Time

Verdict: **Varsten stores traces. It does not yet learn in a meaningful closed loop.**

What data is collected:

- Usage/cost/latency.
- Optional metadata dimensions.
- Cache hits.
- Routing/trim arms.
- Objective quality.
- Eval replay samples when enabled.
- Feedback events when customer sends them.
- Batch job/item data.

What is sufficient for:

- Spend attribution: yes, partly.
- Static recommendation generation: yes.
- Building an offline eval corpus: yes, if capture is enabled.
- Diagnosing some failures: yes.

What is not sufficient/implemented for:

- Automatic routing policy updates.
- Per-task model performance scores.
- Cache threshold tuning.
- Token trimming policy learning.
- Privacy-preserving cross-tenant learning.
- Closed loop from feedback to eval to deployment.
- Agent loop optimization.
- Workflow optimization.

Hard answer:

Varsten does not actually learn today. It logs, samples, and recommends from metadata/usage. The learning loop is manual and incomplete.

Minimum data model for honest "improves over time":

- `task_clusters`: project, route, inferred task, examples, embedding centroid, risk/freshness flags.
- `route_outcomes`: task_cluster, model/provider, policy_version, latency, cost, quality metrics, feedback outcomes, CI.
- `optimization_decisions`: immutable plan, eligible levers, rejected levers, reasons, confidence.
- `cache_match_events`: entry, query, similarity, namespace, eligibility, quality feedback.
- `trim_decisions`: before/after structured segments, protected facts/instructions, compression ratio, outcome.
- `policy_versions`: customer/global policy, rollout state, eval gate, rollback pointer.
- `eval_datasets`: customer/task-specific samples, golden/reference outputs, rubric versions, provenance.
- `feedback_events`: explicit and implicit edits/regens/escalations linked to request and decision.
- `experiments`: online/offline, arms, sample sizes, CI, guardrails, status.

Minimum loop:

`trace -> classify/cluster -> candidate policy -> offline eval -> human review if needed -> staged rollout/holdback -> online quality/savings ledger -> feedback/drift -> rollback or promote`

## Section 10 - Competitive Comparison

### Blunt Competitive Memo: Why Varsten Is Or Is Not Credible Against Enterprise AI Optimization Platforms

Varsten is credible as a narrow savings-proof proxy experiment for teams willing to pilot route-level optimizations. It is not currently credible as a broad enterprise AI optimization platform. Competitors either dominate gateway plumbing, observability/evals, or enterprise workflow/ontology optimization. Varsten's potential wedge is not "we have caching/routing/batching." Everyone has that. The wedge must be "verified savings tied to quality evidence and billing-grade ledgers for customer-specific LLM routes." The current code is not yet strong enough to own that wedge publicly.

### LiteLLM Gateway

- Problem solved: unified LLM proxy for 100+ providers with spend tracking, budgets, load balancing, routing, fallbacks, caching, guardrails, and enterprise controls.
- Trust: widely used OSS/gateway baseline; enterprise offering exists.
- Varsten better: gain-share savings ledger/eval-gated recommendation workflow is more cost-optimization-specific.
- Varsten worse: provider coverage, routing/fallback depth, production gateway maturity, cache controls.
- Embarrassing claim: "We are a better AI gateway than LiteLLM" is not defensible.
- Credible wedge: savings-proof layer on top of gateway traffic, not generic gateway.

### Cloudflare AI Gateway

- Problem solved: edge-hosted AI gateway with analytics/logging, caching, rate limiting, retries, fallback, and provider access.
- Trust: Cloudflare distribution/security/procurement advantage.
- Varsten better: potential gain-share optimization workflow and replay/holdback evidence.
- Varsten worse: infrastructure trust, edge footprint, enterprise procurement, resilience.
- Embarrassing claim: "Enterprise-grade gateway infrastructure" against Cloudflare.
- Credible wedge: deeper per-route savings proof, if built.

### Helicone

- Problem solved: observability, sessions, cost tracking, gateway, caching, eval scores, feedback, prompt management.
- Trust: strong developer adoption and observability depth.
- Varsten better: more opinionated verified-savings/product economics.
- Varsten worse: workflow/session tracing maturity, observability UX, eval/feedback ecosystem.
- Embarrassing claim: "We understand agent workflows better" is false today.
- Credible wedge: CFO-facing savings ledger with intervention proof.

### Portkey

- Problem solved: advanced AI gateway with semantic/simple cache, conditional routing, fallbacks, retries, circuit breaker, load balancing, canary, guardrails, batch, multimodal, virtual keys.
- Trust: mature gateway feature set and enterprise/security posture.
- Varsten better: possible eval-gated savings accounting.
- Varsten worse: almost every gateway/control-plane feature.
- Embarrassing claim: "Smart routing/semantic cache as differentiation."
- Credible wedge: verified route-level cost-quality experiments, not raw gateway capabilities.

### TrueFoundry

- Problem solved: enterprise AI gateway plus deployment/MLOps/agent/platform governance across VPC/on-prem/cloud.
- Trust: enterprise platform posture, deployment models, compliance claims, RBAC/audit.
- Varsten better: simpler cost-savings-specific product if focused.
- Varsten worse: infra/deployment/governance/security surface.
- Embarrassing claim: "Fortune 500 enterprise-ready platform."
- Credible wedge: lightweight savings audit for teams that do not want a full platform.

### Maxim/Bifrost

- Problem solved: high-performance OSS/enterprise AI gateway with model catalog, budgeting, provider fallback, MCP gateway, virtual keys, telemetry, semantic caching.
- Trust: performance/gateway positioning, OSS adoption.
- Varsten better: cost proof and gain-share business model if substantiated.
- Varsten worse: gateway throughput/performance/provider controls.
- Embarrassing claim: "Best gateway performance."
- Credible wedge: measurable savings decision engine.

### LangSmith/LangChain

- Problem solved: tracing, evaluation, feedback, online/offline eval lifecycle, prompt/application debugging.
- Trust: ecosystem standard for LLM app observability/evals.
- Varsten better: inline cost optimizer and billing ledger, not just evals.
- Varsten worse: eval maturity, trace depth, dataset lifecycle, annotations, agent visibility.
- Embarrassing claim: "Quality proof" without comparable eval workflow.
- Credible wedge: automatic spend intervention with LangSmith-like eval rigor.

### Braintrust

- Problem solved: systematic evals, experiments, CI/CD, online scoring, production trace feedback into datasets.
- Trust: strong eval-driven development posture.
- Varsten better: inline cost-control action layer.
- Varsten worse: eval discipline and experiment platform.
- Embarrassing claim: "Verified quality preservation" without Braintrust-grade evals.
- Credible wedge: use Braintrust-style methodology as the proof layer for savings.

### Palantir AIP / AIP Evolve-Style Optimization

Based on the user's description, AIP Evolve attacks cost and quality by optimizing the agent/workflow architecture, not just swapping models.

Against that standard:

- Varsten optimizes individual model calls. It does not optimize whole workflows.
- It cannot identify when an LLM call should be replaced by deterministic logic, structured lookup, SQL, retrieval, cached tool output, or ontology-backed action.
- It does not understand customer entities, workflows, permissions, actions, or business ontology.
- It does not optimize agents end to end.
- It cannot detect repetitive agent steps except via crude usage/session metadata if provided.
- It cannot tune prompts safely.
- It cannot validate outputs against business rules except basic JSON/objective health.
- It lacks a closed loop from traces to diagnosis to fix proposal to eval to deployment.

Hard answer:

Varsten cannot honestly compete with AIP Evolve-style value optimization today. It can maybe sell a narrower "LLM call spend audit and controlled optimization" wedge to teams not buying a full enterprise ontology/platform.

### vLLM Semantic Router / Academic Learned Routing

The 2026 vLLM semantic router work describes signal orchestration, policy conflict detection, context-length routing, category-aware semantic caching, feedback-driven adaptation, hallucination detection, safety classification, and workload-router-pool optimization. RouteLLM-style systems use preference data or calibrated uncertainty to route by cost-quality tradeoff.

Varsten lacks:

- Signal extraction breadth.
- Learned/calibrated routing.
- Per-workload threshold tuning.
- Policy conflict detection.
- Quality-aware cascading/escalation.
- Feedback-driven adaptation.
- Agent/multimodal routing.

Varsten's current routing is many levels below expert practice.

### Internal Enterprise Teams

Serious internal teams can build a LiteLLM/Portkey/Cloudflare gateway plus LangSmith/Braintrust evals plus custom business policy. Varsten must beat that by reducing integration burden and proving savings fast. Today it does not yet have enough proof automation to be clearly superior.

## Section 11 - Enterprise Marketability

| Market | Honest status |
| --- | --- |
| Fortune 500 | Not currently credible as a production traffic owner. Security/compliance/proof maturity insufficient. |
| Mid-market | Credible only as a tightly scoped pilot with explicit no-risk/Base mode and manually approved optimizations. |
| Startups | Marketable as cost observability plus selected optimization if expectations are honest. |
| Self-serve developer tool | Marketable if positioned as proxy + savings estimates + exact cache/batch/pilot routing, not autonomous quality-preserving optimizer. |
| Services-led savings audit | Best near-term ICP. |
| AI cost optimization | Yes, with caveats. |
| AI gateway | Weak claim; many incumbents are stronger. |
| LLM FinOps | Plausible observe/ledger wedge. |
| Verified AI savings | Only for direct cache/batch and properly measured holdback policies. |
| Quality-preserving AI cost reduction | Too broad today. Must be route-specific and evidence-bound. |

Blockers:

- Security: no SOC 2 or formal compliance claim should be made.
- Compliance: no mature region/data residency/customer policy model.
- Tenant isolation: decent project scoping, needs adversarial tests and exportable controls.
- Data retention: cache stores content; policy controls too coarse.
- PII: no robust PII detection/redaction/cache gating.
- Secrets: provider-key handling exists, but enterprise controls/audit need hardening.
- Latency overhead: semantic cache embeddings add latency; routing classifier future adds overhead; no budgeted planner.
- Reliability: fail-open claims depend on integration mode; base-URL proxy outage can still break traffic unless SDK fallback is used.
- Provider fallback: limited compared with gateways.
- Observability: useful but not agent/workflow-complete.
- Eval maturity: insufficient for broad quality claims.
- Savings proof: not CFO-grade.
- Integration friction: base URL and SDK manageable, but metadata is optional and crucial.
- Procurement risk: high for all-AI-traffic proxy without compliance reports.
- Differentiation risk: gateway features are commoditized.

ICP recommendation for next 90 days:

Sell to startups and mid-market teams spending meaningful dollars on OpenAI-compatible chat workloads, where they can tolerate a controlled pilot. Sell "services-led savings audit + measured optimization pilot." Do not sell Fortune 500 "quality-preserving autonomous AI optimization" yet. Fortune 500 is delusional right now unless the engagement is a non-production audit or sandboxed proof-of-value.

## Section 12 - Product Claims Audit

| Claim/location | Classification | Why | Replacement language |
| --- | --- | --- | --- |
| "Cut AI spend safely" (`marketing/app/page.tsx`) | Partially supported, too broad | Some gates exist; cache/trim unsafe broadly. | "Find and apply approved savings opportunities with measured guardrails." |
| "Smart routing" | Partially supported/misleading | Static policy + simple predicate, not learned. | "Policy-based model routing with eval-gated rollouts." |
| "Semantic cache" | Dangerous if broad | Vector cache off by default and lacks safety layer. | "Exact response cache today; semantic cache available for approved low-risk routes." |
| "Repeated and near-identical requests resolve from cache" | Misleading | Near-identical only if semantic enabled; unsafe classes not gated. | "Identical requests can resolve from cache; semantic reuse is opt-in." |
| "Token trim ... without changing what the model returns" | Dangerous | No proof of semantic preservation. | "Pilot token trimming on approved routes with holdback measurement." |
| "Downshift ... equivalent output, and only where it does" | Partially supported | Eval gate for routing exists, but no task classifier and eval coverage may be thin. | "Downshift candidates are tested against captured route samples before rollout." |
| "Batching" in automatic lever list | Partially supported | Real only off-path OpenAI Batch workflow. | "Offline batch workflow for eligible OpenAI jobs." |
| "A failed optimization will never break your app" | Misleading | SDK fallback may help; base-URL proxy outage can break traffic. | "Optimization steps are designed to fail open where integration mode supports it." |
| "Changes are tested first... rolls back before affecting broader audience" | Partially supported | Eval gate/holdback/drift exist; rollback after some treatment traffic. | "Model-route changes can be replay-tested, rolled out with holdback, and rolled back on objective drift." |
| "Quality guardrails and automatic rollback" | Partially supported | Objective quality only, guardrails not full hot-path policy. | "Objective response-health guardrails and drift rollback for gated model policies." |
| "Finance-grade savings ledger" | Misleading | Ledger is good but not CFO-grade. | "Request-level savings ledger with price-versioned estimates and measured savings for supported levers." |
| "Cut AI spend without losing quality" footer | Dangerous | Quality not broadly proven. | "Reduce AI spend with route-level evidence and guardrails." |
| "Set reuse, retention, routing, and eval behavior per route" security/privacy | Overstated | Route-level policy is not mature across all dimensions. | "Configure reuse, retention, routing, and eval controls for approved workloads." |
| "Each savings record holds ... quality decision" | Overstated | Quality often null/coarse. | "Savings records include cost and decision evidence; quality evidence is available for gated model-route experiments." |
| Static dashboard "Semantic cache Active" | Simulation-only | Decorative hardcoded numbers. | Label as "Example dashboard" or replace with dynamic data. |
| Static "High confidence 98/100" | Simulation-only/misleading | No matching confidence model. | Remove or label as illustrative. |

## Section 13 - Tests and Proof Matrix

| Test | What it proves | Failure caught | Current status | Files involved | Priority | Plan |
| --- | --- | --- | --- | --- | --- | --- |
| Exact cache key completeness | Identical only when output-determining fields match | Wrong exact cache hit | Partial | `cache.py`, `test_proxy.py` | P0 | Add cases for all provider params, response_format, penalties, user, modalities. |
| Semantic mismatch suite | Similar wording with material differences misses | Unsafe semantic reuse | Weak | `cache.py`, `embedding.py` | P0 | Build adversarial prompt pairs by domain/task. |
| Tenant cache isolation | No cross-org/project/user leak | Data leak | Partial | `proxy_cache`, evidence tests | P0 | Add semantic cache cross-project and user namespace tests. |
| Cache poisoning | Bad answer cannot poison later prompts | Repeated wrong/stale response | Missing | cache path | P0 | Add no-store, force-refresh, eval holdback, poisoned entry tests. |
| Freshness cache gate | Time-sensitive prompts bypass cache | Stale facts | Missing | cache eligibility | P0 | Add classifier/policy tests. |
| PII/personalization cache gate | User-specific prompts scoped or bypassed | Privacy leak | Missing | request context/cache | P0 | Add metadata and PII tests. |
| Token trim preservation | Protected instructions/schema/facts remain | Broken outputs | Weak | `trim.py`, `test_proxy_trim.py` | P0 | Add structured segment model and golden examples. |
| Tool output trim safety | Tool results not dropped incorrectly | Agent failure | Missing | `trim.py` | P0 | Add tool-output histories. |
| Downshift eval gate | Unsafe candidates cannot apply | Quality regression | Partial | `eval/gate.py` | P0 | Add task-specific eval and insufficient-data tests. |
| Routing reproducibility | Same policy/version produces explainable decision | Non-auditable routing | Partial | `routing.py`, evidence | P1 | Persist policy version and decision features. |
| Policy conflict | Customer deny overrides global optimize | Compliance breach | Missing | policy engine | P0 | Implement precedence tests. |
| Savings attribution | No double-counting across levers | Inflated savings | Partial | `ledger.py`, `savings_measurement.py` | P0 | Add exact/semantic/routing/trim mixed scenarios. |
| Finance export | Per-request proof export reconciles to invoice | CFO rejection | Missing | billing/proof APIs | P1 | Add export fixture and reconciliation test. |
| Provider failover | Provider outage routes/fails open correctly | App outage | Weak | adapters/circuit | P0 | Add upstream 5xx/rate-limit/fallback tests. |
| Base-URL outage behavior | Honest fail-open claim by integration mode | False reliability claim | Missing | SDK/proxy | P0 | Add SDK fallback tests and docs. |
| Streaming lifecycle | Streaming optimized requests capture usage safely | Lost ledger/hangs | Partial | router streaming tests | P1 | Add cache/routing/trim streaming variants. |
| Rate limit/backpressure | Burst traffic does not collapse proxy | Reliability failure | Weak | rate limit/circuit | P1 | Add load and Redis mode tests. |
| Retry/idempotency | Retries do not double-charge/double-store | Billing/cache corruption | Missing | provider/batch/proxy | P1 | Add idempotency keys. |
| Eval regression | Eval suite catches candidate failures | Bad downshift | Partial | eval runner | P0 | Add representative customer task datasets. |
| Dashboard accuracy | UI numbers match ledger/proof API | False claim | Missing | frontend/marketing/backend metrics | P1 | Add end-to-end fixtures. |

## Section 14 - Required Architecture Improvements

| Component | Exists today | Missing | MVP | Production-grade | Tables/services/tests | Priority |
| --- | --- | --- | --- | --- | --- | --- |
| Request classifier | Optional metadata only | Inferred task/risk/freshness | Rule/ML classifier for task/risk/cache safety | Calibrated per-tenant classifiers with drift | `request_classifications`, classifier svc, confusion tests | P0 |
| Task taxonomy | Freeform `task_type` | Canonical route/task identity | Fixed taxonomy + customer route mapping | Hierarchical taxonomy with task clusters | `task_routes`, `task_clusters` | P0 |
| Risk scorer | Metadata only | Domain/compliance/output risk | Deterministic risk rules | Learned + policy-calibrated risk | `risk_assessments`, adversarial tests | P0 |
| Policy engine | If/else + ProxyPolicy | Conflict/precedence/versioning | JSON policy DSL per project/route | Audited ABAC/RBAC policy engine | `policy_versions`, conflict tests | P0 |
| Optimization planner | None | Unified plan | Plan object listing eligible/rejected levers | Multi-objective optimizer with confidence | `optimization_plans`, lifecycle tests | P0 |
| Lever executor | Inline utilities | Uniform contracts | `evaluate/execute/record` per lever | Transactional, idempotent executors | executor service, idempotency tests | P1 |
| Eval engine | Replay for routing/downshift | Task-specific rubrics and trim/cache evals | Customer golden + captured replay | Online/offline eval platform | `eval_datasets`, `eval_rubrics`, CI tests | P0 |
| Holdback system | Random per-request arm | Stratification/power/policy versions | Stable hash assignment by route/user | Experiment framework with CI/stopping | `experiments`, stats tests | P1 |
| Savings ledger | Good start | Overheads/export/immutable policy refs | Per-event immutable baseline and lever | CFO reconciliation and invoice proof pack | `savings_ledger`, export tests | P0 |
| Quality ledger | Coarse objective quality | Semantic/task metrics | Per-request quality evidence status | Calibrated quality ledger with CIs | `quality_events`, regression tests | P0 |
| Model catalog | Sparse | Context, modalities, tools, JSON, latency, regions | Expand schema | Live reliability and deprecation feed | `model_capabilities`, catalog tests | P0 |
| Pricing catalog | Versioned | Complete token classes/overheads | Sync validation and stale alerts | Provider-contract pricing and quirks | pricing service, reconciliation tests | P0 |
| Customer config | Basic project/policies | Endpoint/task controls | Route-level allow/deny/no-cache/no-trim | Full tenant governance UI/API | `customer_route_policies` | P0 |
| Trace store | Usage/events/samples | Agent/session/tool traces | Session IDs and tool/retrieval spans | Full OpenTelemetry trace graph | `trace_spans`, agent tests | P1 |
| Feedback capture | RequestFeedback | Integration into learning | API + SDK helpers + dashboard | Feedback-weighted routing/evals | feedback loop tests | P1 |
| Experimentation | Holdback + eval | Proper rollout lifecycle | Draft/apply/pause/rollback/promote | Sequential testing and guardrails | `experiment_arms`, stats tests | P1 |
| Rollback | Objective drift | Semantic quality/user feedback | Rollback on eval/feedback thresholds | Automated safe rollback with incident record | rollback tests | P1 |
| Cache safety layer | None | Eligibility, namespace, invalidation | Route opt-in + namespaces + no-store | Learned thresholds and shadow quality | `cache_policies`, mismatch tests | P0 |
| Agent loop detector | None | Session/tool loop analysis | Detect repeated calls via headers/sessions | Recommend deterministic workflow changes | `agent_steps`, loop tests | P2 |
| Workflow recommendations | Usage heuristics only | Business/process diagnosis | Manual savings audit report | Trace-to-fix-to-eval-to-deploy loop | recommendation svc, outcome tests | P2 |

## Section 15 - Final Verdict

1. What Varsten actually is today

An inline OpenAI-compatible proxy plus SaaS control plane that can observe spend, store price-versioned usage, exact-cache responses, run optional semantic cache, apply eval-gated model policies, trim prompts by simple rules, run OpenAI Batch jobs, and record some savings/evidence.

2. What Varsten claims to be

A quality-preserving AI cost optimizer that uses semantic caching, batching, model downshift, smart routing, token trimming, spend attribution, and learning over time to reduce spend safely.

3. The gap

The infrastructure skeleton is real. The intelligence layer is shallow. Most quality preservation is not proven. Learning over time is mostly logging. Semantic caching and token trimming are not safe enough for broad claims. Batching is not online. Smart routing is not very smart.

4. The most dangerous false assumption

That reducing API cost while returning a syntactically valid response means quality was maintained.

5. The strongest real asset

The combination of request decision evidence, price-versioned usage, eval-gated routing/downshift, holdback, and measured savings scaffolding. This is a real foundation.

6. The weakest part of the engine

Task/risk/quality understanding. Varsten does not know what the customer is trying to accomplish unless the customer tells it, and even then it barely uses that metadata for safety.

7. What must be removed from positioning immediately

- Broad "semantic caching" claims.
- "Token trim without changing what the model returns."
- "Smart routing" as learned/best-model routing.
- "Finance-grade savings ledger."
- "Quality-preserving" without route-specific evidence.
- "Failed optimization will never break your app" without integration-mode caveat.
- Any static dashboard numbers that look like live proof.

8. What can be honestly sold today

- AI spend observability and attribution.
- Exact response caching for explicitly approved low-risk routes.
- OpenAI Batch API workflow for offline jobs.
- Eval-gated model downshift/routing pilots.
- Request-level savings evidence for supported levers.
- Services-led savings audits.

9. What must be built before charging on verified savings

- Immutable savings ledger with policy/version/quality evidence.
- Exportable proof pack.
- Quality preconditions per billable lever.
- Cache/trim safety gates.
- No double-counting reconciliation.
- Provider pricing completeness and overhead disclosure.

10. What must be built before selling to Fortune 500

- SOC 2/security program evidence.
- Formal tenant/data retention/compliance controls.
- Policy engine with allow/deny/region/model constraints.
- Enterprise gateway reliability/fallback story.
- Task-specific eval/quality system.
- Audit exports.
- Provider failover/rate-limit support.
- Agent/session trace support.

11. What the next 30 days of engineering should focus on

- Build cache eligibility and namespace policy; default semantic cache to off and exact cache to explicit opt-in for production.
- Eval-gate token trim.
- Persist immutable policy/version/lever metadata on every usage event.
- Fix cache-hit request ID and semantic hit evidence.
- Expand model/pricing catalog for context/tools/JSON/latency/deprecation.
- Redline marketing claims.

12. What the next 90 days of product validation should focus on

- Run 3-5 paid or design-partner savings audits on real production traces.
- For each customer, define 2-3 task routes, golden samples, acceptance criteria, and "never optimize" rules.
- Prove one route-level downshift with replay eval + holdback + customer review.
- Prove one exact-cache route with explicit cache scope/freshness.
- Prove one offline batch workflow.
- Do not claim general autonomous optimization until these pilots show repeatable, auditable savings with quality evidence.

---

## Addendum (Second-Pass Re-Audit, 2026-06-30)

A second independent investigation of the full request path, levers, eval/holdback machinery, savings math, pricing, config defaults, the ~11.9k-line test suite, and `marketing/app/page.tsx` **corroborates every lever-level verdict above.** No verdict is downgraded or reversed. This addendum records only what the first pass did not, plus one correction.

### Correction to carry forward (the first pass was right)

The semantic cache **does** have a pgvector **HNSW index** (`vector_cosine_ops`) created in `alembic/versions/d4e5f6a7b8c9_proxy_cache_embedding.py:32`. Any future critique claiming the vector search is an unindexed sequential scan / latency cliff is **wrong** — do not regress this point. The cosine lookup is index-backed.

### Net-new findings (gain-share accounting — not covered above)

These matter specifically because the business model bills a percentage of *verified* savings, so any cost that erodes the customer's true net must be visible in the savings number.

1. **The holdback's own cost is never netted out of reported savings.** The control arm (default 5%, `proxy_policy.py:79`) deliberately keeps paying full incumbent price as the measurement baseline. That is correct experimental design, but `savings_measurement.py::compute_verified_savings` reports the gross treatment-arm savings and never subtracts the premium the customer paid to keep the control arm unoptimized. Reported `verified_savings_usd` is therefore gross-of-measurement-cost. For a CFO-facing, gain-share number this is an overstatement of net benefit. **Fix:** subtract `(control_request_count × per-request savings)` — the savings forgone on held-back traffic — as an explicit line item, or at minimum surface it alongside the gross figure.

2. **Replay-eval and embedding API spend is also unaccounted.** The shadow eval replays the route's traffic through the candidate and runs a position-swapped judge (`eval/openai_ops.py`), and the semantic-cache miss path embeds prompts (`proxy/embedding.py`) — all on the customer's own provider key. None of this spend is charged against the savings it produces. At low sample counts it is immaterial; for a high-volume route under continuous eval it is not. **Fix:** meter eval/embedding calls (they already ride the same `usage_events` ledger surface) and net them into the per-lever savings.

3. **The *estimated* confidence band is a hard-coded ± multiplier, not statistical** (`savings.py:184`: `confidence_low = gross × 0.80`, `confidence_high = gross × 1.15`). It is correctly walled off from billing — the fee is charged only on `verified_savings_usd` (`savings.py:242`) via the `MEASURED_METHODS` allow-list — so this is not a billing defect. But it is presented next to the real, statistically-derived holdback CI from `experiment.py`, and a skeptical reader who notices the estimate band is a fixed fudge factor will discount the rigorous number too. **Fix:** either drop the numeric band on estimates and label them "estimate, not measured," or derive a real prediction interval; never show a fabricated ±15% beside a genuine 95% CI.

### Net assessment after the second pass

Unchanged from the body of this document. The measurement-and-proof core (concurrent randomized holdback + eval gate + objective drift rollback + strict measured/estimated separation with fee-on-verified-only) remains the strongest and most defensible asset; the semantic cache safety model and the absence of task/risk classification feeding routing remain the weakest. The three findings above are refinements to the savings ledger, not new structural risks: fix them before quoting a net-savings or margin figure to a finance buyer.

This is the claim varsten needs to be able to confidently make: Varsten automatically optimizes all AI traffic while preserving quality, and learns and improves over time.
