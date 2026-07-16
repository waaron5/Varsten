"""Drive live traffic through the Varsten proxy for the self-serve walkthrough.

The onboarding funnel proves the *first* request. This proves the rest: enough
real traffic through the inline proxy (via ``scripts/fake_provider.py``) that the
Dashboard and Proof pages fill with live numbers instead of the empty state.

It sends OpenAI-dialect chat completions through the proxy with a project's
``vk_`` key. A slice of the traffic reuses a small pool of prompts so the exact
cache produces hits (measurable savings), and requests are tagged with varied
feature/team metadata so the allocation breakdown has something to show. After
the burst it reads ``GET /v1/dashboard/snapshot`` with the same key (the snapshot
endpoint accepts an API key, no Auth0 needed) and prints the live KPIs so you can
confirm the loop end to end from the terminal.

Usage, from ``backend/`` with the stack running (see scripts/walkthrough.sh):

    # Against a key you generated in the onboarding UI:
    .venv/bin/python scripts/walkthrough_traffic.py --key vk_live_...

    # Or seed a throwaway performance project + key and use it (no UI needed):
    .venv/bin/python scripts/walkthrough_traffic.py --seed

    # Just the single verification request the wizard waits for:
    .venv/bin/python scripts/walkthrough_traffic.py --key vk_... --first-only

``--policy`` is a separate, self-contained proof of the *measurement* pipeline: it
seeds a throwaway performance org, activates one real lever (token-trim) through
the product's own activation surface, sends paired holdback traffic until both
arms clear the >=30-sample gate, then asserts the A/B reports non-zero MEASURED
savings via ``compute_verified_savings`` — never by writing savings directly. It
cleans up the throwaway org and fails clearly on missing prices, entitlements,
policy config, or sample counts.

    .venv/bin/python scripts/walkthrough_traffic.py --policy --requests 140

Pricing note: cache/routing savings are derived from the pricing catalog. Run
``make sync-prices`` once so gpt-4o / gpt-4o-mini are priced, otherwise cost and
savings render as unpriced.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

# Make the backend package importable when run as scripts/walkthrough_traffic.py
# (only the --seed path touches it; the HTTP path is pure stdlib).
_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

# SDK-tagged by default so the *Production SDK* onboarding path verifies. The SDK
# path only clears when traffic arrives tagged as SDK traffic; base-URL mode omits
# this header (see --base-url-mode).
DEFAULT_CLIENT = "@varsten/openai@0.1.0"

MODELS = ["gpt-4o-mini", "gpt-4o-mini", "gpt-4o-mini", "gpt-4o"]
FEATURES = ["support_agent", "summarizer", "classifier", "search_rerank"]
TEAMS = ["support", "growth", "platform"]

# A small pool of stable prompts. Reusing them is what produces exact-cache hits,
# and therefore directly-measured savings, on the optimized arm.
CACHEABLE_PROMPTS = [
    "Summarize our refund policy in two sentences.",
    "Classify this ticket: 'my card was charged twice'.",
    "Draft a friendly reply asking the customer for their order number.",
    "What is the status of a shipment that is 'in transit'?",
]


def _open_http_request(req: urllib.request.Request, timeout: float):
    parsed = urllib.parse.urlparse(req.full_url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"unsupported URL scheme: {parsed.scheme}")
    return urllib.request.urlopen(req, timeout=timeout)  # nosec B310


def _post_completion(
    api_base: str,
    key: str,
    *,
    prompt: str,
    model: str,
    feature: str,
    team: str,
    client: str | None,
    timeout: float,
    extra_meta: dict | None = None,
) -> tuple[int, str]:
    """Send one chat completion through the proxy. Returns (status, cache-label)."""
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}]}).encode("utf-8")
    meta = {"environment": "production", "feature": feature, "team": team, "workflow": feature}
    if extra_meta:
        meta.update(extra_meta)
    metadata = json.dumps(meta)
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "X-Varsten-Metadata": metadata,
    }
    if client:
        headers["X-Varsten-Client"] = client
    req = urllib.request.Request(f"{api_base}/v1/chat/completions", data=body, headers=headers, method="POST")
    try:
        with _open_http_request(req, timeout) as resp:
            return resp.status, resp.headers.get("X-Varsten-Cache", "?")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")[:200]


def _run_traffic(args: argparse.Namespace, key: str) -> None:
    client = None if args.base_url_mode else args.client
    rng = random.Random(args.seed_value)  # nosec B311
    total = 1 if args.first_only else args.count

    sent = 0
    hits = 0
    errors = 0
    print(f"Sending {total} request(s) to {args.api_base} (client={client or 'base-url'})…")
    for i in range(total):
        cacheable = rng.random() < args.cache_ratio
        prompt = rng.choice(CACHEABLE_PROMPTS) if cacheable else f"[{uuid.uuid4()}] one-off question {i}"
        status, cache = _post_completion(
            args.api_base,
            key,
            prompt=prompt,
            model=rng.choice(MODELS),
            feature=rng.choice(FEATURES),
            team=rng.choice(TEAMS),
            client=client,
            timeout=args.timeout,
        )
        sent += 1
        if status >= 400:
            errors += 1
            if errors <= 3:
                print(f"  request {i}: HTTP {status} -> {cache}")
        elif cache == "hit":
            hits += 1
        if args.pace_ms:
            time.sleep(args.pace_ms / 1000.0)

    print(f"Done: {sent} sent, {hits} cache hit(s), {errors} error(s).")


def _read_snapshot(api_base: str, key: str, timeout: float) -> None:
    req = urllib.request.Request(
        f"{api_base}/v1/dashboard/snapshot?period=month",
        headers={"Authorization": f"Bearer {key}"},
    )
    try:
        with _open_http_request(req, timeout) as resp:
            snap = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        print(f"Could not read dashboard snapshot: HTTP {exc.code}")
        return

    print("\nLive dashboard snapshot (same numbers the UI renders):")
    print(f"  mode:  {snap.get('mode')}  (empty -> spend_only/measured means traffic landed)")
    for kpi in snap.get("kpis", []):
        print(f"  {kpi.get('label', kpi.get('key')):<24} {kpi.get('value')}")
    gross = snap.get("gross_savings_usd")
    if gross is not None:
        print(f"  gross savings            {gross}")


def _seed_workspace() -> tuple[object, object, str]:
    """Create a throwaway performance org + project + vaulted provider key.

    Mirrors scripts/load_benchmark.seed_workspace plus the onboarding connect step
    so the walkthrough works with no UI/Auth0. The provider key is vaulted through
    the same store the dashboard uses (PROVIDER_KEY_BACKEND, localdb in dev), and
    the fake provider accepts any string as a valid upstream key. Returns
    (org_id, project_id, plaintext_key). Imports are local so the stdlib traffic
    path has no app dependency.
    """
    from datetime import UTC, datetime

    from app.core.security import generate_api_key
    from app.db.session import get_session_factory
    from app.models import ApiKey, Organization, Project, ProviderConnection
    from app.proxy.keys import store_provider_key_for_project

    session = get_session_factory()()
    try:
        org = Organization(name=f"Walkthrough {uuid.uuid4().hex[:8]}", plan_tier="performance")
        session.add(org)
        session.flush()
        project = Project(organization_id=org.id, name="Walkthrough")
        session.add(project)
        session.flush()
        plaintext, prefix, key_hash = generate_api_key()
        session.add(ApiKey(project_id=project.id, name="walkthrough", key_prefix=prefix, key_hash=key_hash))
        # The key store updates an existing connection row (as the connect endpoint
        # does), so create the connected row first.
        session.add(
            ProviderConnection(
                organization_id=org.id,
                project_id=project.id,
                provider="openai",
                connection_method="local_db_encrypted",
                status="connected",
                last_verified_at=datetime.now(UTC),
            )
        )
        session.commit()
        org_id, project_id = org.id, project.id
    finally:
        session.close()

    try:
        store_provider_key_for_project(project_id, "openai", "sk-fake-local-test")
    except Exception as exc:
        print(f"Warning: could not vault a provider key ({exc}). Proxy calls will 502.", file=sys.stderr)
    return org_id, project_id, plaintext


def _seed_project() -> str:
    _, _, key = _seed_workspace()
    return key


# --- --policy: prove the real measurement path (token-trim holdback A/B) -------

# The planner blocks the trim lever on risky/unknown routes by design, so proof
# traffic is tagged low-risk with a task type — exactly what a real integration
# sends. Without this the candidate is REJECTED and never enters the experiment.
_POLICY_META = {"risk_level": "low", "task_type": "support_summary"}

# Content differs per request (avoids exact + semantic cache, so each request
# reaches the trim experiment) while the large whitespace block is exactly what
# the trim lever collapses — so the treatment (trimmed) arm is genuinely cheaper.
# Sized so the per-request token delta yields a savings figure visible in dollars
# (not a sub-cent number that rounds to $0.00 on the dashboard).
_WHITESPACE_PAD = ("\n" + " " * 120) * 70


def _compressible_prompt(i: int) -> str:
    return f"Summarize support ticket {uuid.uuid4()} (topic {i % 20}):{_WHITESPACE_PAD}End of ticket {i}."


def _fail(org_id, message: str) -> int:
    """Clean up the throwaway org and abort with a clear message."""
    if org_id is not None:
        _cleanup_org(org_id)
    print(f"\nFAILED: {message}", file=sys.stderr)
    return 1


def _cleanup_org(org_id) -> None:
    from sqlalchemy import delete

    from app.db.session import get_session_factory
    from app.models import Organization

    session = get_session_factory()()
    try:
        session.execute(delete(Organization).where(Organization.id == org_id))
        session.commit()
    finally:
        session.close()


def _configure_trim_policy(org_id, project_id, model: str, holdback: float) -> None:
    """Activate a token-trim lever through the product's own activation function
    (the same one the apply-recommendation endpoint calls), then open the canary
    rollout to 100% and widen the holdback so both arms fill in test volume."""
    from datetime import UTC, datetime
    from decimal import Decimal

    from app.db.session import get_session_factory
    from app.models import Organization, Project, Recommendation
    from app.proxy.trim import activate_trim_policy, clear_policy_cache

    session = get_session_factory()()
    try:
        project = session.get(Project, project_id)
        org = session.get(Organization, org_id)
        rec = Recommendation(
            organization_id=org.id,
            project_id=project.id,
            dedupe_key=f"walkthrough-trim-{uuid.uuid4().hex}",
            type="token_trim",
            lever="token_trim",
            target_type="model",
            target_key=model,
            title="Walkthrough token-trim proof",
            description="Trim collapsible prompt context on a low-risk route.",
            risk_level="low",
            confidence="high",
            related_model=model,
            status="applied",
        )
        session.add(rec)
        session.flush()
        policy = activate_trim_policy(session, project, rec, now=datetime.now(UTC))
        if policy is None:
            raise RuntimeError("activate_trim_policy returned no policy (missing related_model?)")
        # Fresh policies start on a canary ramp with a 5% holdback. For a bounded
        # test we open the rollout fully and widen the holdback so the control arm
        # fills to the >=30-sample gate in reasonable volume. This tunes the
        # experiment's fill rate; it does not fabricate savings.
        policy.rollout_percent = 100
        policy.holdback_percent = Decimal(str(holdback))
        session.commit()
        clear_policy_cache(project_id)
    finally:
        session.close()


def _measure_trim(project_id, model: str) -> dict:
    """Read the real attribution pipeline for the current month window."""
    from datetime import UTC, datetime

    from app.db.session import get_session_factory
    from app.proxy.experiment import compute_experiment
    from app.savings import month_end, month_start
    from app.savings_measurement import compute_verified_savings

    now = datetime.now(UTC)
    start, end = month_start(now), month_end(now)
    session = get_session_factory()()
    try:
        exp = compute_experiment(session, project_id, model, model, start, end)
        verified = compute_verified_savings(session, project_id, start, end)
    finally:
        session.close()
    return {"exp": exp, "verified": verified}


def _max_event_cost(project_id) -> object:
    from sqlalchemy import func, select

    from app.db.session import get_session_factory
    from app.models import UsageEvent

    session = get_session_factory()()
    try:
        return session.scalar(select(func.max(UsageEvent.cost_usd)).where(UsageEvent.project_id == project_id))
    finally:
        session.close()


def _send_trim_batch(args, key: str, start_i: int, n: int) -> int:
    """Send n unique compressible requests on the trim model. Returns error count."""
    errors = 0
    for i in range(start_i, start_i + n):
        status, detail = _post_completion(
            args.api_base,
            key,
            prompt=_compressible_prompt(i),
            model=args.policy_model,
            feature="walkthrough_proof",
            team="platform",
            client=None if args.base_url_mode else args.client,
            timeout=args.timeout,
            extra_meta=_POLICY_META,
        )
        if status >= 400:
            errors += 1
            if errors <= 3:
                print(f"  request {i}: HTTP {status} -> {detail}")
    return errors


def _run_policy_proof(args) -> int:
    from decimal import Decimal

    MIN_ARM = 30
    warmup = 10
    total = max(args.requests, warmup + 20)
    est_control = int(total * args.holdback)
    est_treatment = total - est_control

    print("== Policy proof: token-trim holdback A/B (real measurement path) ==")
    print(f"Model: {args.policy_model}   holdback: {args.holdback:.0%}   requests: {total}")
    print(
        f"Expected split ~{est_control} control / ~{est_treatment} treatment. Both arms need "
        f">={MIN_ARM} samples before the A/B reports measured savings."
    )
    if est_control < MIN_ARM + 5:
        print(
            f"Warning: ~{est_control} control samples is close to the {MIN_ARM} gate. "
            f"Raise --requests or lower --holdback if it falls short.",
            file=sys.stderr,
        )

    org_id, project_id, key = _seed_workspace()
    print(f"Seeded throwaway performance project. Key: {key}")
    _configure_trim_policy(org_id, project_id, args.policy_model, args.holdback)
    print("Activated a token-trim policy via the product's activate_trim_policy (rollout 100%).")

    # Warm-up + preflight: prices present and the lever is actually experimenting.
    print(f"Warm-up: {warmup} requests…")
    if _send_trim_batch(args, key, 0, warmup) == warmup:
        return _fail(org_id, "every warm-up request errored; is the backend + fake provider up?")
    max_cost = _max_event_cost(project_id)
    if not max_cost or Decimal(str(max_cost)) <= 0:
        return _fail(
            org_id,
            f"model '{args.policy_model}' is not priced (derived cost is 0/null). Run 'make sync-prices'.",
        )
    warm = _measure_trim(project_id, args.policy_model)["exp"]
    if (warm["control_requests"] or 0) + (warm["treatment_requests"] or 0) == 0:
        return _fail(
            org_id,
            "no holdback experiment events recorded — the trim lever is not applying. "
            "Check the org is on Optimize (optimization enabled) and the policy is active.",
        )

    print(f"Sending the remaining {total - warmup} requests…")
    _send_trim_batch(args, key, warmup, total - warmup)

    result = _measure_trim(project_id, args.policy_model)
    exp, verified = result["exp"], result["verified"]
    n_c, n_t = exp["control_requests"] or 0, exp["treatment_requests"] or 0
    gross = verified["holdback_measured_usd"]
    net = verified["verified_savings_usd"]
    has_signal = bool(verified["holdback_has_signal"])

    print("\n-- Real attribution pipeline (compute_verified_savings / compute_experiment) --")
    print(f"  control arm:   {n_c} requests, avg cost {exp['control_avg_cost_usd']}")
    print(f"  treatment arm: {n_t} requests, avg cost {exp['treatment_avg_cost_usd']}")
    print(f"  measured savings / request: {exp['savings_per_request_usd']}")
    print(f"  has_signal (>= {MIN_ARM}/arm): {has_signal}")
    print(f"  holdback measured (gross):   {gross}")
    print(f"  verified savings (net):      {net}")
    print(f"  95% CI (gross): [{verified['holdback_ci_low_usd']}, {verified['holdback_ci_high_usd']}]")

    if not has_signal:
        return _fail(
            org_id,
            f"holdback has no signal yet: control={n_c}, treatment={n_t} (need >={MIN_ARM} each). "
            f"Re-run with a larger --requests (e.g. {int(total * 1.5)}).",
        )
    if Decimal(str(gross)) <= 0:
        return _fail(
            org_id,
            "arms reached signal but measured savings are 0 — the treatment arm was not cheaper. "
            "The trim lever produced no token reduction (prompt not compressible?).",
        )
    net_positive = Decimal(str(net)) > 0

    print("\n-- What the product surfaces (verified by the same pipeline) --")
    print("  Dashboard  http://localhost:3000/dashboard")
    print(f"    Gross Savings:        {gross}")
    print(f"    Net Realized Savings: {net}  ({'positive' if net_positive else 'not positive'})")
    print("  Proof      http://localhost:3000/proof/savings  and  /proof/attribution")
    print("    Measurement method:   A/B holdback")
    print(
        f"    Verified savings:     {verified['verified_gross_savings_usd']} (gross), {net} (net after holdback cost)"
    )
    print(
        "  Note: this is a throwaway org with no Auth0 user, so it is not viewable in the UI; "
        "the numbers above are the same ones the Dashboard/Proof render. Run the same lever on your "
        "onboarded project to see them in the browser."
    )
    if not net_positive:
        print(
            f"\nNet is not positive because a {args.holdback:.0%} holdback pays full price on the "
            "control arm. Gross measured savings are real; lower --holdback or raise --requests for a "
            "positive net headline.",
            file=sys.stderr,
        )

    if args.keep_org:
        print(f"\nLeaving throwaway org in place (--keep-org). Key: {key}")
    else:
        _cleanup_org(org_id)
        print("\nCleaned up the throwaway org.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Drive live proxy traffic for the self-serve walkthrough.")
    parser.add_argument("--api-base", default="http://localhost:8000", help="Varsten API base URL.")
    parser.add_argument("--key", help="Project vk_ key (from the onboarding UI). Omit with --seed.")
    parser.add_argument("--seed", action="store_true", help="Seed a throwaway performance project + key and use it.")
    parser.add_argument("--count", type=int, default=40, help="Number of requests to send.")
    parser.add_argument("--first-only", action="store_true", help="Send just the single verification request.")
    parser.add_argument(
        "--cache-ratio", type=float, default=0.6, help="Fraction of requests that reuse cacheable prompts."
    )
    parser.add_argument("--client", default=DEFAULT_CLIENT, help="X-Varsten-Client header (SDK-tagged traffic).")
    parser.add_argument(
        "--base-url-mode", action="store_true", help="Send base-URL traffic (omit the SDK client header)."
    )
    parser.add_argument("--pace-ms", type=float, default=0.0, help="Delay between requests, ms.")
    parser.add_argument("--timeout", type=float, default=15.0, help="Per-request timeout, seconds.")
    parser.add_argument("--seed-value", type=int, default=None, help="RNG seed for reproducible prompt selection.")
    # --policy: a self-contained proof of the measurement pipeline. Always uses a
    # throwaway org (it configures a lever and asserts on the result), separate
    # from the default onboarding/spend traffic above.
    parser.add_argument(
        "--policy",
        action="store_true",
        help="Configure one real lever (token-trim), send paired traffic, and assert measured savings.",
    )
    parser.add_argument("--requests", type=int, default=140, help="[--policy] total requests to send.")
    parser.add_argument("--holdback", type=float, default=0.3, help="[--policy] control-arm fraction (0-1).")
    parser.add_argument("--policy-model", default="gpt-4o", help="[--policy] model the trim lever targets.")
    parser.add_argument("--keep-org", action="store_true", help="[--policy] do not delete the throwaway org.")
    args = parser.parse_args()

    if args.policy:
        if args.key:
            parser.error("--policy always uses a throwaway org; do not pass --key")
        if not 0 < args.holdback < 1:
            parser.error("--holdback must be between 0 and 1")
        return _run_policy_proof(args)

    if args.seed:
        key = _seed_project()
        print(f"Seeded throwaway project. Key: {key}")
    elif args.key:
        key = args.key
    else:
        parser.error("provide --key vk_... or --seed")

    if not key.startswith("vk_"):
        print("Warning: key does not start with vk_; the proxy will reject it.", file=sys.stderr)

    _run_traffic(args, key)
    _read_snapshot(args.api_base, key, args.timeout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
