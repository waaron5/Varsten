# Operations Setup

These steps are required before using Varsten production flows.

## Multi-Provider SDK Drop-In Launch

Use this checklist before enabling the inline proxy for OpenAI, Anthropic, or
Gemini traffic in production.

### 1. Apply Backend Migrations

Run migrations before routing live SDK traffic:

```bash
make migrate
```

Confirm the following tables/columns exist:

- `provider_connections.secret_ref`
- `provider_connections.last_verified_at`
- `provider_connections.last_error`
- `optimization_decisions`

The `optimization_decisions` table is required for routing-ineligibility audit
trails. Do not enable cross-provider routing before it exists.

### 2. Configure Provider Key Vaulting

Production should use AWS Secrets Manager:

```bash
PROVIDER_KEY_BACKEND=secretsmanager
PROVIDER_KEY_CACHE_TTL_SECONDS=300
PROVIDER_KEY_CACHE_MAXSIZE=4096
PROVIDER_KEY_SECRET_PREFIX=varsten
PROVIDER_KEY_SECRET_ENVIRONMENT=production
PROVIDER_KEY_AWS_REGION=us-east-1
PROXY_DEFAULT_PROVIDER=openai
```

Local/dev may use `PROXY_PROVIDER_KEYS`, `PROXY_OPENAI_KEYS`,
`PROXY_ANTHROPIC_KEYS`, and `PROXY_GEMINI_KEYS`, but production provider keys
should be written through the dashboard Connections screen or
`PUT /v1/admin/connections/{provider}`.

Secrets are stored as one secret per project/provider:

```text
varsten/<env>/provider-keys/<project_id>/<provider>
```

Each secret value is JSON:

```json
{"api_key":"sk-..."}
```

### 3. Configure IAM Least Privilege

The data-plane task role needs read-only access to provider secrets and KMS
decrypt:

```json
{
  "Effect": "Allow",
  "Action": ["secretsmanager:GetSecretValue", "kms:Decrypt"],
  "Resource": [
    "arn:aws:secretsmanager:<region>:<account>:secret:varsten/production/provider-keys/*",
    "arn:aws:kms:<region>:<account>:key/<kms-key-id>"
  ]
}
```

The control-plane role used by the dashboard/admin API additionally needs:

```json
{
  "Effect": "Allow",
  "Action": [
    "secretsmanager:CreateSecret",
    "secretsmanager:PutSecretValue",
    "secretsmanager:DeleteSecret"
  ],
  "Resource": "arn:aws:secretsmanager:<region>:<account>:secret:varsten/production/provider-keys/*"
}
```

Keep write/delete permissions off any worker that only forwards model traffic.

### 4. Connect Providers

In the dashboard, open Settings -> Connections and connect or rotate keys for:

- OpenAI
- Anthropic
- Gemini

The UI never returns stored secrets. Disconnecting a provider deletes the
Secrets Manager secret, clears cached decrypted keys, and marks the provider
connection `not_connected`.

### 5. Run Live SDK Smoke

Start the API and run the opt-in SDK smoke tests with a Varsten `vk_` API key
from the connected project:

```bash
cd backend
uv pip install openai anthropic google-genai
cd ..
VARSTEN_SDK_SMOKE=1 \
VARSTEN_SDK_SMOKE_BASE_URL=https://<api-host> \
VARSTEN_SDK_SMOKE_API_KEY=vk_<project-key> \
make backend-sdk-smoke
```

Optional model overrides:

```bash
VARSTEN_SDK_SMOKE_OPENAI_MODEL=gpt-4o-mini
VARSTEN_SDK_SMOKE_ANTHROPIC_MODEL=claude-3-5-haiku-20241022
VARSTEN_SDK_SMOKE_GEMINI_MODEL=gemini-3.5-flash
```

The smoke suite covers non-streaming and streaming calls through the official
OpenAI, Anthropic, and Google GenAI SDKs.

### 6. Validate Routing Audit Records

For a request that stays on the incumbent provider because it cannot be safely
translated, confirm an `optimization_decisions` row records:

- `request_id`
- requested provider/model
- candidate provider/model
- `decision = ineligible`
- exact `reason_code`

Known reason codes include `anthropic_cache_control`,
`anthropic_beta_unsupported`, `gemini_safety_settings`, `server_side_tool`, and
`native_multimodal_unmapped`.

### 7. Rollback

If a launch issue appears:

1. Set `PROXY_KILL_SWITCH=true` to bypass optimization.
2. Disable affected routing policies.
3. If vault access is the issue, switch `PROVIDER_KEY_BACKEND=env` only after
   placing scoped temporary keys in env maps.
4. Clear provider-key cache or restart workers after key/backend changes.

## Marketing Lead Email

Set these variables in `marketing/.env.local` for local development and in the Vercel project environment for production:

```bash
RESEND_API_KEY=
LEADS_NOTIFY_EMAIL=aaron@varsten.ai
LEADS_FROM_EMAIL="Aaron Wood <aaron@varsten.ai>"
LEADS_CALENDLY_URL=https://calendly.com/<your-handle>/<event-slug>
```

`LEADS_FROM_EMAIL` must be a sender address/domain verified in Resend. `LEADS_CALENDLY_URL` is inserted into the buyer autoresponder email.

## Backend Operator Access

Set this in the backend runtime environment:

```bash
OPERATOR_ADMIN_EMAILS='["aaron@varsten.ai"]'
```

This is a JSON array of Auth0 user emails allowed to call `/v1/operator/*`. Everyone else receives `403 Forbidden`.

## Resend Domain Verification

1. Open Resend.
2. Add `varsten.ai` under Domains.
3. Copy the DNS records Resend provides.
4. Add the TXT/CNAME records in the DNS provider for `varsten.ai`.
5. Wait until Resend marks the domain as verified.
6. Use a verified sender in `LEADS_FROM_EMAIL`.

## Calendly Setup Event

Create a 15-minute setup event and add these required booking questions:

- Language/framework
- Current request volume

Use the event URL as `LEADS_CALENDLY_URL`.

## API Key Handoff

During onboarding, transfer generated API keys through 1Password Send or an equivalent one-view secret link. Do not paste plaintext API keys into email, chat, ticketing systems, or call transcripts.
