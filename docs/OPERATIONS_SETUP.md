# Operations Setup

These steps are required before using the marketing lead flow and operator onboarding flow in production.

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
