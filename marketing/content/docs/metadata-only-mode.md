---
title: Direct Monitoring
description: Send token counts, model names, and workload labels to Varsten without placing Varsten in the request path.
slug: metadata-only-mode
category: Integration modes
order: 30
updatedAt: 2026-07-09
---
## Lowest-risk start

Direct Monitoring automatically sends usage records after provider calls. Nothing sits inline, so this path has no availability risk and cannot apply optimization levers.

## What to send

Send cost-relevant metadata such as provider, model, token counts, timestamps, and workload labels. Do not send prompt text, completions, provider keys, or customer content.

```ts
await fetch("https://api.varsten.ai/v1/usage-events", {
  method: "POST",
  headers: {
    Authorization: `Bearer ${process.env.VARSTEN_API_KEY}`,
    "Content-Type": "application/json",
  },
  body: JSON.stringify({
    provider: "openai",
    model: "gpt-4o-mini",
    request_type: "chat_completion",
    input_tokens: usage.prompt_tokens,
    output_tokens: usage.completion_tokens,
    feature: "support_agent",
    environment: "production",
    idempotency_key: requestId,
    occurred_at: new Date().toISOString(),
  }),
});
```

## What you get

You get spend visibility, workload attribution, pricing coverage checks, and savings analysis. Turning on optimization later requires an inline path such as the SDK.
