---
title: API reference
description: Reference the public metadata event shape, common headers, idempotency behavior, and safe attribution fields for Varsten integrations.
slug: api-reference
category: Reference
order: 100
updatedAt: 2026-07-21
---
## Base URL

Control-plane endpoints use `https://api.varsten.ai/v1`.

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

Required fields are `provider` and `model`. Token counts default to zero, but meaningful cost reporting requires the applicable input and output counts. Only USD is accepted in version 1.

Useful optional fields include `request_type`, `feature`, `team`, `department`, `customer_id`, `user_id`, `environment`, `cached_input_tokens`, `reasoning_tokens`, `cost_usd`, `status`, `error_code`, `latency_ms`, `occurred_at`, and `metadata`.

The endpoint returns `201 Created` for a new event. A retry with an existing project-scoped idempotency key returns the stored event with `200 OK`.

## List usage events

```http
GET /v1/usage-events?limit=50&offset=0
```

Supported filters include provider, model, workflow, feature, customer, user, team, environment, request type, and start/end timestamps. `limit` accepts 1 through 100. Responses contain `items`, `limit`, `offset`, and `has_more`.

## Idempotency

Use an idempotency key for usage-event retries. Retries should never double-count cost or savings inputs.

## Common errors

- `401`: missing, invalid, or revoked Varsten API key.
- `422`: invalid fields, unsupported currency, or malformed values.
- `429`: request rate limited. Retry metadata ingestion with backoff and the same idempotency key.
- `5xx`: temporary Varsten failure. Retry metadata ingestion with backoff and the same idempotency key.

## Safe attribution fields

Use team, feature, environment, provider, model, route, and request type. Do not send prompts, completions, customer content, provider keys, or secrets.
