# Self-serve onboarding walkthrough (local, end to end)

Test the whole funnel the way a real customer hits it — from the marketing
"Start free trial" / "Explore observe only" CTAs, through onboarding, to a live
Dashboard — against the real backend, real proxy, real engine, and zero provider
spend.

This exercises everything the mocked Playwright specs cannot: the real control
plane (Auth0 session), the vaulted provider key, the inline proxy hot path, and
the consolidated dashboard snapshot. The only thing standing in for reality is
`scripts/fake_provider.py`, a zero-cost OpenAI-compatible stub, so no real
provider account, key, or spend is involved.

## Why the topology is a hybrid (not `make up`)

The backend must reach the fake provider at host `127.0.0.1:9100`, which a
container can't. So: **Postgres + Redis in Docker, and the fake provider +
backend + frontend on the host.** `scripts/walkthrough.sh` sets this up for you.

Prerequisites (already true in this repo's dev setup):

- `backend/.env`: Auth0 configured, `PROVIDER_KEY_BACKEND=localdb`,
  `PROVIDER_KEY_LOCAL_ENCRYPTION_KEY` set, `OPENAI_BASE_URL=http://127.0.0.1:9100`.
- `frontend/.env.local`: Auth0 client + `NEXT_PUBLIC_API_BASE=http://localhost:8000`
  and `NEXT_PUBLIC_VARSTEN_PROXY_BASE=http://localhost:8000/v1` so onboarding
  snippets point at the local proxy.
- `backend/.venv` (`cd backend && uv sync`) and `frontend/node_modules`
  (`cd frontend && npm install`).

## 1. Start the stack

```
make walkthrough                 # db+redis, migrations, fake provider, backend, frontend
make walkthrough sync-prices     # first time only: price the catalog so cost/savings render
```

`make walkthrough-status` shows health; logs are in `.walkthrough/*.log`. Stop the
host processes with `make walkthrough-down` (the database is left running).

## 2. Walk the funnel in the browser

Pick the entry point that matches the CTA you want to test:

| CTA | URL | Result |
| --- | --- | --- |
| Start free trial | http://localhost:3000/start?intent=trial | Optimize trial org |
| Explore observe only | http://localhost:3000/start?intent=observe | Free / observe-only org |

Then:

1. Log in via Auth0 (your dev tenant). `/start` syncs the intent and redirects
   into `/onboarding?intent=…`.
2. **Stack step** — pick provider, language, and integration path. Production SDK
   is pre-selected. (Observe intent defaults to the Gateway URL; picking a
   non-TypeScript language moves an SDK selection to the Gateway URL, since the
   fail-open SDK is TypeScript-only today.)
3. **Keys step** — create the Varsten key (copy the `vk_…` shown once), then
   connect OpenAI with any string, e.g. `sk-fake-local-test` (skipped on the
   metadata path). The stub's `GET /v1/models` accepts any key, and the key is
   Fernet-vaulted locally.
4. **Verify step** — shows the generated recipe (install, env vars with your real
   `vk_` key if created this session, code) and waits for the first request. Send
   it (next section). The step flips to "Verified live" with the first captured
   request, and **Finish setup** lands you on `/dashboard`.

The dashboard shows the "Waiting for your first request" state until traffic
lands, then fills in.

## 3. Generate live traffic

`Finish setup` needs one verified request; a realistic Dashboard needs more.

```
# Use the key you copied in the wizard:
make walkthrough-traffic KEY=vk_...            # ~40 requests, ~60% cacheable
make walkthrough-traffic KEY=vk_... ARGS="--first-only"   # just the verification request
make walkthrough-traffic KEY=vk_... ARGS="--count 120"
```

The tool sends OpenAI-dialect traffic through the proxy (SDK-tagged by default,
so the Production SDK path verifies), reuses prompts to produce cache hits, tags
requests with varied feature/team metadata, then reads back the live snapshot and
prints the KPIs — the same numbers the UI renders.

No UI at all? Seed a throwaway performance project + vaulted key and use it:

```
make walkthrough-traffic ARGS="--seed --count 60"
```

## What "full functionality" looks like — and what it honestly won't fake

- **Immediately:** `mode` flips `empty → spend_only`, and Actual/Baseline spend
  populate from the real pricing catalog. Cache hits are served on the hot path.
- **Savings are deliberately not painted on.** Verified savings come from
  `SavingsAttribution`, tied to the measurement machinery: direct-measured lever
  savings and the randomized-holdback A/B (which needs ≥30 samples per arm before
  it reports a confidence interval). A trickle of ad-hoc traffic with no levers
  configured will honestly show spend without claimed savings — the "no
  painted-on savings" principle, not a bug.
- To see savings and Proof populate, walk the real trial funnel (proper
  entitlements), enable levers in **Engine**, and push enough volume through the
  same routes for the holdback to reach signal.

## Proving measured savings (the real attribution pipeline)

The default walkthrough shows onboarding, live traffic, and spend. To prove the
*measurement* pipeline — that Varsten reports savings only when a real A/B says
so — run the separate policy proof:

```
make walkthrough-proof                       # ~140 requests, token-trim lever, gpt-4o
make walkthrough-proof ARGS="--requests 200 --holdback 0.25"
```

What it does, end to end, on a throwaway org it cleans up afterward:

1. Seeds a throwaway Optimize project + vaulted key.
2. Activates **one real lever** (token-trim) through the product's own
   `activate_trim_policy` — the same function the apply-recommendation endpoint
   calls — then opens the canary rollout to 100% so the experiment fills in test
   volume.
3. Sends paired traffic tagged low-risk with a task type (what a real integration
   sends; the planner blocks trim on risky/unknown routes by design). Each request
   is unique and carries a large collapsible block, so the trimmed **treatment**
   arm is genuinely cheaper than the held-back **control** arm.
4. Reads the result from `compute_verified_savings` / `compute_experiment` — the
   exact functions the Dashboard and Proof pages use — and asserts non-zero
   **measured** savings with `has_signal` (≥30 samples per arm). It never writes
   savings directly.

It prints the arm counts, per-request delta, gross/net measured savings with a
confidence interval, and the URLs where these appear in the product
(`/dashboard`, `/proof/savings`, `/proof/attribution`).

Explicit about volume: the holdback A/B needs **≥30 samples per arm**. At the
default 30% holdback, ~140 requests yields ~42 control / ~98 treatment. It fails
clearly (and cleans up) if an arm falls short, if the model is unpriced, if the
org is not on Optimize, or if trim produced no cost delta.

Because it uses a throwaway org with no Auth0 user, it is not viewable in the
browser — the printed numbers are exactly what the UI renders. To see them in the
UI, apply the same lever on your onboarded project from the **Engine** page.

## Troubleshooting

- **`502 no_provider_key`** — no provider connected for the project. In the UI,
  finish the provider step; with `--seed` this is handled automatically.
- **Cost/savings show unpriced** — run `make sync-prices` once.
- **Dashboard stays empty** — confirm you sent traffic with the project's own
  `vk_` key to `http://localhost:8000`, and check `.walkthrough/backend.log`.
- **Auth errors on the dashboard** — the control plane requires a real Auth0
  session; the frontend E2E bypass is for mocked tests only and won't work here.
