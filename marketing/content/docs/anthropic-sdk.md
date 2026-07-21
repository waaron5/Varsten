---
title: Anthropic SDK
description: Integrate Anthropic Messages through the Varsten beta wrapper with direct-to-provider fallback before output starts.
slug: anthropic-sdk
category: SDKs
order: 21
updatedAt: 2026-07-21
---
## Status

The Anthropic wrapper is version 0.1.0 beta and intended for founder-supervised pilots. It supports streaming and non-streaming Messages. Test tools, beta headers, and workload-specific options before production rollout.

## Install

```bash
npm install @varsten/anthropic @anthropic-ai/sdk
```

Node.js 18 or newer and ESM are required.

## Create the client

```ts
import { VarstenAnthropic } from "@varsten/anthropic";

const client = new VarstenAnthropic({
  varstenApiKey: process.env.VARSTEN_API_KEY,
  anthropicApiKey: process.env.ANTHROPIC_API_KEY,
  onFallback: (event) => console.warn("varsten fallback", event.reasonCode),
});

const response = await client.messages.create({
  model: "claude-haiku-4-5-20251001",
  max_tokens: 256,
  messages: [{ role: "user", content: "Hello" }],
});
```

The Varsten key is sent only to Varsten. The Anthropic key stays in your application and is used by the direct fallback path.

## Fallback boundary

The wrapper falls back for positively identified Varsten or transport failures before output starts. Relayed provider errors, deliberate budget caps, and mid-stream failures are surfaced instead of retried.
