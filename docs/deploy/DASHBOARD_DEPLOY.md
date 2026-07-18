# Dashboard deploy runbook (Phase A: config/readiness)

Goal: serve the existing Next.js dashboard/onboarding at `https://app.varsten.ai`
so a customer can log in, create a project, generate a `vk_` key, and send a first
request. The dashboard is already built; this is deployment + config only.

## Architecture

```
Browser ── pages + Auth0 (/auth/*) ──▶  Vercel (Next.js 16, frontend/)
   │
   └── data + mutations (Authorization: Bearer <Auth0 token>) ─CORS─▶  App Runner backend
                                                                       (xkmwbvcq2r.us-east-1.awsapprunner.com)
```

- `lib/api.ts` calls the backend from the **browser** (`NEXT_PUBLIC_API_BASE`), so the
  backend `CORS_ORIGINS` must include the dashboard origin.
- Auth0 runs through Next 16's `proxy.ts` (`auth0.middleware`), which mounts
  `/auth/login|logout|callback`.

## Build status

Clean-`main` `next build` (Next 16.2.7) succeeds locally — all dashboard routes +
the Auth0 `Proxy (Middleware)` compile. Vercel builds the committed branch, so the
WIP in the working tree (entitlements/security/frontend-playwright experiments) is
intentionally excluded.

## A1. Auth0 — production Regular Web Application

In the designated **production** Auth0 tenant
(`dev-tnqse1hznivo6img.us.auth0.com`):

1. Confirm an **API** exists with identifier (audience) exactly `https://api.varsten.ai`
   (the backend already validates tokens against it).
2. Create/confirm a **Regular Web Application** for the dashboard and set:
   - Allowed Callback URLs: `https://app.varsten.ai/auth/callback`
   - Allowed Logout URLs: `https://app.varsten.ai`
   - Allowed Web Origins: `https://app.varsten.ai`
   - Grant types include `authorization_code` + `refresh_token` (the app requests
     `offline_access`).
3. Copy its **Client ID** and **Client Secret** for the Vercel env below.

(For a Vercel preview deploy, also add the preview origin, e.g.
`https://<preview>.vercel.app/auth/callback`, then remove it after cutover.)

## A2. Vercel project

1. New Vercel project from this repo. **Root Directory: `frontend`** (Vercel
   auto-detects Next.js; build command `next build`, output default).
2. Set Production environment variables — see `frontend/.env.production.example`:
   - `NEXT_PUBLIC_API_BASE=https://api.varsten.ai`
   - `AUTH0_DOMAIN=dev-tnqse1hznivo6img.us.auth0.com`
   - `AUTH0_CLIENT_ID`, `AUTH0_CLIENT_SECRET` (from A1)
   - `AUTH0_SECRET` = `openssl rand -hex 32`
   - `AUTH0_AUDIENCE=https://api.varsten.ai`
   - `APP_BASE_URL=https://app.varsten.ai`
   - **Do NOT set `NEXT_PUBLIC_E2E_AUTH_BYPASS`** (=1 disables auth — security hole).
3. Deploy a **preview** first and verify (see Verification). Because
   `NEXT_PUBLIC_API_BASE` is build-time-inlined, it must be set before the build.

## A3. Backend CORS

`CORS_ORIGINS` is already `["https://app.varsten.ai"]` — no backend change needed for
the production domain. Only for a temporary `*.vercel.app` preview would you add that
origin to `CORS_ORIGINS` (a backend redeploy), then revert.

## A4. DNS (do LAST, after build/env are clean)

Point `app.varsten.ai` at Vercel (CNAME/A per Vercel's domain instructions); verify
TLS. Optionally configure the App Runner custom domain `api.varsten.ai` and switch
`NEXT_PUBLIC_API_BASE` to it (cleaner, not required — the `awsapprunner.com` URL works).

## Verification checklist

- `app.varsten.ai` loads; `/auth/login` redirects to Auth0 and back.
- Browser DevTools: `createProject` / `createApiKey` succeed with **no CORS error**
  (the most likely first failure).
- The Auth0 access token has audience `https://api.varsten.ai` (not an opaque
  userinfo token); `POST /v1/auth/sync` returns 200.
- New user → "Create your first project" → onboarding → "Create API key" shows a
  `vk_…` once.
- Run the base-URL snippet with that key; onboarding "Send a test request" flips to
  received.
- `NEXT_PUBLIC_E2E_AUTH_BYPASS` is unset in prod (an anonymous request to a dashboard
  page must show the login gate, not data).

## Out of scope for Phase A

Key-revocation UI, onboarding snippet copy, SDK publishing, and the production keyed
smoke are later steps. No backend fail-open logic changes; no Anthropic/Gemini/
embeddings/batch work; no unrelated entitlements/security/marketing WIP.
