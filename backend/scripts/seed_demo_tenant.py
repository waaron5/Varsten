"""Demo tenant seeder: a realistic 30-day proxy narrative, written fast and safe.

This populates the shared demo organization with proxy-shaped ledger rows so every
Dashboard panel lights up with internally consistent numbers a buyer can trust.

How it differs from the older ``seed_demo.py``:
  * It writes the *proxy* telemetry the new Dashboard reads (``feature='proxy'``
    usage events carrying cache/holdback/saved_usd metadata), not ingestion-style
    workflow events.
  * It is strictly isolated. It only ever touches an organization flagged
    ``is_demo=True``; the structural flag (not a hard-coded UUID) is the kill switch.
  * It is idempotent. Each run wipes the demo project's data and regenerates a fresh
    30-day window ending today, so the tenant is pristine before every sales call.

Speed and cost: no LLM calls and no routing through the in-process proxy. Rows are
written straight through the ORM with backdated timestamps and costs computed from
real OpenAI list prices, so the run is lightning-fast and spends zero API credits.

Reconciliation contract (the thing under test): the per-lever SavingsAttribution
rows equal the current-month ledger ``saved_usd`` for that lever, so the Command
Center KPI (`saved_month`), the Margin chart (`savings-trend`), and the Proof page
all read the same number. Nothing here is painted on; every dollar traces to a row.

Usage:
    VARSTEN_ALLOW_DEMO_SEED=1 uv run python -m scripts.seed_demo_tenant
    uv run python -m scripts.seed_demo_tenant --yes --base 600
"""

from __future__ import annotations

import argparse
import os
import random
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.security import generate_api_key
from app.db.session import SessionLocal
from app.models import (
    ApiKey,
    BatchJob,
    EvalRun,
    EvalSampleResult,
    LeverConfig,
    Organization,
    OrgMembership,
    Project,
    ProxyCacheEntry,
    ProxyPolicy,
    Recommendation,
    RecommendationAction,
    ReplaySample,
    SavingsAttribution,
    UsageEvent,
    User,
)
from app.models.batch import STATUS_FINALIZED
from app.proxy.routing import ARM_CONTROL, ARM_TREATMENT
from app.savings import FEE_PERCENT, month_end, month_start

# --- demo identity ------------------------------------------------------------

DEMO_ORG_NAME = "Varsten Demo"
DEMO_PROJECT_NAME = "Production"

# --- shape parameters (the 30-day B2B curve) ----------------------------------

WINDOW_DAYS = 30
BASE_REQUESTS = 600  # day-one request volume; the curve grows from here
WEEKLY_GROWTH = Decimal("1.16")  # week-over-week growth, "up and to the right"
WEEKEND_MULT = 0.62  # weekend dip
JITTER = 0.08  # +/- daily noise so the curve is not a clean line

# Traffic mix per day. Cache and routing are the levers under measurement; plain is
# unoptimized premium traffic that establishes the baseline spend.
CACHE_SHARE = 0.55
ROUTING_SHARE = 0.30
# plain = remainder

HIT_RATE_START = 0.30  # exact-hash hit-rate inside the cache stream, day one
HIT_RATE_END = 0.62  # ... ramping up as the cache warms over the window
HOLDBACK = Decimal("0.15")  # fraction of routed traffic held back on the incumbent

# Objective response-health per arm. Treatment sits a hair below control but inside
# the drift tolerance (0.05), so the route reads "saving", never "drift".
CONTROL_OK_RATE = 0.985
TREATMENT_OK_RATE = 0.96

SEED = 1729  # deterministic: same call every time, so the demo is reproducible

# --- real-world OpenAI list pricing (USD per token) ---------------------------
# gpt-4o:      $5.00 / 1M input, $15.00 / 1M output
# gpt-4o-mini: $0.15 / 1M input,  $0.60 / 1M output
INCUMBENT = "gpt-4o"
CANDIDATE = "gpt-4o-mini"
RATES: dict[str, dict[str, Decimal]] = {
    "gpt-4o": {"in": Decimal("0.000005"), "out": Decimal("0.000015")},
    "gpt-4o-mini": {"in": Decimal("0.00000015"), "out": Decimal("0.0000006")},
}

_Q8 = Decimal("0.00000001")  # ledger cost precision (Numeric(18,8))
_CENTS = Decimal("0.01")


def _cost(model: str, in_tok: int, out_tok: int) -> Decimal:
    r = RATES[model]
    return (Decimal(in_tok) * r["in"] + Decimal(out_tok) * r["out"]).quantize(_Q8, rounding=ROUND_HALF_UP)


def _q_cents(value: Decimal) -> Decimal:
    return Decimal(value).quantize(_CENTS, rounding=ROUND_HALF_UP)


class DemoSafetyError(RuntimeError):
    """Raised when the seeder is asked to touch anything that is not the demo tenant."""


@dataclass
class DemoResult:
    org_id: uuid.UUID
    project_id: uuid.UUID
    api_key: str  # plaintext, shown once
    total_events: int
    month_events: int
    # Current-month ledger saved per lever, raw (pre-cent-rounding). The attribution
    # rows are _q_cents() of these, which is what the Dashboard reads back.
    cache_saved_month: Decimal
    routing_saved_month: Decimal
    batch_saved_month: Decimal

    @property
    def expected_saved_month(self) -> Decimal:
        """What the Dashboard `saved_month` KPI must equal: the sum of the
        per-lever attributions, each rounded to cents independently."""
        return _q_cents(self.cache_saved_month) + _q_cents(self.routing_saved_month) + _q_cents(self.batch_saved_month)


# --- isolation guardrails -----------------------------------------------------


def assert_demo_org(org: Organization | None) -> None:
    """Structural kill switch. Refuse to touch any organization not flagged demo.

    This is the whole safety story: deletes and regeneration are scoped to an org
    whose ``is_demo`` column is True. A real customer tenant (is_demo=False, the
    default) can never be selected here, so the seeder cannot wipe live data even if
    pointed at a production database."""
    if org is None or not org.is_demo:
        raise DemoSafetyError(
            f"refusing to seed: target org {getattr(org, 'id', None)} is not is_demo=True. "
            "The demo seeder only ever touches the demo tenant."
        )


def resolve_demo_org(db: Session) -> Organization:
    """Find the existing demo org or create one. If a non-demo org already owns the
    demo name, refuse rather than risk colliding with a real tenant."""
    org = db.scalar(select(Organization).where(Organization.name == DEMO_ORG_NAME, Organization.is_demo.is_(True)))
    if org is not None:
        return org
    clash = db.scalar(select(Organization).where(Organization.name == DEMO_ORG_NAME))
    if clash is not None:
        raise DemoSafetyError(
            f"an organization named {DEMO_ORG_NAME!r} exists with is_demo=False; refusing to repurpose it."
        )
    org = Organization(name=DEMO_ORG_NAME, is_demo=True)
    db.add(org)
    db.flush()
    return org


def _ensure_project_and_key(db: Session, org: Organization) -> tuple[Project, ApiKey, str]:
    project = db.scalar(select(Project).where(Project.organization_id == org.id))
    if project is None:
        project = Project(organization_id=org.id, name=DEMO_PROJECT_NAME)
        db.add(project)
        db.flush()
    # Always mint a fresh key so the plaintext can be surfaced (hashes are one-way).
    db.execute(delete(ApiKey).where(ApiKey.project_id == project.id))
    plaintext, prefix, key_hash = generate_api_key()
    api_key = ApiKey(project_id=project.id, name="demo", key_prefix=prefix, key_hash=key_hash)
    db.add(api_key)
    db.flush()
    return project, api_key, plaintext


def wipe_demo_data(db: Session, org: Organization, project: Project) -> None:
    """Idempotency: delete the demo project's generated data so a re-run starts
    clean. Guarded by the structural is_demo assertion and scoped to the demo
    project_id, so the blast radius is exactly one demo project and nothing else."""
    assert_demo_org(org)  # belt and suspenders: never delete outside a demo org
    pid = project.id

    # Eval sample results hang off eval runs; clear children before parents.
    run_ids = list(db.scalars(select(EvalRun.id).where(EvalRun.project_id == pid)))
    if run_ids:
        db.execute(delete(EvalSampleResult).where(EvalSampleResult.eval_run_id.in_(run_ids)))

    for model in (
        UsageEvent,
        BatchJob,
        ProxyPolicy,
        ProxyCacheEntry,
        ReplaySample,
        EvalRun,
        SavingsAttribution,
        RecommendationAction,
        Recommendation,
        LeverConfig,
    ):
        db.execute(delete(model).where(model.project_id == pid))
    db.flush()


# --- the 30-day curve ---------------------------------------------------------


def _daily_requests(day_index: int, day: datetime, base: int, rng: random.Random) -> int:
    """Request count for one day: week-over-week growth, a weekend dip, and noise."""
    week = day_index // 7
    volume = Decimal(base) * (WEEKLY_GROWTH**week)
    if day.weekday() >= 5:
        volume *= Decimal(str(WEEKEND_MULT))
    volume *= Decimal(str(1.0 + rng.uniform(-JITTER, JITTER)))
    return max(1, int(volume))


def _tokens(rng: random.Random, *, big: bool) -> tuple[int, int]:
    """Token counts per call. Big = RAG/agent context on the premium model."""
    if big:
        return rng.randint(3500, 7000), rng.randint(350, 750)
    return rng.randint(1200, 2600), rng.randint(200, 480)


def _event(
    *,
    project: Project,
    org_id: uuid.UUID,
    api_key_id: uuid.UUID,
    model: str,
    in_tok: int,
    out_tok: int,
    cost: Decimal,
    latency_ms: int | None,
    metadata: dict,
    ts: datetime,
    idempotency_key: str,
) -> UsageEvent:
    return UsageEvent(
        project_id=project.id,
        organization_id=org_id,
        api_key_id=api_key_id,
        provider="openai",
        model=model,
        operation="chat_completion",
        request_type="chat_completion",
        feature="proxy",
        environment="production",
        input_tokens=in_tok,
        output_tokens=out_tok,
        cached_input_tokens=0,
        total_tokens=in_tok + out_tok,
        cost_usd=cost,
        reported_cost_usd=None,
        cost_source="catalog",
        pricing_status="priced",
        currency="USD",
        status="success",
        success=True,
        latency_ms=latency_ms,
        event_metadata=metadata,
        occurred_at=ts,
        event_timestamp=ts,
        received_at=ts,
        idempotency_key=idempotency_key,
    )


def build_demo(
    db: Session,
    *,
    base_requests: int = BASE_REQUESTS,
    now: datetime | None = None,
    attach_email: str | None = None,
) -> DemoResult:
    """Resolve (or create) the demo tenant, wipe it, and regenerate a fresh 30-day
    proxy narrative. Returns the identifiers and the reconciliation totals. Does not
    commit; the caller owns the transaction."""
    now = now or datetime.now(UTC)
    # Deterministic demo data, not security-sensitive randomness.
    rng = random.Random(SEED)  # nosec B311

    org = resolve_demo_org(db)
    assert_demo_org(org)
    project, api_key, plaintext = _ensure_project_and_key(db, org)
    wipe_demo_data(db, org, project)  # scoped to the project; leaves project + key intact

    if attach_email:
        _attach_member(db, org, attach_email)

    m_start = month_start(now)
    events: list[UsageEvent] = []
    cache_saved_month = Decimal("0")
    routing_saved_month = Decimal("0")
    seq = 0

    def _key() -> str:
        nonlocal seq
        seq += 1
        return f"demo-{seq:07d}"

    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    for i in range(WINDOW_DAYS):
        day = day_start - timedelta(days=WINDOW_DAYS - 1 - i)
        n = _daily_requests(i, day, base_requests, rng)
        hit_rate = HIT_RATE_START + (HIT_RATE_END - HIT_RATE_START) * (i / (WINDOW_DAYS - 1))

        n_cache = round(n * CACHE_SHARE)
        n_route = round(n * ROUTING_SHARE)
        n_plain = max(0, n - n_cache - n_route)

        # --- cache stream: exact-hash on the premium model ---
        n_hit = round(n_cache * hit_rate)
        for j in range(n_cache):
            ts = day + timedelta(seconds=rng.randint(0, 86399))
            in_tok, out_tok = _tokens(rng, big=True)
            full = _cost(INCUMBENT, in_tok, out_tok)
            if j < n_hit:
                # Served from cache: $0 spend, the full premium call avoided.
                events.append(
                    _event(
                        project=project,
                        org_id=org.id,
                        api_key_id=api_key.id,
                        model=INCUMBENT,
                        in_tok=in_tok,
                        out_tok=out_tok,
                        cost=Decimal("0"),
                        latency_ms=rng.randint(3, 14),
                        metadata={"proxy": True, "cache": "hit", "naive_cost_usd": str(full), "saved_usd": str(full)},
                        ts=ts,
                        idempotency_key=_key(),
                    )
                )
                if ts >= m_start:
                    cache_saved_month += full
            else:
                events.append(
                    _event(
                        project=project,
                        org_id=org.id,
                        api_key_id=api_key.id,
                        model=INCUMBENT,
                        in_tok=in_tok,
                        out_tok=out_tok,
                        cost=full,
                        latency_ms=rng.randint(620, 1150),
                        metadata={"proxy": True, "cache": "miss"},
                        ts=ts,
                        idempotency_key=_key(),
                    )
                )

        # --- routing stream: holdback A/B, gpt-4o (control) vs gpt-4o-mini (treatment) ---
        n_control = round(n_route * float(HOLDBACK))
        for j in range(n_route):
            ts = day + timedelta(seconds=rng.randint(0, 86399))
            in_tok, out_tok = _tokens(rng, big=True)
            inc_cost = _cost(INCUMBENT, in_tok, out_tok)
            if j < n_control:
                # Control arm: held back on the incumbent. Carries no savings.
                ok = rng.random() < CONTROL_OK_RATE
                events.append(
                    _event(
                        project=project,
                        org_id=org.id,
                        api_key_id=api_key.id,
                        model=INCUMBENT,
                        in_tok=in_tok,
                        out_tok=out_tok,
                        cost=inc_cost,
                        latency_ms=rng.randint(700, 1200),
                        metadata={
                            "proxy": True,
                            "cache": "miss",
                            "holdback": True,
                            "arm": ARM_CONTROL,
                            "experiment_from": INCUMBENT,
                            "experiment_to": CANDIDATE,
                            "quality_ok": ok,
                        },
                        ts=ts,
                        idempotency_key=_key(),
                    )
                )
            else:
                # Treatment arm: routed to the cheaper model. Saving = avoided delta.
                cand_cost = _cost(CANDIDATE, in_tok, out_tok)
                saved = inc_cost - cand_cost
                ok = rng.random() < TREATMENT_OK_RATE
                events.append(
                    _event(
                        project=project,
                        org_id=org.id,
                        api_key_id=api_key.id,
                        model=CANDIDATE,
                        in_tok=in_tok,
                        out_tok=out_tok,
                        cost=cand_cost,
                        latency_ms=rng.randint(420, 760),
                        metadata={
                            "proxy": True,
                            "cache": "miss",
                            "routed": True,
                            "routed_from": INCUMBENT,
                            "routed_to": CANDIDATE,
                            "naive_cost_usd": str(inc_cost),
                            "saved_usd": str(saved),
                            "holdback": True,
                            "arm": ARM_TREATMENT,
                            "experiment_from": INCUMBENT,
                            "experiment_to": CANDIDATE,
                            "quality_ok": ok,
                        },
                        ts=ts,
                        idempotency_key=_key(),
                    )
                )
                if ts >= m_start:
                    routing_saved_month += saved

        # --- plain stream: unoptimized premium traffic (baseline spend) ---
        for _ in range(n_plain):
            ts = day + timedelta(seconds=rng.randint(0, 86399))
            in_tok, out_tok = _tokens(rng, big=True)
            events.append(
                _event(
                    project=project,
                    org_id=org.id,
                    api_key_id=api_key.id,
                    model=INCUMBENT,
                    in_tok=in_tok,
                    out_tok=out_tok,
                    cost=_cost(INCUMBENT, in_tok, out_tok),
                    latency_ms=rng.randint(700, 1200),
                    metadata={"proxy": True, "cache": "miss"},
                    ts=ts,
                    idempotency_key=_key(),
                )
            )

    # --- batching: a handful of bulk jobs across the window ---
    batch_saved_month = _build_batches(
        db,
        events,
        project=project,
        org_id=org.id,
        api_key_id=api_key.id,
        day_start=day_start,
        m_start=m_start,
        rng=rng,
        key_fn=_key,
    )

    db.bulk_save_objects(events)
    db.flush()

    month_events = sum(1 for e in events if e.received_at >= m_start)

    # --- the active route the proxy is "executing" (drives the Quality table) ---
    db.add(
        ProxyPolicy(
            organization_id=org.id,
            project_id=project.id,
            lever="cheaper_model",
            target_type="model",
            target_key=INCUMBENT,
            enabled=True,
            holdback_percent=HOLDBACK,
            params={"candidate_model": CANDIDATE},
            activated_at=day_start - timedelta(days=WINDOW_DAYS - 2),
        )
    )

    # --- attributions + lever configs: reconciled to the current-month ledger ---
    _write_attribution(db, org, project, "semantic_cache", "direct", cache_saved_month, m_start, now)
    _write_attribution(db, org, project, "cheaper_model", "holdback", routing_saved_month, m_start, now)
    _write_attribution(db, org, project, "batching", "direct", batch_saved_month, m_start, now)

    _write_lever(db, org, project, "semantic_cache", cache_saved_month, "auto", None)
    _write_lever(
        db,
        org,
        project,
        "cheaper_model",
        routing_saved_month,
        "approve",
        Decimal(str(round((TREATMENT_OK_RATE - CONTROL_OK_RATE) * 100, 2))),
    )
    _write_lever(db, org, project, "batching", batch_saved_month, "auto", None)

    db.flush()
    return DemoResult(
        org_id=org.id,
        project_id=project.id,
        api_key=plaintext,
        total_events=len(events),
        month_events=month_events,
        cache_saved_month=cache_saved_month,
        routing_saved_month=routing_saved_month,
        batch_saved_month=batch_saved_month,
    )


def _build_batches(
    db: Session,
    events: list[UsageEvent],
    *,
    project: Project,
    org_id: uuid.UUID,
    api_key_id: uuid.UUID,
    day_start: datetime,
    m_start: datetime,
    rng: random.Random,
    key_fn,
) -> Decimal:
    """A few finalized batch jobs spread across the window. Each gets one aggregate
    ledger event (so its saving flows into savings-trend) plus a BatchJob row (so the
    batching volume panel reads the request counts). Returns current-month saved."""
    batch_saved_month = Decimal("0")
    # One batch roughly weekly.
    for offset in (26, 19, 12, 5, 1):
        created = day_start - timedelta(days=offset, hours=rng.randint(0, 12))
        req_count = rng.randint(400, 1200)
        in_tok = req_count * rng.randint(900, 1500)
        out_tok = req_count * rng.randint(150, 320)
        # Batch endpoints bill at ~50% of synchronous list price; the saving is the
        # avoided half of the synchronous premium-model cost.
        sync_cost = _cost(INCUMBENT, in_tok, out_tok)
        actual_cost = (sync_cost * Decimal("0.5")).quantize(_Q8, rounding=ROUND_HALF_UP)
        saved = sync_cost - actual_cost

        db.add(
            BatchJob(
                organization_id=org_id,
                project_id=project.id,
                api_key_id=api_key_id,
                provider="openai",
                endpoint="/v1/chat/completions",
                completion_window="24h",
                status=STATUS_FINALIZED,
                input_storage_key=f"demo://batch/{uuid.uuid4()}",
                request_count=req_count,
                input_tokens=in_tok,
                output_tokens=out_tok,
                actual_cost_usd=actual_cost,
                naive_cost_usd=sync_cost,
                saved_usd=saved,
                submitted_at=created,
                completed_at=created + timedelta(hours=2),
                expires_at=created + timedelta(days=1),
                created_at=created,
            )
        )
        events.append(
            _event(
                project=project,
                org_id=org_id,
                api_key_id=api_key_id,
                model=INCUMBENT,
                in_tok=in_tok,
                out_tok=out_tok,
                cost=actual_cost,
                latency_ms=None,
                metadata={
                    "proxy": True,
                    "batch": True,
                    "lever": "batching",
                    "naive_cost_usd": str(sync_cost),
                    "saved_usd": str(saved),
                },
                ts=created,
                idempotency_key=key_fn(),
            )
        )
        if created >= m_start:
            batch_saved_month += saved
    return batch_saved_month


def _write_attribution(
    db: Session,
    org: Organization,
    project: Project,
    lever: str,
    method: str,
    gross_raw: Decimal,
    m_start: datetime,
    now: datetime,
) -> None:
    """One SavingsAttribution for the current month whose gross equals the lever's
    current-month ledger savings (rounded to cents). This is the row the Command
    Center and Proof read, and the reason their numbers reconcile with the ledger."""
    gross = _q_cents(gross_raw)
    fee = _q_cents(gross * FEE_PERCENT)
    net = gross - fee
    db.add(
        SavingsAttribution(
            organization_id=org.id,
            project_id=project.id,
            lever=lever,
            measurement_method=method,
            status="measured" if method == "holdback" else "estimated",
            period_start=m_start,
            period_end=month_end(now),
            counterfactual_spend_usd=None,
            actual_spend_usd=None,
            gross_savings_usd=gross,
            varsten_fee_usd=fee,
            net_savings_usd=net,
            confidence_low_usd=_q_cents(gross * Decimal("0.90")),
            confidence_high_usd=_q_cents(gross * Decimal("1.10")),
            notes=f"Demo: {lever} current-month savings, derived from the proxy ledger ({method}).",
        )
    )


def _write_lever(
    db: Session,
    org: Organization,
    project: Project,
    lever: str,
    saved_raw: Decimal,
    automation_mode: str,
    quality_delta_percent: Decimal | None,
) -> None:
    db.add(
        LeverConfig(
            organization_id=org.id,
            project_id=project.id,
            lever=lever,
            enabled=True,
            automation_mode=automation_mode,
            savings_to_date_usd=_q_cents(saved_raw),
            quality_delta_percent=quality_delta_percent,
        )
    )


def _attach_member(db: Session, org: Organization, email: str) -> None:
    """Attach a dev user to the demo org so they see it after signing in."""
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email)
        db.add(user)
        db.flush()
    existing = db.scalar(
        select(OrgMembership).where(OrgMembership.organization_id == org.id, OrgMembership.user_id == user.id)
    )
    if existing is None:
        db.add(OrgMembership(organization_id=org.id, user_id=user.id, role="owner"))
        db.flush()


# --- CLI ----------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the isolated demo tenant with a 30-day proxy narrative.")
    parser.add_argument("--yes", action="store_true", help="confirm the destructive re-seed of the demo tenant")
    parser.add_argument("--base", type=int, default=BASE_REQUESTS, help="day-one request volume")
    parser.add_argument("--attach-email", default=None, help="attach this user to the demo org")
    args = parser.parse_args()

    if not args.yes and os.getenv("VARSTEN_ALLOW_DEMO_SEED") != "1":
        parser.error("refusing: pass --yes or set VARSTEN_ALLOW_DEMO_SEED=1 to confirm the destructive re-seed.")

    db = SessionLocal()
    try:
        result = build_demo(db, base_requests=args.base, attach_email=args.attach_email)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    print("Demo tenant seeded.")
    print(f"  org_id        {result.org_id}")
    print(f"  project_id    {result.project_id}")
    print(f"  api_key       {result.api_key}")
    print(f"  events        {result.total_events} total, {result.month_events} this month")
    print("  current-month savings (reconciles with the Dashboard):")
    print(f"    semantic_cache  {_q_cents(result.cache_saved_month)}")
    print(f"    cheaper_model   {_q_cents(result.routing_saved_month)}")
    print(f"    batching        {_q_cents(result.batch_saved_month)}")
    print(f"    saved_month     {result.expected_saved_month}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
