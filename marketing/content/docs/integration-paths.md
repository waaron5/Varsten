---
title: Integration paths
description: Compare SDK, base URL, and metadata-only integration paths so each workload starts with the right risk posture.
slug: integration-paths
category: Architecture
order: 50
updatedAt: 2026-07-09
---
## Choose the path by workload risk

Varsten supports three integration styles. Pick the one that matches the workload's availability and optimization needs.

## SDK path

The SDK is the production path. It keeps Varsten inline for healthy traffic and keeps the provider key local for direct fallback when Varsten is unavailable.

## Base URL path

Base URL mode is useful for quick evaluations. It does not provide the SDK's direct provider fallback.

## Metadata-only path

Metadata-only mode is analysis-only. It gives visibility and proof inputs without inline optimization.

## Planned: in-VPC sidecar

A sidecar data plane that runs inside your own cloud boundary is designed but not yet available. Prompt and completion content would never leave your VPC; only token counts and scores would reach the Varsten control plane. If this is your required deployment model, contact us — demand moves it up the roadmap.

## Practical rollout order

1. Start with metadata-only or base URL mode if the team needs visibility first.
2. Move one stable OpenAI workload to the SDK path.
3. Enable optimization levers only after pricing coverage and fallback behavior are verified.
