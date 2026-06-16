# Varsten Data Handling and Retention

Customer-facing reference for what Varsten stores, where, and for how long. This
describes the system as built; it is the document a customer security review
should be handed alongside the security posture page.

## The one principle

The usage ledger is **metadata only**. Prompt and completion text are never
written to it. The single, deliberate exception is the semantic cache, which by
definition must store a response in order to serve it. Everything below follows
from that.

## What is stored, where, and how long

| Data | Contains content? | Store | Retention |
|---|---|---|---|
| Usage ledger (`usage_events`) | No — token counts, model, latency, derived cost, allocation tags | Postgres | Retained as the system of record. No prompt/response text. |
| Semantic cache (`proxy_cache_entries`) | **Yes** — the stored response, served on a hit | Postgres | TTL'd. Each entry carries an `expires_at` set on write (default 7 days, configurable via `PROXY_CACHE_TTL_SECONDS`). Expired entries are skipped by lookups and deleted by a purge sweep. |
| Replay samples (eval harness) | Yes — sampled real traffic, opt-in | Postgres | TTL'd (`EVAL_SAMPLE_TTL_DAYS`, default 14). Off by default; double-gated by a global setting and a per-project opt-in. Golden samples you supply never expire. |
| Batch objects | Yes — the `.jsonl` you submit | Object storage (S3 in prod) | TTL'd (`BATCH_OBJECT_TTL_HOURS`, default 72): a scheduled sweep deletes the input/output objects from storage past their deadline (`objects_purged_at` marks the row). Never held in the API's memory; streamed via pre-signed URLs. |
| Provider API keys | N/A (a secret) | AWS Secrets Manager, one secret per project/provider, KMS-encrypted | Lives until you disconnect; deletion removes the secret. |
| Audit log (`audit_events`) | No — actor, action, target, before/after tier; never secret values | Postgres | Append-only record of plan changes and provider-key custody actions. |
| Errors (Sentry) | No | Sentry | Request headers, cookies, and bodies are never attached (`send_default_pii=False`). |

## Content stores are the exception, and they are bounded

There are exactly three places content can live, all opt-in or intrinsic to a
feature you turn on, all time-bounded:

1. **Semantic cache** — only when caching is enabled. Stores the response so an
   identical/near-identical later request is served without calling the provider.
   Per-entry `expires_at`; a scheduled purge deletes lapsed entries.
2. **Replay corpus** — only when the eval harness is enabled *and* the project
   opts in. Samples a fraction of traffic to prove a cheaper-model swap is safe.
   TTL'd; capped per route.
3. **Batch staging** — the file you submit to the batch endpoint, in your object
   store, TTL'd in hours.

If none of these are enabled, no content is stored anywhere.

## Provider key custody (summary)

Provider keys are stored in AWS Secrets Manager, one secret per
project/provider (`varsten/<env>/provider-keys/<project_id>/<provider>`),
KMS-encrypted. The data plane's IAM role can read only its environment's secrets
and decrypt via KMS; it cannot read another environment's. Keys are validated with
a cheap probe before they are stored, decrypted into a short-TTL in-process cache
on the hot path (never read from Secrets Manager per request), and removed on
disconnect. Connecting and disconnecting a key is recorded in the audit log
(that it happened, never the value). Full detail: `provider-key-vaulting.md`.

## Tenant isolation

Every authorization walks `user → organization membership → organization`, and
all tenant data hangs off `organization → project`. API keys resolve directly to
their project. A request can only ever read or write its own tenant's data.

## Deletion

Disconnecting a provider deletes its secret. Cache and replay content age out on
their TTLs; a customer-initiated purge of cache content for a project can be run
on request. Per-org customer-managed retention windows and customer-managed
encryption keys for the cache are on the roadmap and tracked in the security plan.

## What we will tell you plainly

- Do your prompts leave your boundary? In the current hosted deployment, content
  is processed in-memory and only stored in the bounded content stores above when
  you enable the corresponding feature. The in-VPC deployment (roadmap) keeps
  content entirely in your cloud account, with only counts and scores flowing to
  the control plane.
- Is any of this sold or used to train models? No.
