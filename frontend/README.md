# Varsten Frontend

Next.js 16 dashboard for Varsten.

## Local Setup

Install dependencies from this directory:

```bash
npm install
```

Create `frontend/.env.local` from `.env.example` and fill in the secret values:

```bash
cp .env.example .env.local
```

Required Auth0 settings:

```bash
APP_BASE_URL=http://localhost:3000
AUTH0_DOMAIN=dev-tnqse1hznivo6img.us.auth0.com
AUTH0_CLIENT_ID=P1B0w3im7xLrwBElLzCVrfaXMuotfdqu
AUTH0_CLIENT_SECRET=<from Auth0>
AUTH0_SECRET=<64 hex chars from openssl rand -hex 32>
```

Do not prefix Auth0 secrets with `NEXT_PUBLIC_`. They must stay server-side.

## Auth0 Application Settings

In the Auth0 dashboard for client `P1B0w3im7xLrwBElLzCVrfaXMuotfdqu`:

- Application Type: Regular Web Application
- Token Endpoint Authentication Method: `client_secret_post`
- Allowed Callback URLs: `http://localhost:3000/auth/callback`
- Allowed Logout URLs: `http://localhost:3000`

For deployment, add the production equivalents of the callback and logout URLs, and set `APP_BASE_URL` to the deployed origin.

## Auth Routes

The Auth0 SDK proxy in `proxy.ts` mounts:

- `/auth/login`
- `/auth/logout`
- `/auth/callback`
- `/auth/profile`
- `/auth/access-token`
- `/auth/backchannel-logout`

Use normal `<a>` elements for login/logout links so the SDK routes are handled by the browser request cycle.

## Run

Start the frontend:

```bash
npm run dev -- --port 3000
```

Open `http://localhost:3000`.

Run checks:

```bash
npm run lint
```
