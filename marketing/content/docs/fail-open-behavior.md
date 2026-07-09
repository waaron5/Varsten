---
title: Fail-open behavior
description: Learn when Varsten SDK fallback calls the provider directly and when provider-origin errors are returned as-is.
slug: fail-open-behavior
category: Reliability
order: 70
updatedAt: 2026-07-09
---
## What falls back

The SDK can call the provider directly when Varsten is unavailable before output starts. Examples include DNS failures, connection failures, Varsten-origin 5xx errors, Varsten rate limits, and local circuit-breaker bypass.

## What does not fall back

If the provider returns an error and Varsten relays it, the SDK returns that provider error. Retrying direct would usually double bill or hit the same provider-side problem.

## Streaming

Streaming can fall back before tokens start. Once output is flowing, a mid-stream error is surfaced instead of silently restarting the request.

## Test before rollout

```bash
VARSTEN_BASE_URL=http://127.0.0.1:1 npm run your-ai-test
```

Run this only outside production. Your request should still complete through the provider and your fallback log should record the reason code.
