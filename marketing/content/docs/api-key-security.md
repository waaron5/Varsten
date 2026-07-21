---
title: API keys and provider keys
description: Understand the separate roles of Varsten project keys and provider credentials across SDK and base URL integrations.
slug: api-key-security
category: Security
order: 81
updatedAt: 2026-07-21
---
## Two different credentials

A `vk_` project key authenticates your application to Varsten. A provider key authenticates calls to OpenAI, Anthropic, or Gemini. Never expose either credential in browser code, logs, analytics, URLs, or support forms.

## Production SDK path

With a Varsten SDK wrapper, the provider key remains in your application and is used for direct fallback. The optimized attempt uses the Varsten key. Workflow metadata is not sent to the provider during fallback.

## Base URL evaluation path

With the base URL path, Varsten must have a connected provider credential to forward requests. This is a different custody model from the SDK path and should be reviewed before sending sensitive traffic.

## Rotation

Create a replacement credential, deploy it, verify traffic, and then revoke the old credential. Treat a displayed `vk_` value as a secret; project keys are shown only at creation time in the application.

## If a key is exposed

Revoke it immediately, replace it everywhere it is used, and review traffic and audit records for unexpected activity. Contact security@varsten.ai for a suspected Varsten-related incident.
