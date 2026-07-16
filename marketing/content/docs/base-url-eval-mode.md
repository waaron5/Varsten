---
title: Base URL eval mode
description: Use an OpenAI-compatible base URL change for low-risk evaluation traffic before installing the SDK fallback path.
slug: base-url-eval-mode
category: Integration modes
order: 40
updatedAt: 2026-07-09
---
## Evaluation path

Base URL mode points an official provider SDK at Varsten. It is useful for low-risk evaluations, traffic checks, and demo workloads. Your Varsten `vk_` key replaces the provider key in the client; the real provider key stays vaulted with Varsten.

```ts
import OpenAI from "openai";

const client = new OpenAI({
  apiKey: process.env.VARSTEN_API_KEY,
  baseURL: "https://api.varsten.ai/v1",
});
```

```python
import os
from openai import OpenAI

client = OpenAI(
    api_key=os.environ["VARSTEN_API_KEY"],
    base_url="https://api.varsten.ai/v1",
)
```

## Base URL per provider

Each official SDK appends its own version segment, so the base URL differs per provider:

| Provider SDK | Base URL |
| --- | --- |
| OpenAI | `https://api.varsten.ai/v1` |
| Anthropic | `https://api.varsten.ai` (no `/v1` — the SDK appends `/v1/messages`) |
| Gemini (`google-genai`) | `https://api.varsten.ai` with `api_version: "v1beta"` |

The in-app setup at app.varsten.ai generates the exact client construction for your provider and language.

## Important boundary

Base URL mode does not provide direct-to-provider fallback if Varsten is unavailable. Use the production SDK path for workloads that need local provider fallback.

## Good fits

- A staging route with representative prompts.
- A low-risk internal tool.
- A temporary evaluation that checks attribution and pricing coverage.
