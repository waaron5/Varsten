# AWS operator access hardening

The production workload roles are managed by Terraform. Human/operator access is
managed separately so an application apply cannot accidentally remove the only
account recovery path.

Never paste an access-key secret, MFA seed, password, recovery code, or session
token into source control, chat, shell history, or an evidence document.

## Verified baseline (2026-07-17)

- Root MFA is enabled and the root account has no access keys.
- `varsten-admin-cli` is the only IAM user. It has console access, one active
  long-lived access key, and the AWS-managed `AdministratorAccess` policy.
- The user has no MFA device. Do not remove its current policy or access key until
  the replacement access path below has been tested in a separate session.
- `varsten-production-audit` is an active multi-region CloudTrail with log-file
  validation and a private, encrypted, versioned seven-year S3 archive.

## Human procedure: establish MFA-protected administration

Perform these steps in the AWS console while retaining the current terminal as a
recovery session:

1. Sign in as `varsten-admin-cli` and open **IAM → Users → varsten-admin-cli →
   Security credentials**.
2. Assign a passkey or hardware TOTP MFA device. Store its recovery material in
   the company password manager, not in this repository.
3. Sign out, then sign in again and prove that MFA succeeds.
4. Preferably enable IAM Identity Center, create a named human administrator with
   MFA, and verify a fresh `AdministratorAccess` session from the AWS access
   portal. Keep one documented break-glass path protected by hardware MFA.
5. Open a separate terminal using the new MFA-backed session and verify:

   ```bash
   aws sts get-caller-identity
   aws cloudtrail get-trail-status --name varsten-production-audit
   terraform -chdir=infra/aws/terraform plan
   ```

6. Only after the new session is proven, set the old IAM access key to **Inactive**.
   Verify production readiness and perform a read-only Terraform plan. Leave the
   key inactive for one working day, then delete it.
7. Remove `AdministratorAccess` from `varsten-admin-cli` after the Identity Center
   administrator and break-glass path are proven. Delete the IAM user's console
   password if the user is no longer the break-glass identity.

The application does not depend on the operator key. Disabling it cannot affect
App Runner traffic, but it can block deployments if the replacement session was
not configured correctly—which is why the separate-session proof is mandatory.

## Required steady state

- Every human administrator uses an individual identity with phishing-resistant
  MFA where available; no shared daily-use administrator exists.
- Daily deployment sessions are short-lived. No long-lived access key carries
  `AdministratorAccess`.
- Break-glass credentials are hardware-MFA protected, stored offline, tested on a
  schedule, and generate an alert when used.
- CloudTrail remains logging; delivery failures, trail changes, IAM policy changes,
  and provider-key secret/KMS activity are reviewed and alerted on.
- Customer provider keys are rotated at the upstream provider, reconnected through
  Varsten, and the superseded credentials are revoked.

## Rollback and recovery

If the new identity cannot plan or deploy, do not delete the old key or detach its
policy. Restore access using the still-active recovery session, correct the new
permission assignment, and repeat the separate-session proof. Root should be used
only for account recovery or root-only actions.
