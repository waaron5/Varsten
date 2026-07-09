---
title: Quickstart
description: Route one OpenAI workload through Varsten with SDK fail-open fallback and verify that traffic still completes if Varsten is unavailable.
slug: quickstart
category: Start
order: 10
updatedAt: 2026-07-09
---
## Start with one route

Use one stable OpenAI route, job, or service for the first rollout. Do not rewrite prompts, request bodies, streaming loops, or tool handling while you are proving the integration.

## Install

```bash
npm install @varsten/openai openai
```

## Configure keys

Keep your provider key in the application. Varsten uses its own key for the optimized path, and the local provider key remains available for direct fallback.

```bash
VARSTEN_API_KEY=vk_...
OPENAI_API_KEY=sk-...
VARSTEN_BASE_URL=https://api.varsten.ai/v1
```

## Replace the client constructor

```ts
import { VarstenOpenAI } from "@varsten/openai";

const client = new VarstenOpenAI({
  varstenApiKey: process.env.VARSTEN_API_KEY,
  openaiApiKey: process.env.OPENAI_API_KEY,
  onFallback: (event) => {
    console.warn("varsten fallback", event.reasonCode);
  },
});

const response = await client.chat.completions.create({
  model: "gpt-4o-mini",
  messages,
});
```

## Verify

Run one development or staging request and check the Varsten marker. It is attached to the response for diagnostics and should not be serialized to users.

```ts
console.log(response._varsten?.servedBy);
// "varsten" or "provider-fallback"
```

## Test fallback

Point `VARSTEN_BASE_URL` at a dead local port in a non-production shell. The request should complete through your provider if the provider key is configured.

```bash
VARSTEN_BASE_URL=http://127.0.0.1:1 npm run your-ai-test
```
