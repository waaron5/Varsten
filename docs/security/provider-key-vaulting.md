# Provider key vaulting: migration to AWS Secrets Manager

Status: planned. This documents the path from today's interim key storage to a
KMS-backed vault, so a security reviewer can see a concrete, credible plan even
though the implementation is deferred.

## Today (interim, Phase 1)

A client's upstream provider key (e.g. their OpenAI `sk-...`) is supplied to the
backend as a JSON env var, `PROXY_OPENAI_KEYS`, mapping `project_id -> key`:

```json
{"<project-uuid>": "sk-..."}
```

It is read in `app/proxy/keys.py` (`openai_key_for_project`) off `settings.proxy_openai_keys`.

Properties of the interim approach:

- Keys live in the platform's env/secret store (App Runner config / Secrets Manager
  reference), never in the repo, never returned to clients, never logged, never
  written to the ledger (audited).
- Resolution is a dict lookup: zero latency, no new dependency on the hot path.

Limitations a CTO will (correctly) flag:

- **Onboarding a client requires a redeploy** (env change), which does not scale
  past a handful of tenants.
- **All tenant keys are co-resident in one process env**, so the blast radius of a
  process compromise is every client's key.
- **No per-key rotation, versioning, or audited access** independent of deploys.
- **No per-tenant encryption boundary.**

## Target: AWS Secrets Manager (KMS-backed)

### Storage layout

One secret per `(project_id, provider)`, namespaced:

```
varsten/<env>/provider-keys/<project_id>/<provider>   ->  {"api_key": "sk-..."}
```

- Encrypted at rest with a **customer-scoped KMS key** (one CMK per tenant for
  enterprise tiers; a shared CMK for self-serve), enabling per-tenant key policies
  and crypto-shredding on offboarding.
- Versioned by Secrets Manager (`AWSCURRENT` / `AWSPREVIOUS`) so rotation is
  atomic and reversible.

### Code seam

`app/proxy/keys.py` already isolates resolution behind one function. The migration
is additive behind that seam:

```python
# app/proxy/keys.py  (target)
async def provider_key_for(project_id: uuid.UUID, provider: str) -> str | None:
    return await _key_resolver.get(project_id, provider)
```

- A `KeyResolver` interface with two implementations: `EnvKeyResolver` (today) and
  `SecretsManagerKeyResolver` (target), selected by a `provider_key_backend`
  setting. This mirrors the provider-adapter registry pattern already in the
  codebase, so swapping backends is config, not a rewrite.
- The proxy calls `provider_key_for(project.id, adapter.provider)` instead of
  `openai_key_for_project(project.id)`, making key resolution provider-aware (it is
  OpenAI-only today).

### Hot-path latency

A Secrets Manager `GetSecretValue` call is ~10-30ms — unacceptable on every
request. Mitigation:

- **In-process TTL cache** (the same `cachetools.TTLCache` pattern now used for
  pricing), keyed by `(project_id, provider)`, short TTL (e.g. 5 min). First
  request for a tenant pays the fetch; subsequent ones are in-memory.
- **Decrypt cache** via the AWS SDK is also available; the TTL cache is the primary
  control.
- Cache is invalidated on rotation (below), so a rotated key takes effect promptly.

### Rotation

- Secrets Manager rotation schedule (or manual rotate) writes a new version.
- An **EventBridge rule on `SecretsManager` rotation events** publishes to the app
  (SNS/webhook) which calls `clear_provider_key_cache(project_id, provider)`,
  matching the `clear_price_cache()` invalidation hook already in pricing.
- Fail-open on resolution error stays the rule: if the vault is briefly
  unreachable and the key is not cached, the request fails closed for that tenant
  (no key = 502, as today) rather than forwarding unauthenticated.

### IAM / least privilege

- The app's task role gets `secretsmanager:GetSecretValue` and `kms:Decrypt`
  scoped by resource ARN prefix `varsten/<env>/provider-keys/*` only — not broad
  Secrets Manager access.
- Writes (creating/rotating a tenant's key) are done by the onboarding/control
  path with a separate, narrower role, never by the data-plane task role.

### Migration steps (no downtime)

1. Add `KeyResolver` interface + `EnvKeyResolver` wrapping today's behavior. No
   behavior change. Ship.
2. Add `SecretsManagerKeyResolver` + TTL cache + the `provider_key_backend` flag,
   defaulting to `env`. Ship dark.
3. Backfill: write each existing tenant's key into Secrets Manager under the new
   layout (one-off script, run from the control path).
4. Flip `provider_key_backend=secretsmanager` in staging, smoke test, then prod.
   `EnvKeyResolver` stays as the instant rollback.
5. Wire the EventBridge rotation -> cache-invalidation hook.
6. Remove `PROXY_OPENAI_KEYS` from the env once prod is stable on the vault.

### What this lets us tell a security reviewer

- Tenant keys are encrypted with per-tenant KMS keys, access is least-privilege and
  audited (CloudTrail on `GetSecretValue`/`Decrypt`), rotation is atomic and
  reversible, and onboarding a client no longer requires a deploy. The data plane
  fails closed on key resolution and never logs or persists keys.
