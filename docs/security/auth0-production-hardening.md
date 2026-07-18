# Auth0 production hardening worksheet

Tenant: `dev-tnqse1hznivo6img.us.auth0.com`

Application client ID: `bcBLfGeiEF1ra9LDdkm0xP11MtXBu6NF`

API audience: `https://api.varsten.ai`

This worksheet contains no secrets. Do not record client secrets, passwords, MFA
seeds, recovery codes, email-provider credentials, or access tokens here.

Complete each item in the Auth0 dashboard and record only the resulting setting or
`not available on current plan`. A plan limitation is a launch decision, not a
silent pass.

## 1. Tenant ownership and production designation

Dashboard: **Settings → General** and **Settings → Tenant Members**.

- [ ] Environment tag is **Production**.
- [ ] Friendly name is **Varsten**.
- [ ] Support email uses a monitored Varsten mailbox.
- [ ] Support URL points to a live Varsten support/contact page.
- [ ] Every tenant member is recognized and still requires access.
- [ ] Every tenant member shows MFA enabled.
- [ ] At least two recovery-capable owners exist, or a documented single-founder
      break-glass procedure exists until a second owner is added.
- [ ] **Enable Application Connections** is off, so new applications do not
      inherit unintended identity connections.

Do not remove the only tenant owner during this review.

## 2. Dashboard application

Dashboard: **Applications → Applications → Varsten dashboard application →
Settings**.

The exact production values are:

| Setting | Required value |
| --- | --- |
| Application type | Regular Web Application |
| Application Login URI | `https://app.varsten.ai/auth/login` |
| Allowed Callback URLs | `https://app.varsten.ai/auth/callback` only |
| Allowed Logout URLs | `https://app.varsten.ai` only |
| Allowed Web Origins | `https://app.varsten.ai` only |
| Allowed Origins (CORS) | Empty unless a demonstrated Auth0 browser call requires it |
| Token endpoint authentication method | `client_secret_post` or `client_secret_basic`; never `none` |
| JSON Web Token signature algorithm | RS256 |
| OIDC conformant | Enabled |

- [ ] Remove every localhost, `127.0.0.1`, preview-Vercel, wildcard, stale domain,
      path-bearing web origin, and unused callback/logout URL.
- [ ] Under **Advanced Settings → Grant Types**, enable only
      `authorization_code` and `refresh_token`. Disable implicit, password,
      password-realm, device-code, client-credentials, MFA grants, and other flows
      unless a separately documented consumer requires one.
- [ ] Keep open-redirect protection enabled where the plan exposes it.
- [ ] Do not trust the token-endpoint forwarded-IP header unless Varsten operates
      the trusted proxy that sets it.

## 3. Refresh tokens and sessions

The frontend requests `offline_access`; refresh tokens therefore need rotation and
expiration instead of unlimited bearer lifetime.

Recommended first-customer baseline:

| Setting | Launch baseline |
| --- | ---: |
| Refresh Token Rotation | Enabled |
| Rotation Overlap Period | 5 seconds |
| Absolute Refresh Token Lifetime | 2,592,000 seconds (30 days) |
| Inactivity Refresh Token Lifetime | 604,800 seconds (7 days) |
| Tenant SSO inactivity timeout | 480 minutes (8 hours) |
| Tenant require-login-after | 4,320 minutes (3 days) |
| API access-token lifetime | 3,600 seconds (1 hour) |

- [ ] Rotation is enabled and reuse detection remains active.
- [ ] Absolute and inactivity expiration are both enabled.
- [ ] Record any intentional deviation and why in the production evidence register.

## 4. Identity connections

Dashboard: **Authentication → Database/Social/Enterprise** and the application’s
**Connections** tab.

- [ ] Enable only the connection(s) intentionally offered at launch.
- [ ] Disable signups on any administrative or legacy database connection.
- [ ] Require email verification for database signups before treating the address
      as trusted.
- [ ] Review duplicate identities before enabling multiple login methods. Do not
      automatically link accounts solely because email addresses match.
- [ ] Remove test users only through an explicit data-cleanup procedure; never
      delete an ambiguous identity to work around an account-linking error.

## 5. Attack protection

Dashboard: **Security → Attack Protection**.

- [ ] Brute Force Protection is enabled with blocking, not monitoring only.
- [ ] Breached Password Detection is enabled.
- [ ] Block compromised credentials for signup, login, and password reset.
- [ ] User notification for compromised credentials is enabled after the
      production email provider is proven.
- [ ] Suspicious IP Throttling is enabled with an enforcement response if included
      in the plan.
- [ ] Bot Detection is enabled with an enforcement response if included in the
      plan; test that legitimate signup remains usable.
- [ ] Run Auth0's production readiness check and resolve or explicitly record every
      finding.

## 6. MFA policy

Progress (`2026-07-18`): outstanding; the actions in this section still need to
be completed.

Dashboard administrator MFA is mandatory and separate from customer MFA.

- [ ] All tenant administrators use MFA, preferably passkeys or hardware security
      keys, with recovery material stored outside Auth0.
- [ ] For customer accounts, enable WebAuthn security keys/passkeys and OTP where
      available. Do not make SMS the sole factor.
- [ ] Choose **Adaptive MFA** if the subscription includes it. Otherwise document
      whether launch uses **Always** or a post-login Action appropriate to the
      enterprise pilot.
- [ ] Test enrollment, challenge, recovery, and lost-device handling with a test
      identity before enforcing a new customer policy.

## 7. Production email and recovery

Progress (`2026-07-18`): Resend is the selected provider, but it is not configured
in Auth0. A new or safely retrieved Resend API key may be required; do not record
the key in this worksheet.

Dashboard: **Branding → Email Provider** and **Email Templates**.

- [ ] Configure a company-controlled email provider; the Auth0 test provider is
      not a production delivery service.
- [ ] Verify the sending domain with SPF and DKIM (and DMARC policy/monitoring).
- [ ] Send and receive a test email.
- [ ] Customize and test verification, password reset, blocked account, breached
      password, and MFA enrollment templates.
- [ ] Links use production domains and monitored support contact information.
- [ ] Password reset uses the current flow; legacy/deprecated reset behavior is
      disabled where the tenant exposes the setting.

## 8. Logs and incident evidence

Progress (`2026-07-18`): outstanding; a guided configuration walkthrough is
required.

Auth0's native retention is plan-dependent and short. Production authentication
evidence must be exported.

- [ ] Record the subscription's native log-retention period.
- [ ] Configure a log stream to a controlled destination with at least one year of
      retention, access logging, and restricted operator access.
- [ ] Alert on repeated failed logins, breached-password events, blocked IPs,
      administrator changes, application/connection changes, and log-stream errors.
- [ ] Generate a harmless login failure and prove it arrives at the destination.
- [ ] Confirm logs do not contain access tokens, client secrets, passwords, or MFA
      material.

## 9. Phase 4.2 evidence to return

Return only this non-secret summary:

```text
Environment tag: production / unavailable
Tenant members with MFA: <count>/<count>
Callbacks: exact / needs correction
Logout URLs: exact / needs correction
Web origins: exact / needs correction
Grant types: authorization_code, refresh_token / other: <names>
RS256 + OIDC conformant: yes/no
Refresh rotation + absolute/inactivity expiry: yes/no
Attack protection enforcement: brute force=<state>, breached=<state>, IP=<state>, bot=<state>
Customer MFA policy: <state>
Production email test received: yes/no
Native log retention: <days>
External log stream test received: yes/no
Production readiness check unresolved findings: <count and titles>
```

Phase 4.2 passes only when the settings are verified, not merely saved. Phase 4.3
then performs fresh signup, login/logout, callback failure, expiration, recovery,
and cross-tenant live tests.

## References

- <https://auth0.com/docs/get-started/tenant-settings>
- <https://auth0.com/docs/get-started/applications/application-settings>
- <https://auth0.com/docs/secure/attack-protection>
- <https://auth0.com/docs/secure/multi-factor-authentication/enable-mfa>
- <https://auth0.com/docs/deploy-monitor/logs/log-data-retention>
