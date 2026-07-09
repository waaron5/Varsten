---
title: API reference
description: Reference the public metadata event shape, common headers, idempotency behavior, and safe attribution fields for Varsten integrations.
slug: api-reference
category: Reference
order: 100
updatedAt: 2026-07-09
---
## Authentication

Send a Varsten API key in the `Authorization` header.

```http
Authorization: Bearer vk_...
Content-Type: application/json
```

## Usage events

```http
POST /v1/usage-events
```

```json
{
  "provider": "openai",
  "model": "gpt-4o-mini",
  "request_type": "chat_completion",
  "input_tokens": 1200,
  "output_tokens": 340,
  "feature": "support_agent",
  "environment": "production",
  "idempotency_key": "req_123",
  "occurred_at": "2026-07-09T13:00:00.000Z"
}
```

## Idempotency

Use an idempotency key for usage-event retries. Retries should never double-count cost or savings inputs.

## Safe attribution fields

Use team, feature, environment, provider, model, route, and request type. Do not send prompts, completions, customer content, provider keys, or secrets.
