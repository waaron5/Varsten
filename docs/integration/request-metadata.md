# Passing request metadata to Varsten

Varsten sits between your application and your AI providers. Every request you
send through the Varsten proxy is metered, optimized, and recorded as structured
evidence. You can attach optional business and task context to each request so
that evidence is attributable to the workload that generated it.

You do not have to send any metadata. Without it, requests still work and are
still optimized. But sending it is strongly recommended: it is what lets Varsten
answer, per workload, "what is the cheapest reliable way to do this?" and report
savings broken down by feature, customer, and task type.

## The convention

Send a single JSON header, `X-Varsten-Metadata`, on the proxied request:

```
X-Varsten-Metadata: {"feature":"support_reply","workflow":"billing_support",
  "customer_id":"cust_123","external_user_id":"user_456","team":"support",
  "department":"customer_success","environment":"production",
  "task_type":"support_reply.billing","task_confidence":1.0,
  "risk_level":"medium","quality_threshold":"customer_safe"}
```

All fields are optional. Recognized fields:

| Field | Meaning |
|---|---|
| `feature` | The product feature making the call (e.g. `support_reply`). |
| `workflow` | The workflow or agent within that feature. |
| `customer_id` | Your end customer, for per-customer margin. |
| `external_user_id` | The end user. |
| `user_id` | An internal user id, if different. |
| `team` / `department` | Org allocation. |
| `environment` | `production`, `staging`, etc. Defaults to `production`. |
| `task_type` | What kind of task this is (see below). **Highly recommended.** |
| `task_confidence` | `0.0`–`1.0`, how sure you are of the task type. Clamped to range. |
| `risk_level` | `low` / `medium` / `high`, how costly a wrong answer is. |
| `quality_threshold` | A label for the quality bar, e.g. `customer_safe`. |

Any additional keys you include are preserved (bounded) as custom dimensions.

### Individual headers (fallback)

If your client cannot set a JSON header, send individual headers instead. They
override the JSON object when both are present:

```
X-Varsten-Feature: support_reply
X-Varsten-Workflow: billing_support
X-Varsten-Customer-Id: cust_123
X-Varsten-External-User-Id: user_456
X-Varsten-Team: support
X-Varsten-Department: customer_success
X-Varsten-Environment: production
X-Varsten-Task-Type: support_reply.billing
X-Varsten-Task-Confidence: 1.0
X-Varsten-Risk-Level: medium
X-Varsten-Quality-Threshold: customer_safe
```

### Why `task_type` matters

`task_type` is optional but the single most valuable field. It is the axis Varsten
optimizes along: routing, cheaper-model swaps, and savings analysis all get
sharper when requests are grouped by what they are actually doing
(`summarization`, `extraction`, `classification`, `support_reply.billing`, ...)
rather than just by which model was called. Use a stable, low-cardinality
namespace you control. You assign it; Varsten does not guess in this phase.

## Examples

### OpenAI-compatible SDK

Point the SDK's base URL at Varsten and authenticate with your Varsten `vk_` key.

```python
from openai import OpenAI

client = OpenAI(
    base_url="https://proxy.varsten.ai/v1",
    api_key="vk_live_...",  # your Varsten key, not your OpenAI key
    default_headers={
        "X-Varsten-Metadata": '{"feature":"support_reply","task_type":"support_reply.billing","customer_id":"cust_123"}'
    },
)

resp = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "How do I update my billing address?"}],
)
```

### Anthropic-compatible SDK

Anthropic SDKs send the key as `x-api-key`; put your Varsten `vk_` key there.

```python
from anthropic import Anthropic

client = Anthropic(
    base_url="https://proxy.varsten.ai",
    api_key="vk_live_...",
    default_headers={
        "X-Varsten-Metadata": '{"feature":"contract_review","task_type":"extraction","risk_level":"high"}'
    },
)

resp = client.messages.create(
    model="claude-3-5-sonnet-latest",
    max_tokens=512,
    messages=[{"role": "user", "content": "Extract the parties and term."}],
)
```

### Gemini-compatible request

Gemini's native SDK sends `x-goog-api-key`; use your Varsten `vk_` key. Set the
metadata header the same way.

```
POST https://proxy.varsten.ai/v1beta/models/gemini-2.0-flash:generateContent
x-goog-api-key: vk_live_...
X-Varsten-Metadata: {"feature":"data_analysis","task_type":"summarization"}
```

## Correlating feedback later

Every proxied response includes an `X-Varsten-Request-Id` header. Capture it if
you want to report later how the output performed (see `POST /v1/feedback`):

```python
resp = client.chat.completions.with_raw_response.create(...)
request_id = resp.headers["x-varsten-request-id"]
```

Then, when you know the outcome:

```
POST https://proxy.varsten.ai/v1/feedback
Authorization: Bearer vk_live_...
{"request_id": "<the id>", "outcome": "accepted", "quality_score": 0.9}
```

`outcome` is one of `accepted`, `rejected`, `edited`, `regenerated`, `escalated`,
`overridden`. You may key on `request_id` or on a `usage_event_id`; at least one
is required. A key may only attach feedback to its own project's requests.

## Privacy posture

- **Request metadata is stored.** The fields above are recorded against each
  request as structured evidence (the `usage_events` ledger and the
  `request_decision_events` evidence trail). This is metadata, not content.
- **Prompt and completion content is not stored** in the usage ledger or the
  decision evidence. Content storage is limited to the semantic cache and the
  eval replay corpus, each opt-in and governed by its own retention settings.
- **Malformed or oversized metadata is ignored, never fatal.** A bad
  `X-Varsten-Metadata` header is dropped and your request proceeds normally.
- **Varsten headers are never forwarded upstream.** `X-Varsten-*` headers are
  consumed by the proxy and stripped before the request reaches the AI provider.
