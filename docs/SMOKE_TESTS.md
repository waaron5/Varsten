# Smoke Tests: Manual and Production

How to prove a Varsten deployment actually works end to end, before and after
routing a customer's traffic through it. Two layers: a live SDK suite (per
provider, using the official SDKs) and a fast production curl sequence.

## 1. Live SDK smoke suite

Exercises the official OpenAI, Anthropic, and `google-genai` SDKs against a
running Varsten server, reaching the real upstream providers. Opt-in: it is
skipped unless `VARSTEN_SDK_SMOKE=1`.

Prereqs:
- A running Varsten API (local or deployed) reachable at the base URL.
- A Varsten `vk_` API key for a project with upstream provider keys connected.
- The official SDKs installed (`openai`, `anthropic`, `google-genai`).

```bash
export VARSTEN_SDK_SMOKE=1
export VARSTEN_SDK_SMOKE_BASE_URL="https://<api-host>"   # default http://127.0.0.1:8000
export VARSTEN_SDK_SMOKE_API_KEY="vk_..."
# Optional model overrides:
# export VARSTEN_SDK_SMOKE_OPENAI_MODEL=gpt-4o-mini
# export VARSTEN_SDK_SMOKE_ANTHROPIC_MODEL=claude-3-5-haiku-20241022
# export VARSTEN_SDK_SMOKE_GEMINI_MODEL=gemini-2.5-flash

make backend-sdk-smoke
```

Each provider test does a non-streaming completion and a streaming completion and
asserts non-empty output. Run it per provider before enabling that provider for a
customer. A provider whose SDK smoke does not pass is not ready for that customer.

## 2. Production curl smoke (no SDKs required)

A 60-second sequence to run against a freshly deployed environment. Replace
`$HOST` and `$VK`.

```bash
HOST="https://<api-host>"; VK="vk_..."

# Liveness + readiness (readiness must show the DB reachable).
curl -fsS "$HOST/health"        # {"ok":true}
curl -fsS "$HOST/health/ready"  # {"ok":true,"database":"ok"}

# A real non-streaming completion (OpenAI dialect).
curl -fsS "$HOST/v1/chat/completions" \
  -H "Authorization: Bearer $VK" -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"ping"}]}' \
  -i | grep -i 'x-varsten-\|HTTP/'   # expect 200 + X-Varsten-Mode / X-Varsten-Cache

# A streaming completion (expect SSE chunks then [DONE]).
curl -fsS -N "$HOST/v1/chat/completions" \
  -H "Authorization: Bearer $VK" -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"count to 3"}],"stream":true}'

# A cache hit: send the identical request again, expect X-Varsten-Cache: hit.
curl -fsS "$HOST/v1/chat/completions" \
  -H "Authorization: Bearer $VK" -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"ping"}]}' \
  -i | grep -i 'x-varsten-cache'      # expect: miss first time, hit second time

# Negative checks (prove the guardrails):
# - bad key -> 401
curl -s -o /dev/null -w "%{http_code}\n" "$HOST/v1/chat/completions" \
  -H "Authorization: Bearer vk_not_a_real_key" -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o-mini","messages":[]}'   # expect 401
```

Pass criteria:
- `/health/ready` reports the database reachable.
- A real completion returns `200` with `X-Varsten-*` headers.
- The second identical request reports `X-Varsten-Cache: hit`.
- A streaming request returns SSE chunks ending in `[DONE]`.
- A bad key returns `401`.

## 3. Failure-mode spot checks (optional, staging only)

Validate the failure matrix against a staging instance (never production):
- Toggle the project bypass and confirm `X-Varsten-Mode: bypass`.
- Set `PROXY_KILL_SWITCH=true` and confirm all traffic forwards, still metered.
- Point the project at a deliberately bad upstream key and confirm a clean `502`
  (`varsten_upstream_error`), not a hang or a stack trace.

See `FAILURE_MODES.md` for the full expected behavior; the same matrix is asserted
in `backend/tests/test_proxy.py` so the deployed behavior matches the tested one.

## First-customer rollout gate

Do not route a customer's production traffic until: the SDK smoke passes for their
provider, the production curl smoke passes against the deployed environment, and a
tested database restore exists (see `OPERATIONS_DEPLOY.md`).
