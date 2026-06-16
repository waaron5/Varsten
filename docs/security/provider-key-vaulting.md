# Provider key vaulting: migration to AWS Secrets Manager

Status: implemented behind `PROVIDER_KEY_BACKEND`. The data plane resolves
provider keys through a provider-aware TTL cache; production writes and deletes
use AWS Secrets Manager and local/dev can still use env maps for rollback.

## Today (interim, Phase 1)

A client's upstream provider key can be supplied to the backend as a JSON env var,
either with the legacy OpenAI-only map `PROXY_OPENAI_KEYS` or the provider-aware
map `PROXY_PROVIDER_KEYS`:

```json
{"anthropic": {"<project-uuid>": "sk-ant-..."}, "gemini": {"<project-uuid>": "AIza-..."}}
```

It is read in `app/proxy/keys.py` through
`provider_key_for_project(project_id, provider)`.

Properties of the interim approach:

- Keys live in the platform's env/secret store (App Runner config / Secrets Manager
  reference), never in the repo, never returned to clients, never logged, never
  written to the ledger (audited).
- Resolution is a dict lookup: zero latency, no new dependency on the hot path.

Limitations a CTO will (correctly) flag:

- **Onboarding a client via env requires a redeploy**, which does not scale
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

`app/proxy/keys.py` isolates resolution and storage behind a provider-aware seam:

```python
# app/proxy/keys.py
def provider_key_for_project(project_id: uuid.UUID, provider: str) -> str | None:
    ...

def store_provider_key_for_project(project_id: uuid.UUID, provider: str, api_key: str) -> str:
    ...

def delete_provider_key_for_project(project_id: uuid.UUID, provider: str) -> None:
    ...
```

- `EnvProviderKeyResolver` supports local/dev env maps and refuses writes.
- `SecretsManagerProviderKeyResolver` stores one secret per
  `(project_id, provider)` and can delete the same secret on disconnect.
  It is selected with `PROVIDER_KEY_BACKEND=secretsmanager`.
- The proxy calls `provider_key_for_project(project.id, adapter.provider)`, so
  OpenAI, Anthropic, and Gemini all use the same hot-path key-resolution contract.

### Hot-path latency

A Secrets Manager `GetSecretValue` call is ~10-30ms — unacceptable on every
request. Mitigation:

- **In-process TTL cache** (`cachetools.TTLCache` guarded by an `RLock`), keyed by
  `(project_id, provider)`, default TTL 5 minutes. First request for a tenant pays
  the fetch; subsequent ones are in-memory.
- **Decrypt cache** via the AWS SDK is also available; the TTL cache is the primary
  control.
- Cache is invalidated on rotation and disconnect, so a changed key takes effect
  promptly and a disconnected provider does not continue using a stale in-memory
  credential.

### Rotation and disconnect

- Manual rotate through `PUT /v1/admin/connections/{provider}` writes a new
  Secrets Manager version and updates `provider_connections.last_verified_at`.
- Disconnect through `DELETE /v1/admin/connections/{provider}` deletes the
  Secrets Manager secret, clears `provider_connections.secret_ref`, marks the row
  `not_connected`, and invalidates the in-process key cache.
- Secrets Manager rotation schedule can also write a new version.
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
  path with a separate role that also has `secretsmanager:CreateSecret`,
  `secretsmanager:PutSecretValue`, and `secretsmanager:DeleteSecret`, never by
  the data-plane task role.

### Migration steps (no downtime)

1. Backfill: write each existing tenant's key into Secrets Manager under the new
   layout (one-off script, run from the control path).
2. Flip `PROVIDER_KEY_BACKEND=secretsmanager` in staging, smoke test, then prod.
   `EnvKeyResolver` stays as the instant rollback.
3. Wire the EventBridge rotation -> cache-invalidation hook.
4. Remove env maps once prod is stable on the vault.

### What this lets us tell a security reviewer

- Tenant keys are encrypted with per-tenant KMS keys, access is least-privilege and
  audited (CloudTrail on `GetSecretValue`/`Decrypt`), rotation is atomic and
  reversible, and onboarding a client no longer requires a deploy. The data plane
  fails closed on key resolution and never logs or persists keys.
