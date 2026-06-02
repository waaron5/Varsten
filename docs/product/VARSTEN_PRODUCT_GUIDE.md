# Varsten Product Guide

## Purpose of this document

This is the product source of truth for Varsten. It describes the finished, sellable product in its entirety: what it is, what it does, how it is sold, how it earns trust, and what every screen is for. Coding agents, design agents, and contributors should read it to understand what this thing is supposed to be as a real product in market, not to be told what to build first. Sequencing and engineering scope live in `CLAUDE.md`. This document describes the destination.

Varsten is first and foremost an AI cost-optimization engine. It is second an analytics dashboard. That ordering is the most important thing in this document. Everything else follows from it.

## What Varsten is

Varsten cuts a company's AI bill and proves how much it cut. A customer connects their AI providers and traffic, Varsten finds specific cuts worth real money, applies the safe ones automatically, holds output quality with guardrails, and reports a verified savings number that a CFO will trust. The customer pays a percentage of the savings Varsten verifiably produces.

The product is the engine that executes the savings, not the dashboard that reports on them. Spend visibility is close to commoditized. Cloud providers and observability tools already show a team where its money went. Nobody pays a recurring fee to be told they are bleeding money. They pay to have the bleeding stopped and the savings proven. So the engine and the proof are the product. Analysis exists to feed the engine and is a supporting section, not the destination.

Measurement still matters, and Varsten is rigorous about it, because the savings number is only as credible as the spend numbers underneath it. You cannot attribute a saved dollar you cannot measure. Authoritative cost measurement is the foundation that makes the proof defensible. It is the foundation, not the building.

## One-sentence value proposition

Varsten automatically cuts your AI spend without degrading quality, and proves the savings with a number your finance team can defend.

## The money loop

Every part of the product serves one loop:

Spend comes in. The engine cuts it. Guardrails keep the cuts safe. The savings get proven. A human approves what is not yet trusted. Approved cuts feed back into the engine.

The governing design principle is simple: every screen answers a money question and produces a decision. A screen that only informs does not belong in the daily path.

## The selling point

Varsten is a no-brainer because of how it is priced and how it proves itself. The customer pays a percentage of verified savings, with a floor that guarantees the fee stays below the savings. The customer never pays more than Varsten saves them. The Proof section shows realized savings, the Varsten fee, and the net to the customer after the fee, every month, measured against a live control. The buyer is not asked to take savings on faith or to do their own ROI math. The product carries the burden of proof.

That reframes the purchase. A flat SaaS fee makes a CTO weigh cost against uncertain benefit. Pay-for-verified-savings makes the question "why would we not turn this on," because the downside is bounded to zero and the upside is measured and banked.

## Target customer

The sharpest fit is an AI-native company where token spend is a real line of cost of goods sold and gross margin depends on it. For that company Varsten is not a nice-to-have cost tool, it is a margin and survival tool, and the per-customer margin view is the screen that lands.

The buyer and daily user is technical: a CTO, VP of Engineering, or platform / FinOps lead at a seed to mid-market company running LLMs in production. A CEO or CFO is a wedge into the deal because they react to the spend number and the savings number, but the product is built for the technical owner, and the stickiness lives with them. They run one or more of OpenAI, Anthropic, Google Vertex, AWS Bedrock, and Azure OpenAI, often through a gateway like LiteLLM or a custom internal wrapper, and their AI spend has become material, unpredictable, or hard to attribute.

The buyer pain Varsten removes is not "I cannot see my spend." It is "I can see my spend climbing and I do not have a safe, fast way to bring it down without risking quality or pulling engineers off the roadmap."

## The savings engine

The engine is the heart of the product. It cuts spend through five levers. Every recommendation, every automated action, and every line of savings maps to one of them.

- **Smart routing** sends each request to the cheapest model that clears the quality bar for that route. Routing is decided per request from a policy, not set once globally.
- **Semantic cache** reuses an answer when a new request is semantically close to one already served, removing an entire model call on a hit.
- **Token trim** compresses prompts and context before the call without changing the output, cutting input tokens on every request to a route.
- **Cheaper model** systematically moves whole workloads down to a cheaper tier wherever evals show quality holds.
- **Batching** routes non-urgent jobs through batch endpoints to capture bulk pricing in exchange for a controlled delay.

The engine continuously analyzes traffic, identifies which levers apply to which routes, estimates the savings and the risk of each, and either applies the cut or surfaces it for approval. The savings each lever produces are measured, attributed, and shown in Proof.

### Autonomy: auto versus approve

For each lever the customer decides whether the engine acts on its own or waits for a human. Low-risk, objectively-measurable levers default to auto: semantic cache, batching, and token trim. Medium-risk levers default to approve: smart routing and cheaper-model downgrades. Every auto-applied cut still passes all guardrails before going live, and any cut that fails a quality gate is rolled back automatically and surfaced in the decision queue. Auto is the stronger experience and the one a customer earns into lever by lever as trust builds.

## The app, section by section

Varsten is a left side nav with six sections. The vertical order is the flow. A user lands at the top, works in the Engine, and drops into Analysis only to investigate. Each side nav item is a page. The tabs inside a page swap the main content and default to the first tab on open. Command Center is the only multi-panel dashboard and has no tabs.

### Command center

The home surface. It answers "what should I do right now" and produces approvals. It shows live savings (saved this month and current annual run-rate), a decision queue of cuts waiting for a yes, a feed of what the engine has already done on its own, and the single largest source of waste right now. A user can approve or dismiss a recommendation here without going deeper. Command Center and the Engine together should cover the large majority of daily use.

### Engine

The workspace where spend is cut. Three tabs.

- **Recommendations** is a ranked list of proposed cuts, each with its lever, its monthly dollar impact, a risk label, a one-line rationale, and a one-click apply. This is the screen that sells the product, because it turns "your bill is too high" into "here is a specific $24,800-per-month cut at low risk, apply it."
- **Levers** shows the five mechanisms, each with an on/off, its savings to date, and its measured quality impact. Turning a lever off pauses it everywhere.
- **Automation** is where the customer sets auto versus approve per lever, with each lever's risk profile shown alongside.

### Guardrails

The section that makes the cuts safe, so a CTO can let the engine act. Three tabs.

- **Quality** sets the floor the engine may never cross: minimum model tier per route, the eval gate each route must pass, and automatic rollback when a live cut drifts below tolerance.
- **Budgets** sets hard caps per team, feature, or customer, and the engine throttles before a cap is breached rather than after.
- **Alerts** sets the thresholds that pull in a human and where they fire, on Slack or email. Everything below those thresholds the engine handles silently.

### Proof

The finance-facing section and the load-bearing one. Three tabs.

- **Savings** shows realized savings versus run-rate, and the month's full accounting: counterfactual spend, actual spend, the Varsten fee, and the net to the customer after the fee. This is the board-ready number.
- **Attribution** explains how each saved dollar is tied to a specific lever and action, shows the savings broken down by lever, and states the measurement method plainly enough to survive scrutiny.
- **Data quality** shows spend coverage, the trust score, and any gaps such as unmapped models or missing metadata, because if coverage drops the savings number is suspect and this is where a skeptic confirms it is not.

### Analysis

Deliberately demoted to a supporting section. It feeds decisions rather than being the destination. Three tabs.

- **Spend** breaks down drivers by team, feature, and provider.
- **Customers** shows per-customer revenue against AI cost and flags negative-margin customers. For an AI-native business this is the most valuable page in Analysis and the sharpest wedge in the whole product.
- **Models** shows cost, volume, and average cost per request by model, with cheaper-swap opportunities the engine has flagged.

### Admin

Setup, access, and the commercial relationship. Three tabs.

- **Connections** manages provider connections, SDK and ingestion setup, and model mappings. Read-only by default so a security team can approve it quickly.
- **Team** manages users, roles, and API keys, including narrow roles such as a Proof-only viewer for finance.
- **Billing & security** shows the plan, the verified-savings fee, the savings floor, and the security posture including SOC 2 status and data controls.

## How Varsten handles the hard CTO questions

A serious technical buyer will not adopt an inline cost tool on faith. These are the questions that decide the sale, and the product is designed so the answers are real, not marketing. Two architectural commitments do most of the work: a concurrent randomized holdback, and a thin in-VPC data plane split from the control plane.

### "Can you cut to cheaper models without degrading quality, and will your evals catch regressions on my workloads?"

Quality is a measurement loop, never a generic promise. Before a routing or downgrade change goes live on a route, Varsten replays a sample of that customer's own recent traffic through both the incumbent and the candidate and compares them on that route's real distribution, not on a public benchmark. Objective tasks are scored with objective signals such as classification accuracy and structured-output validity. Subjective generation is scored with pairwise judging calibrated against a customer-labeled seed set, and against the customer's own golden sets where they provide them. Implicit signals like retries, thumbs-down, and human escalation feed in too. Varsten only auto-applies where the signal is objective and trustworthy. For open-ended generation, where automatic judgment is too noisy to bet on, the change defaults to approve-mode with a human in the loop. The eval and replay harness is the real engineering of the product. Routing is a configuration change. Knowing the change is safe on traffic nobody has seen before is the actual work.

### "How do you separate your savings from what we would have done anyway, and from provider price changes?"

Varsten measures savings against a live randomized control, not a modeled counterfactual. For each optimizable route it holds back a small random share of traffic on the unoptimized original and optimizes the rest. Because assignment is random and concurrent, the holdback's cost per request is an unbiased estimate of what the optimized traffic would otherwise have cost, and the savings are the measured difference between the two arms. Anything the customer's own team changes during the period lands on both arms and cancels, so Varsten only ever claims its own delta. A provider price change hits both arms at the same time and cancels too, with no need to model it away. Savings are reported with confidence intervals rather than false precision, and the raw assignment and per-request costs are auditable. The held-back traffic costs a little because it stays unoptimized, so the holdback is kept small on high-volume routes and shown to the customer as an explicit line item. The same holdback doubles as the live baseline for quality drift, so one mechanism produces both the savings proof and the quality guarantee.

### "What does sitting in my request path do to latency?"

The only work Varsten does in the hot path is a policy lookup and a cache lookup, both sub-millisecond to low single-digit milliseconds. Everything expensive, including judging, evaluation, and the savings math, runs asynchronously off the path. Varsten never puts a model call or an LLM judge inline. The data plane can run as a sidecar or service inside the customer's own environment so the added hop is local rather than a round trip across the internet. A cache hit removes an entire model call and improves end-to-end latency. Because a cheaper model can be slower, latency is treated as a first-class guardrail with a per-route budget, and a cut that saves money but breaks the latency budget is rejected the same way a quality regression is.

### "What happens when Varsten is down?"

It fails open, always, and this is stated plainly in the product and the contract. The thin data plane in the request path is separated from the control plane and holds a local snapshot of the current routing policy, so if anything upstream is unreachable it passes the request straight through to the original provider with the original model. The customer stops saving money and gains roughly a millisecond. Production does not go down. The customer has a single kill switch that bypasses Varsten entirely, and the data plane ships with canary deploys and circuit breakers. The blast radius is bounded by design.

### "Do my prompts and completions leave my boundary?"

The customer chooses the deployment mode and the honest answer follows from it, described next.

## Deployment and security

Varsten offers two deployment modes.

In **metadata mode**, Varsten ingests only usage metadata such as token counts, model, route, and latency, drawn from provider billing APIs and lightweight instrumentation. Content never reaches Varsten. This mode powers Analysis, Proof, and recommendations, but not inline caching or content-based routing, since those require seeing the request.

In **inline gateway mode**, Varsten sees request content because caching and routing require it. The default and recommended deployment runs the data plane and the cache inside the customer's own cloud account, so content never leaves the customer's perimeter and only hashes, token counts, and eval scores flow back to Varsten's control plane. In that configuration the truthful answer to whether prompts leave the boundary is no, only counts and scores do, which turns security from a blocker into a selling point. Where a Varsten-hosted gateway is used instead, content is processed in memory and not persisted by default, with PII redaction before any logging, strict tenant isolation, and customer-managed encryption keys for the cache.

Varsten supplies the real artifacts a security review demands: a SOC 2 Type II report under NDA, a data processing agreement, a subprocessor list, a penetration test summary, and a clear data flow diagram. Roles are scoped, including a Proof-only viewer for finance, and access is audited.

## The measurement foundation

The savings number is only as trustworthy as the spend it is measured against, so Varsten is authoritative about cost rather than mirroring the customer's own math.

Varsten derives cost from a pricing catalog it owns and versions by effective date, resolving each event in order: a per-organization negotiated override first, then the global catalog, then the client-reported cost as a fallback, then unknown. It records which path produced each number and flags pricing trust issues such as a model missing from the catalog or missing token counts. Unknown cost is never treated as zero and unpriced events are never dropped, they are accepted and surfaced, because losing usage data is worse than honestly showing incomplete cost data. Prices live in data and are refreshed from a maintained source, never hard-coded, and historical prices are never overwritten so that past spend never silently changes.

Pricing trust and data quality are shown as first-class metrics, for example the share of spend that is catalog-priced versus client-reported versus unpriced, and the share of spend that is properly tagged. These are the numbers that let a customer believe the savings.

## Business value and customer margin

Varsten connects AI spend to business outcomes rather than treating all spend as waste to be cut. The goal is never to spend less at all costs. Some AI spend is profitable and drives retention, conversion, speed, or support deflection. The goal is to cut the waste and protect the value.

The clearest expression of this is customer-level AI margin: revenue per customer set against the AI cost to serve them, surfacing the customers whose AI cost exceeds what they pay. For an AI-native business this is existential, and it is the reason the Customers view in Analysis is the most valuable page in that section. Where a customer enriches their events with optional business signals such as plan, revenue, or business outcomes, Varsten can express spend as cost per outcome and feature-level return, but none of that enrichment is required for the core savings product to work.

## What success looks like

Before Varsten, the technical owner says: our AI bill is growing, I roughly know where, and bringing it down safely would mean pulling engineers onto a cost project nobody wants to own.

After Varsten, they say: our AI bill is lower, the engine cut it without touching quality, I approved the cuts I wanted to review and let it handle the rest, and I have a verified savings number, net of the fee, that I put in front of finance every month.

That is the product. Not a clearer picture of the problem. A smaller bill and the proof of it.

## North star

Varsten is the layer that makes AI spend go down and stays accountable for it. It is the system a company trusts to act on its AI costs, safely and continuously, and to prove every dollar it saved. A dashboard tells you what happened. Varsten changes what happens and shows you the difference.
