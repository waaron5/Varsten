---
title: Provider compatibility
description: Understand Varsten provider support across OpenAI, Anthropic, and Gemini before choosing a rollout path.
slug: provider-compatibility
category: Architecture
order: 60
updatedAt: 2026-07-09
---
## Current recommendation

OpenAI is the production-recommended path for a first Varsten rollout.

## Provider status

- **OpenAI:** GA for controlled production rollout.
- **Anthropic:** beta and founder-supervised pilot.
- **Gemini:** beta and founder-supervised pilot.

## Why this matters

Savings proof, fallback behavior, pricing coverage, and request compatibility vary by provider. The safest rollout starts with the provider path that has the strongest current support, then expands after measurement and fallback checks are clean.

## Multi-provider accounts

Use workload labels so spend and savings stay attributable by team, feature, provider, model, and environment.
