---
title: OpenAI SDK
description: Integrate Varsten with OpenAI-compatible chat completion traffic while keeping the provider key available for direct fallback.
slug: openai-sdk
category: SDKs
order: 20
updatedAt: 2026-07-09
---
## Production path

The OpenAI wrapper is the recommended production path today. It keeps your call shape close to the official SDK while allowing Varsten to meter, optimize, and fall back.

## Constructor

```ts
import { VarstenOpenAI } from "@varsten/openai";

export const ai = new VarstenOpenAI({
  varstenApiKey: process.env.VARSTEN_API_KEY,
  openaiApiKey: process.env.OPENAI_API_KEY,
  timeoutMs: 15_000,
  onFallback: (event) => {
    logger.warn({ reason: event.reasonCode }, "Varsten fallback");
  },
});
```

## Request labels

Add labels that help finance and engineering understand savings by workload. Do not put customer content, prompt text, or secrets in metadata.

```ts
await ai.chat.completions.create({
  model: "gpt-4o-mini",
  messages,
  metadata: {
    team: "support",
    feature: "ticket_draft",
    environment: "production",
  },
});
```

## Streaming

Streaming can fall back before output starts. Once tokens are flowing, a mid-stream provider or network error is surfaced to the caller instead of silently restarting the request and risking duplicate output.
