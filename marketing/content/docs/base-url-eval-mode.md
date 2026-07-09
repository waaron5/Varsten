---
title: Base URL eval mode
description: Use an OpenAI-compatible base URL change for low-risk evaluation traffic before installing the SDK fallback path.
slug: base-url-eval-mode
category: Integration modes
order: 40
updatedAt: 2026-07-09
---
## Evaluation path

Base URL mode points an OpenAI-compatible client at Varsten. It is useful for low-risk evaluations, traffic checks, and demo workloads.

```ts
import OpenAI from "openai";

const client = new OpenAI({
  apiKey: process.env.VARSTEN_API_KEY,
  baseURL: "https://api.varsten.ai/v1",
});
```

## Important boundary

Base URL mode does not provide direct-to-provider fallback if Varsten is unavailable. Use the production SDK path for workloads that need local provider fallback.

## Good fits

- A staging route with representative prompts.
- A low-risk internal tool.
- A temporary evaluation that checks attribution and pricing coverage.
