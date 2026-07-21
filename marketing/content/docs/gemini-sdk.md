---
title: Gemini SDK
description: Integrate Google Gen AI through the Varsten beta wrapper with conservative direct-to-provider fallback.
slug: gemini-sdk
category: SDKs
order: 22
updatedAt: 2026-07-21
---
## Status

The Gemini wrapper is version 0.1.0 beta and intended for founder-supervised pilots. It supports `generateContent` and `generateContentStream`. Validate the exact model and request features used by your workload.

## Install

```bash
npm install @varsten/gemini @google/genai
```

Node.js 18 or newer and ESM are required.

## Create the client

```ts
import { VarstenGemini } from "@varsten/gemini";

const client = new VarstenGemini({
  varstenApiKey: process.env.VARSTEN_API_KEY,
  geminiApiKey: process.env.GEMINI_API_KEY,
  onFallback: (event) => console.warn("varsten fallback", event.reasonCode),
});

const response = await client.models.generateContent({
  model: "gemini-3.1-flash-lite",
  contents: "Hello",
});
```

The Gemini key remains local and is used only for direct fallback.

## Conservative fallback

Gemini provider errors do not always expose response headers. The wrapper retries only transport failures and errors positively identified as Varsten-originated. An unattributed provider-like error is surfaced to avoid duplicate billing.
