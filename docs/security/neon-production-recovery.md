# Neon production recovery worksheet

This worksheet records non-secret production recovery evidence. Do not paste
database URLs, passwords, access tokens, user email addresses, or recovery codes.

## Known production facts

- Database provider: Neon Postgres
- Region: AWS `us-east-1`
- Application credentials: AWS Secrets Manager
- Existing pre-price-sync recovery branch: `br-icy-scene-aimmtj6f`

The existing branch demonstrates that a branch was created successfully. It does
not establish the current restore window, snapshot policy, account recovery, or a
completed restore drill.

## Phase 5.1 — account and recovery capability

Complete these fields from the Neon console:

- Plan name:
- Billing status (`active` or `action required`):
- Production project name:
- Production branch ID:
- Production branch is the root branch (`yes` or `no`):
- Configured instant-restore window:
- Oldest selectable restore timestamp (UTC):
- Snapshots available (`yes` or `no`):
- Scheduled snapshot frequency:
- Scheduled snapshot retention:
- Project region:
- Account MFA enabled (`yes` or `no`):
- Authorized project/account administrators (count only):
- Second recovery-capable administrator (`yes` or `no`):
- Account recovery method tested (`yes` or `no`):

Confirm in **Backup & Restore**:

- [ ] The production root branch is selected.
- [ ] History/time-travel controls are available, or their plan limitation is recorded.
- [ ] The interface offers restoration to a new branch.
- [ ] The account has enough compute allowance for an isolated restore endpoint.
- [ ] Branch `br-icy-scene-aimmtj6f` is visible, or its absence is explained.

## Phase 5.2 — proposed internal recovery objectives

These are proposed engineering targets, not a customer SLA or public promise,
until an isolated drill proves them and contractual terms approve them.

- RPO: one hour, contingent on the configured Neon restore window covering it.
- RTO: four hours from confirmed incident declaration.
- Recovery owner: founder until a second recovery-capable owner is assigned.
- Customer notification threshold: confirmed data loss, cross-tenant exposure, or
  a material recovery event; contractual notification timing remains subject to
  the approved DPA and incident policy.

## Phase 5.3 — isolated restore drill record

Do not begin this operation without explicit approval. Restore only to a new,
isolated branch. Never overwrite or reset production during the drill.

- Source branch ID:
- Selected recovery timestamp (UTC):
- Drill start (UTC):
- Restored branch ID:
- Endpoint ready (UTC):
- Verification complete (UTC):
- Recovery-point gap / measured RPO:
- Time to endpoint:
- Time to verified recovery / measured RTO:
- Alembic revision matches expected state (`yes` or `no`):
- Aggregate organization/project counts plausible (`yes` or `no`):
- API-key metadata count plausible (`yes` or `no`):
- Model/price catalog counts plausible (`yes` or `no`):
- Usage and billing aggregate counts plausible (`yes` or `no`):
- Provider-connection metadata count plausible (`yes` or `no`):
- Tenant-isolation checks pass (`yes` or `no`):
- Production remained healthy and unchanged (`yes` or `no`):
- Temporary endpoint and branch deleted (`yes` or `no`):
- Findings and remediation:

Use aggregate, read-only verification. The restored destination must not receive
production traffic or connect to email, provider APIs, Stripe, webhooks, or
schedulers.

## Provider references

- <https://neon.com/docs/manage/projects#restore-window>
- <https://neon.com/docs/guides/branch-restore>
- <https://neon.com/docs/manage/backup-restore>
- <https://neon.com/docs/manage/snapshots>
