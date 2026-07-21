---
title: Request metadata
description: Attach content-free workload labels and trace IDs so Varsten can allocate spend and analyze agent workflows.
slug: request-metadata
category: Integration modes
order: 35
updatedAt: 2026-07-21
---
## What metadata is for

Request metadata tells Varsten which product feature, team, customer, environment, or workflow generated a call. These labels power allocation and task-aware analysis.

## OpenAI wrapper example

```ts
import { VarstenTrace } from "@varsten/openai";

const trace = new VarstenTrace();

await client.chat.completions.create(body, {
  varsten: trace.metadata({
    feature: "research_agent",
    team: "product",
    taskType: "research.step",
    riskLevel: "medium",
  }),
});
```

Supported labels include trace, feature, workflow, customer, external user, team, department, environment, task type, risk level, and quality threshold.

## Content boundary

Metadata values must be short labels or identifiers. Never put prompts, completions, provider keys, access tokens, customer content, or other secrets in metadata.
