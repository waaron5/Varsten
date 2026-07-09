---
title: Data handling
description: Review how Varsten separates metadata ledgers from bounded content stores and how teams should choose retention policies.
slug: data-handling
category: Security
order: 80
updatedAt: 2026-07-09
---
## Ledger data

Varsten's savings ledger is metadata-oriented. It records enough information to explain cost, attribution, optimization decisions, and proof without treating prompt and completion text as the default record.

## Content boundaries

Content can exist only where a configured feature needs it, such as semantic cache, replay corpus, or batch staging. Those stores should be bounded and governed by route policy.

## What not to send

Do not put provider keys, prompt text, completion text, customer content, or secrets into request metadata, analytics events, lead forms, or URL parameters.

## Enterprise review

For stricter environments, review retention, access, subprocessors, DPA terms, and deployment boundaries before moving production traffic inline.
