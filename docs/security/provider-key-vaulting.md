# Provider key vaulting: migration to AWS Secrets Manager

Status: AWS Secrets Manager storage is live behind `PROVIDER_KEY_BACKEND`.
Customer-managed KMS enforcement and shorter plaintext cache residency are
implemented in code/Terraform but require the migration below before they are
true of existing production secrets. Human IAM removal, durable CloudTrail, and
read/write workload separation remain separate custody-hardening gates.

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

- The first hardening step uses a dedicated, rotating customer-managed KMS key for
  all provider secrets in one environment. Per-tenant keys remain an enterprise
  isolation target and must not be claimed as deployed yet.
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
  `(project_id, provider)`, production TTL 30 seconds. First request for a tenant pays
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

- The current App Runner instance role reads environment secrets and provider
  secrets, and also writes provider secrets for the self-serve Connections flow.
  This is not the final least-privilege boundary. The CMK change scopes its
  explicit `kms:Decrypt` grant to the provider-key CMK instead of `Resource = "*"`.
- Separating the control-plane writer from the data-plane reader requires a
  separate workload/role and remains mandatory before enterprise launch.

### Existing-secret migration without plaintext export

1. Review and apply Terraform to create the provider-key CMK, alias, exact KMS
   runtime grant, 30-second cache setting, and `PROVIDER_KEY_KMS_KEY_ID`.
2. Deploy the matching backend image. Production startup refuses to proceed if
   the Secrets Manager backend lacks the KMS key identifier.
3. For each existing provider secret, run `aws secretsmanager update-secret` with
   the new KMS key ARN. Do not call `GetSecretValue`, print a secret, or copy one
   through a shell variable.
4. Rotate each key in its provider console, then reconnect it through Varsten.
   That creates a fresh `AWSCURRENT` version under the selected CMK without moving
   the old plaintext through an operator workstation.
5. Verify secret metadata (`KmsKeyId`, tags, version stages), proxy health, and a
   controlled request for each provider. Never include `SecretString` in evidence.
6. Revoke the superseded provider keys at OpenAI, Anthropic, and Google.

This sequence intentionally separates infrastructure creation from key rotation.
Do not narrow or remove the old decrypt path until all existing secrets have been
migrated and a controlled request has passed.

### Migration steps (no downtime)

1. Backfill: write each existing tenant's key into Secrets Manager under the new
   layout (one-off script, run from the control path).
2. Flip `PROVIDER_KEY_BACKEND=secretsmanager` in staging, smoke test, then prod.
   `EnvKeyResolver` stays as the instant rollback.
3. Wire the EventBridge rotation -> cache-invalidation hook.
4. Remove env maps once prod is stable on the vault.

### Target statement after all custody gates pass

- Provider keys are encrypted with a dedicated CMK, runtime access is
  least-privilege and durably audited, rotation is controlled, and onboarding a
  client does not require a deploy. Per-tenant/customer-owned custody is described
  separately and never implied for the shared hosted gateway.
