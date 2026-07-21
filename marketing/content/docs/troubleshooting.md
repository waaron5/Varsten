---
title: Troubleshooting
description: Diagnose authentication, provider connection, pricing coverage, fallback, and first-request problems.
slug: troubleshooting
category: Reliability
order: 75
updatedAt: 2026-07-21
---
## No traffic appears

Confirm that the application uses the intended `vk_` project key and Varsten base URL. Send one non-sensitive staging request, then verify that the response carries the Varsten diagnostic marker.

## Authentication fails

A `401` usually means the Varsten key is missing, invalid, or revoked. Confirm that the server process—not browser code—has the expected environment variable.

## Provider connection fails

For base URL mode, confirm that the provider connection is configured in the Varsten application. For an SDK wrapper, confirm that the local provider key exists if direct fallback is required.

## Cost is missing

Check the provider and model spelling and send complete token counts. An unknown model can be recorded but may show incomplete pricing coverage until its price is available.

## Fallback does not occur

The SDK does not retry provider-origin errors, deliberate budget caps, invalid requests, or mid-stream failures. Read timeouts also do not fall back by default because the provider may already have billed the first attempt.

## Still blocked

Send the provider, SDK package/version, approximate timestamp, and non-sensitive error code to support@varsten.ai. Do not send API keys, prompts, completions, or customer content.
