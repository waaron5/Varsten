> **Historical, fully executed.** This directive kicked off the inline-proxy build. Every item below is now shipped: the proxy pipeline, zero-retention ledger, and all five levers named here refactored into live execution modules (plus a sixth, prompt compression, added after this was written — see `app/levers.py`). Kept as a record of original intent, not a current to-do list. For what's actually built and what's still open, read `CLAUDE.md` and `docs/design/ENGINE_IMPLEMENTATION_PLAN.md`.

### SYSTEM ARCHITECTURE & PRODUCT DIRECTIVE: THE VARSTEN OPTIMIZATION ENGINE

We are building Varsten: an enterprise-grade AI FinOps optimization engine targeting mid-market B2B SaaS and AI Agent platforms spending $5k–$50k/month on LLMs. 

Do not build a passive post-hoc diagnostic dashboard. Varsten must operate as an inline, low-latency Smart Proxy Gateway that programmatically intercept, alters, and optimizes live traffic to mathematically guarantee a 40%–70% cost reduction via a gain-share business model.

Implement the following core product specs and inner mechanics:

1. THE INLINE PROXY PIPELINE (The Heart of Varsten)
- Expose mirror routes for major providers (e.g., `POST /v1/chat/completions` for OpenAI).
- Authenticate incoming requests using our custom `vk_...` API key schema to resolve the project's tenancy state.
- Intercept the request body, evaluate active optimization levers, modify the payload JSON programmatically, swap out the Varsten key for the customer's securely vaulted provider key, and forward to the target LLM.
- Stream responses back to the client natively using streaming protocols (e.g., FastAPI's StreamingResponse) to preserve sub-10ms routing overhead. Capture token/billing metadata asynchronously from the stream to populate the database ledger without blocking the client.

2. SYSTEM OF RECORD & ZERO-RETENTION SECURITY
- Maintain absolute database financial integrity using Numeric(20,12) for versioned pricing. 
- Enforce a strict Zero-Retention Policy: Prompt payloads and completion text must pass through volatile memory only and never be written to disk. The database must only log metadata facts (token counts, latencies, derived costs, allocation tags).

3. THE FIVE CORE OPTIMIZATION LEVERS (Inline Execution)
Refactor our 5 levers from "diagnostic detectors" into "active execution modules" inside the proxy routing path:
- Semantic Cache: Intercept repeating requests at the proxy layer, returning vector-matched responses in under 15ms at $0 cost, bypassing the LLM provider entirely.
- Token Trim & Advanced Prompt Caching: Identify high input-to-output context ratios ($\ge 8$). Dynamically restructure prompt layouts at the wire level to maximize provider-level prompt prefix caching (targeting 50-90% input discounts).
- Smart Routing & Model Downshift: Analyze target routes. Automatically downgrade routine tasks (e.g., basic classification) to lower-cost tiers (e.g., GPT-4o-mini, Gemini Flash) while preserving frontier models strictly for complex reasoning.
- Batching: Intercept payloads flagged as non-real-time or background tasks and automatically divert them to providers' async batch endpoints for a flat 50% pricing cut.

4. WRITING THE HIGH-ROI LEDGER
- The recommendation loop (`refresh_recommendations()`) must be completely decoupled from the ingestion write path. Move it to an async, debounced background worker process.
- The dashboard must act as an authoritative financial ledger, displaying a real-time comparison of "Naive Retail Cost" vs "Varsten Optimized Cost". This delta is what proves our ROI and drives our gain-share billings.
