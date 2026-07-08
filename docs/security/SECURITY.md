# Varsten Security Posture

A plain-language summary of how Varsten protects customer data and traffic. Written
to be handed to a customer's technical buyer or security reviewer. It states what
is true today and what is on the roadmap, without conflating the two.

## Architecture in one paragraph

Varsten is an inline AI proxy plus a control plane. Customer traffic authenticates
with a Varsten `vk_` key, Varsten resolves the customer's upstream provider key,
forwards the request, and records metadata-only usage. Optimization (caching,
routing, trimming, batching) only runs on the paid Optimize plan; the Free plan
is observe-only and cannot alter production behavior.

## Data protection

- **Metadata-only ledger.** Token counts, model, latency, and derived cost — never
  prompt or completion text. See `data-handling.md`.
- **Bounded content stores.** The only places content can live are the semantic
  cache, the opt-in replay corpus, and batch staging — each time-bounded by a TTL
  and each tied to a feature you enable.
- **Encryption.** Data at rest in Postgres and Secrets Manager is encrypted;
  traffic is TLS-terminated at the managed container host. Provider keys are
  KMS-encrypted, one secret per project/provider.
- **No training, no resale.** Customer data is never used to train models or sold.

## Access control and tenancy

- OAuth (Auth0) for dashboard sign-in; identity is keyed on the stable provider
  subject, never email.
- Strict multi-tenant isolation: every authorization walks organization
  membership, and all data is project-scoped. A request can only touch its own
  tenant's data.
- Varsten API keys are stored as SHA-256 hashes; the plaintext is shown once and
  never retrievable. Keys are revocable.
- Operator (founder) actions are gated to an allowlist and are audited.

## Auditability

An append-only audit log records sensitive control-plane actions — plan changes
and provider-key connect/disconnect — with actor, target, timestamp, source IP,
and before/after state, never secret values. Customers can read their own
organization's audit log from the dashboard.

## Reliability and safety (because we are inline)

- **Fail open.** If the control plane, cache, or plan lookup is unreachable,
  traffic forwards straight to the provider, still metered. Worst case is "we stop
  saving," never "we took down prod."
- **Kill switch.** A global and a per-project switch bypass all optimization in one
  toggle.
- **Circuit breaker + timeouts** on the upstream path; **rate limiting** on the
  public proxy surface.
- **Readiness probe** keeps a pod out of rotation if it cannot reach the database.

## Operational security

- Secrets live in AWS Secrets Manager, never in the repository or images. The data
  plane's IAM role is least-privilege: read only its environment's secrets, decrypt
  via KMS.
- Errors go to Sentry with PII attachment disabled (no headers, cookies, or
  bodies).
- Automated database backups with point-in-time recovery; restore is drilled (see
  `OPERATIONS_DEPLOY.md`).
- CI enforces lint, type, security scan, complexity, and the full test suite on
  every change.

## Compliance status (stated honestly)

Varsten is built to be SOC 2-compatible — append-only audit logging, least-
privilege IAM, encryption at rest, tenant isolation, and a documented data flow —
but is **not yet SOC 2 certified**. On request and under NDA we can share the
current state of: SOC 2 roadmap, DPA, subprocessor list, pen test summary, and a
data flow diagram. We will not claim an artifact exists before it does.

## Reporting a vulnerability

Email security@varsten.ai with details and reproduction steps. We will acknowledge
and work the issue per the severity playbook in `incident-response.md`.
