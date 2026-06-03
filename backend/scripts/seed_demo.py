"""Seed a deterministic Varsten demo workspace.

Run after migrations:

    uv run python -m scripts.seed_demo

The data is intentionally shaped around the product guide: it creates measured
usage, five lever-specific savings opportunities, proof rows, guardrail config,
customer economics, and admin connection state. Re-running is safe; stable keys
and idempotency values prevent duplicate demo records.
"""
from __future__ import annotations

import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.security import hash_api_key
from app.db.session import SessionLocal
from app.models import (
    AlertRule,
    ApiKey,
    BudgetRule,
    CustomerEconomics,
    LeverConfig,
    ModelCatalog,
    ModelPrice,
    OrgMembership,
    Organization,
    Project,
    ProviderConnection,
    QualityGuardrail,
    Recommendation,
    RecommendationAction,
    SavingsAttribution,
    UsageEvent,
    User,
)
from app.pricing.service import price_usage_event
from app.recommendations import refresh_recommendations
from app.savings import month_end, month_start, record_applied_savings

DEMO_ORG_NAME = "Varsten Demo Co"
DEMO_PROJECT_NAME = "Production AI"
DEMO_USER_EMAIL = "demo@varsten.local"
DEMO_API_KEY = "vk_demo_varsten_local_key"

# Lever automation modes only. Savings-to-date is NOT seeded; it is derived from
# the recommendations the seed applies, just like in the running product.
LEVER_MODES = {
    "smart_routing": "approve",
    "semantic_cache": "auto",
    "token_trim": "auto",
    "cheaper_model": "approve",
    "batching": "auto",
}

# How many of the highest-value open recommendations to "apply" so the demo shows
# realized savings and Proof while leaving the rest in the decision queue.
DEMO_APPLY_LIMIT = 3


@dataclass(frozen=True)
class PriceSeed:
    model_key: str
    provider: str
    input_cost: Decimal
    output_cost: Decimal
    tier: str
    cheaper_substitute_key: str | None = None
    cache_read_cost: Decimal | None = None
    batch_input_cost: Decimal | None = None
    batch_output_cost: Decimal | None = None


@dataclass(frozen=True)
class UsageSeed:
    key: str
    provider: str
    model: str
    request_type: str
    feature: str
    customer_id: str
    user_id: str
    team: str
    department: str
    environment: str
    count: int
    input_tokens: int
    output_tokens: int
    latency_ms: int
    success: bool = True
    error_code: str | None = None
    metadata: dict | None = None


# Public list prices (per token) as of mid-2026, mirrored as reference data so the
# demo is deterministic and offline. In production these come from `make
# sync-prices` against the live feed; the math is identical either way.
PRICES = [
    PriceSeed(
        model_key="gpt-4o",
        provider="openai",
        input_cost=Decimal("0.0000025"),   # $2.50 / 1M
        output_cost=Decimal("0.00001"),    # $10.00 / 1M
        tier="frontier",
        cheaper_substitute_key="gpt-4o-mini",
        cache_read_cost=Decimal("0.00000125"),  # $1.25 / 1M
    ),
    PriceSeed(
        model_key="gpt-4o-mini",
        provider="openai",
        input_cost=Decimal("0.00000015"),  # $0.15 / 1M
        output_cost=Decimal("0.0000006"),  # $0.60 / 1M
        tier="small",
        cache_read_cost=Decimal("0.000000075"),  # $0.075 / 1M
        batch_input_cost=Decimal("0.000000075"),
        batch_output_cost=Decimal("0.0000003"),
    ),
    PriceSeed(
        model_key="claude-3-5-sonnet",
        provider="anthropic",
        input_cost=Decimal("0.000003"),    # $3.00 / 1M
        output_cost=Decimal("0.000015"),   # $15.00 / 1M
        tier="frontier",
        cheaper_substitute_key="claude-3-haiku",
        cache_read_cost=Decimal("0.0000003"),  # $0.30 / 1M
    ),
    PriceSeed(
        model_key="claude-3-haiku",
        provider="anthropic",
        input_cost=Decimal("0.00000025"),  # $0.25 / 1M
        output_cost=Decimal("0.00000125"), # $1.25 / 1M
        tier="small",
        cache_read_cost=Decimal("0.00000003"),  # $0.03 / 1M
        batch_input_cost=Decimal("0.000000125"),
        batch_output_cost=Decimal("0.000000625"),
    ),
]


def _month_start(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _month_end(now: datetime) -> datetime:
    return (_month_start(now) + timedelta(days=32)).replace(day=1) - timedelta(seconds=1)


def _get_or_create_org(db: Session) -> Organization:
    org = db.scalar(select(Organization).where(Organization.name == DEMO_ORG_NAME))
    if org is None:
        org = Organization(
            name=DEMO_ORG_NAME,
            monthly_spend_budget_usd=Decimal("95000.00"),
        )
        db.add(org)
        db.flush()
    else:
        org.monthly_spend_budget_usd = Decimal("95000.00")
    return org


def _get_or_create_project(db: Session, org: Organization) -> Project:
    project = db.scalar(
        select(Project).where(
            Project.organization_id == org.id,
            Project.name == DEMO_PROJECT_NAME,
        )
    )
    if project is None:
        project = Project(organization_id=org.id, name=DEMO_PROJECT_NAME)
        db.add(project)
        db.flush()
    return project


def _get_or_create_user(db: Session, org: Organization) -> User:
    user = db.scalar(select(User).where(User.email == DEMO_USER_EMAIL))
    if user is None:
        user = User(
            email=DEMO_USER_EMAIL,
            name="Demo Owner",
            auth_provider_subject="demo|varsten-local",
        )
        db.add(user)
        db.flush()
    membership = db.scalar(
        select(OrgMembership).where(
            OrgMembership.organization_id == org.id,
            OrgMembership.user_id == user.id,
        )
    )
    if membership is None:
        db.add(OrgMembership(organization_id=org.id, user_id=user.id, role="owner"))
    else:
        membership.role = "owner"
    return user


def _get_or_create_api_key(db: Session, project: Project) -> ApiKey:
    key_hash = hash_api_key(DEMO_API_KEY)
    api_key = db.scalar(select(ApiKey).where(ApiKey.key_hash == key_hash))
    if api_key is None:
        api_key = ApiKey(
            project_id=project.id,
            name="Demo ingestion key",
            key_prefix=DEMO_API_KEY[:7],
            key_hash=key_hash,
        )
        db.add(api_key)
        db.flush()
    return api_key


def _seed_prices(db: Session) -> None:
    demo_effective_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
    for price in PRICES:
        catalog = db.scalar(
            select(ModelCatalog).where(
                ModelCatalog.model_key == price.model_key,
                ModelCatalog.provider == price.provider,
            )
        )
        if catalog is None:
            catalog = ModelCatalog(
                model_key=price.model_key,
                provider=price.provider,
                mode="chat",
                tier=price.tier,
                supports_function_calling=True,
                cheaper_substitute_key=price.cheaper_substitute_key,
                source="demo",
            )
            db.add(catalog)
        else:
            catalog.mode = "chat"
            catalog.tier = price.tier
            catalog.supports_function_calling = True
            catalog.cheaper_substitute_key = price.cheaper_substitute_key
            catalog.source = "demo"

        latest = db.scalar(
            select(ModelPrice)
            .where(
                ModelPrice.model_key == price.model_key,
                ModelPrice.provider == price.provider,
            )
            .order_by(ModelPrice.effective_at.desc())
            .limit(1)
        )
        if (
            latest is None
            or latest.input_cost_per_token != price.input_cost
            or latest.output_cost_per_token != price.output_cost
            or latest.cache_read_input_token_cost != price.cache_read_cost
            or latest.input_cost_per_token_batch != price.batch_input_cost
            or latest.output_cost_per_token_batch != price.batch_output_cost
        ):
            db.add(
                ModelPrice(
                    model_key=price.model_key,
                    provider=price.provider,
                    input_cost_per_token=price.input_cost,
                    output_cost_per_token=price.output_cost,
                    cache_read_input_token_cost=price.cache_read_cost,
                    input_cost_per_token_batch=price.batch_input_cost,
                    output_cost_per_token_batch=price.batch_output_cost,
                    source="demo",
                    effective_at=demo_effective_at,
                )
            )
        elif latest.source == "demo" and latest.effective_at > demo_effective_at:
            latest.effective_at = demo_effective_at
    db.flush()


def _event(
    db: Session,
    org: Organization,
    project: Project,
    api_key: ApiKey,
    *,
    key: str,
    provider: str,
    model: str,
    request_type: str,
    feature: str,
    customer_id: str,
    user_id: str,
    team: str,
    department: str,
    environment: str,
    input_tokens: int,
    output_tokens: int,
    occurred_at: datetime,
    latency_ms: int,
    success: bool = True,
    error_code: str | None = None,
    metadata: dict | None = None,
) -> bool:
    existing = db.scalar(
        select(UsageEvent).where(
            UsageEvent.project_id == project.id,
            UsageEvent.idempotency_key == key,
        )
    )

    cost, cost_source, pricing_status, price_version_id = price_usage_event(
        db,
        organization_id=org.id,
        model_key=model,
        provider=provider,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_input_tokens=0,
        reported_cost_usd=None,
        at=occurred_at,
    )
    values = {
        "organization_id": org.id,
        "project_id": project.id,
        "api_key_id": api_key.id,
        "provider": provider,
        "model": model,
        "operation": request_type,
        "request_type": request_type,
        "workflow": feature,
        "feature": feature,
        "external_user_id": user_id,
        "user_id": user_id,
        "customer_id": customer_id,
        "team": team,
        "department": department,
        "environment": environment,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "cost_usd": cost,
        "cost_source": cost_source,
        "pricing_status": pricing_status,
        "price_version_id": price_version_id,
        "currency": "USD",
        "idempotency_key": key,
        "status": "success" if success else "error",
        "success": success,
        "error_code": error_code,
        "latency_ms": latency_ms,
        "occurred_at": occurred_at,
        "event_timestamp": occurred_at,
        "received_at": occurred_at,
        "event_metadata": metadata or {},
    }
    if existing is not None:
        for field, value in values.items():
            setattr(existing, field, value)
        return False
    db.add(
        UsageEvent(
            **values,
        )
    )
    return True


def _seed_usage(db: Session, org: Organization, project: Project, api_key: ApiKey) -> int:
    now = datetime.now(timezone.utc)
    inserted = 0
    legacy_keys = [
        "demo:sr-expensive",
        "demo:sr-cheap",
        "demo:trim-1",
        "demo:cache-1",
        "demo:cache-2",
        "demo:cache-3",
        "demo:batch-1",
        "demo:cheap-model-1",
        "demo:nonprod-1",
        "demo:failed-1",
        "demo:unpriced-1",
    ]
    db.execute(
        delete(UsageEvent).where(
            UsageEvent.project_id == project.id,
            UsageEvent.idempotency_key.in_(legacy_keys),
        )
    )
    db.flush()

    rows = [
        # High-volume monthly traffic, not one-off toy calls. These rows make
        # spend, forecast, proof savings, and budget posture live on the same
        # enterprise scale while still keeping the seed deterministic.
        UsageSeed("sr-expensive", "openai", "gpt-4o", "support_chat", "support_bot", "cust_acme", "user", "support", "cx", "production", 110, 3_200_000, 700_000, 1280),
        UsageSeed("sr-cheap", "openai", "gpt-4o-mini", "support_chat", "support_bot", "cust_acme", "user", "support", "cx", "production", 160, 3_000_000, 680_000, 940),
        UsageSeed("trim", "openai", "gpt-4o-mini", "summarize_research", "research_agent", "cust_nova", "user", "product", "r_and_d", "production", 95, 12_000_000, 900_000, 1610),
        UsageSeed("cache", "openai", "gpt-4o-mini", "answer_faq", "support_bot", "cust_acme", "user", "support", "cx", "production", 240, 1_500_000, 500_000, 720, metadata={"semantic_cache_key": "faq:reset-password"}),
        UsageSeed("batch", "openai", "gpt-4o-mini", "nightly_export", "analytics_exports", "cust_zenith", "system", "data", "analytics", "production", 40, 62_000_000, 14_000_000, 5800, metadata={"batchable": "true"}),
        UsageSeed("cheap-model", "anthropic", "claude-3-5-sonnet", "classify_ticket", "ticket_triage", "cust_nova", "user", "support", "cx", "production", 75, 2_200_000, 300_000, 1120),
        UsageSeed("nonprod", "openai", "gpt-4o", "load_test", "eval_harness", "cust_internal", "engineer", "platform", "engineering", "staging", 20, 5_000_000, 1_200_000, 1330),
        UsageSeed("failed", "openai", "gpt-4o-mini", "support_chat", "support_bot", "cust_zenith", "user", "support", "cx", "production", 35, 1_800_000, 100_000, 2100, success=False, error_code="provider_timeout"),
        UsageSeed("unpriced", "openai", "unknown-frontier-demo", "prototype", "labs_agent", "cust_internal", "engineer", "labs", "r_and_d", "development", 12, 2_000_000, 400_000, 1800),
    ]
    window_minutes = 60 * 24 * max(now.day, 1)
    for row in rows:
        for index in range(row.count):
            minutes_ago = 5 + ((index * 37) % window_minutes)
            if _event(
                db,
                org,
                project,
                api_key,
                key=f"demo:{row.key}:{index + 1:04d}",
                provider=row.provider,
                model=row.model,
                request_type=row.request_type,
                feature=row.feature,
                customer_id=row.customer_id,
                user_id=f"{row.user_id}_{(index % 24) + 1}",
                team=row.team,
                department=row.department,
                environment=row.environment,
                input_tokens=row.input_tokens,
                output_tokens=row.output_tokens,
                occurred_at=now - timedelta(minutes=minutes_ago),
                latency_ms=row.latency_ms,
                success=row.success,
                error_code=row.error_code,
                metadata=row.metadata,
            ):
                inserted += 1
    return inserted


def _upsert_levers(db: Session, org: Organization, project: Project) -> None:
    # Create the lever configs with their automation modes. savings_to_date is
    # left at 0 here and filled in by record_applied_savings when the seed applies
    # recommendations, so the Levers screen shows derived totals, not constants.
    for lever, mode in LEVER_MODES.items():
        config = db.scalar(
            select(LeverConfig).where(
                LeverConfig.project_id == project.id,
                LeverConfig.lever == lever,
            )
        )
        if config is None:
            db.add(
                LeverConfig(
                    organization_id=org.id,
                    project_id=project.id,
                    lever=lever,
                    automation_mode=mode,
                )
            )
        else:
            config.enabled = True
            config.automation_mode = mode
            # Reset so the total is re-derived from this run's applied
            # recommendations, never carried over from a prior seed.
            config.savings_to_date_usd = Decimal("0")


def _upsert_guardrails(db: Session, org: Organization, project: Project) -> None:
    quality_rules = [
        ("support_chat", "mid", "golden_set", Decimal("0.96"), 2500),
        ("classify_ticket", "small", "structured_accuracy", Decimal("0.98"), 1500),
    ]
    for route, tier, gate, score, latency in quality_rules:
        rule = db.scalar(
            select(QualityGuardrail).where(
                QualityGuardrail.project_id == project.id,
                QualityGuardrail.route == route,
            )
        )
        if rule is None:
            db.add(
                QualityGuardrail(
                    organization_id=org.id,
                    project_id=project.id,
                    route=route,
                    min_model_tier=tier,
                    eval_gate=gate,
                    min_eval_score=score,
                    max_latency_ms=latency,
                )
            )
        else:
            rule.min_model_tier = tier
            rule.eval_gate = gate
            rule.min_eval_score = score
            rule.max_latency_ms = latency

    budget_rules = [
        ("team", "support", Decimal("6000.00"), True),
        ("feature", "research_agent", Decimal("2200.00"), False),
        ("customer", "cust_nova", Decimal("1800.00"), False),
    ]
    for owner_type, owner_key, budget, hard_cap in budget_rules:
        rule = db.scalar(
            select(BudgetRule).where(
                BudgetRule.project_id == project.id,
                BudgetRule.owner_type == owner_type,
                BudgetRule.owner_key == owner_key,
            )
        )
        if rule is None:
            db.add(
                BudgetRule(
                    organization_id=org.id,
                    project_id=project.id,
                    owner_type=owner_type,
                    owner_key=owner_key,
                    monthly_budget_usd=budget,
                    hard_cap_enabled=hard_cap,
                )
            )
        else:
            rule.monthly_budget_usd = budget
            rule.hard_cap_enabled = hard_cap

    if not db.scalar(select(AlertRule).where(AlertRule.project_id == project.id)):
        db.add_all(
            [
                AlertRule(
                    organization_id=org.id,
                    project_id=project.id,
                    alert_type="forecast_over_budget",
                    threshold_percent=Decimal("0.90"),
                    destination_type="email",
                    destination="finops@example.com",
                ),
                AlertRule(
                    organization_id=org.id,
                    project_id=project.id,
                    alert_type="unpriced_usage",
                    threshold_percent=Decimal("0.05"),
                    destination_type="slack",
                    destination="#ai-costs",
                ),
            ]
        )


def _upsert_customer_economics(db: Session, org: Organization, project: Project) -> None:
    now = datetime.now(timezone.utc)
    start = _month_start(now)
    end = _month_end(now)
    rows = [
        ("cust_acme", "Acme Support", Decimal("180000.00")),
        ("cust_nova", "Nova Labs", Decimal("96000.00")),
        ("cust_zenith", "Zenith Analytics", Decimal("72000.00")),
    ]
    for customer_id, name, revenue in rows:
        econ = db.scalar(
            select(CustomerEconomics).where(
                CustomerEconomics.project_id == project.id,
                CustomerEconomics.customer_id == customer_id,
                CustomerEconomics.period_start == start,
                CustomerEconomics.period_end == end,
            )
        )
        if econ is None:
            db.add(
                CustomerEconomics(
                    organization_id=org.id,
                    project_id=project.id,
                    customer_id=customer_id,
                    customer_name=name,
                    revenue_usd=revenue,
                    period_start=start,
                    period_end=end,
                )
            )
        else:
            econ.customer_name = name
            econ.revenue_usd = revenue


def _upsert_connections(db: Session, org: Organization, project: Project) -> None:
    for provider, method, status in [
        ("openai", "metadata_api", "connected"),
        ("anthropic", "metadata_api", "connected"),
        ("bedrock", "metadata_api", "not_connected"),
    ]:
        conn = db.scalar(
            select(ProviderConnection).where(
                ProviderConnection.project_id == project.id,
                ProviderConnection.provider == provider,
            )
        )
        if conn is None:
            db.add(
                ProviderConnection(
                    organization_id=org.id,
                    project_id=project.id,
                    provider=provider,
                    connection_method=method,
                    status=status,
                    last_sync_at=datetime.now(timezone.utc) if status == "connected" else None,
                )
            )
        else:
            conn.connection_method = method
            conn.status = status
            conn.last_sync_at = datetime.now(timezone.utc) if status == "connected" else None


def _apply_demo_recommendations(db: Session, project: Project, now: datetime) -> int:
    """Apply the highest-value open recommendations through the real apply path so
    Proof, lever savings-to-date, and Command Center activity are all computed from
    the engine's own output. Leaves the rest open for the decision queue.

    Idempotent: re-seeding clears prior demo attributions/actions first, then
    re-applies against the freshly recomputed recommendations.
    """
    start = month_start(now)
    end = month_end(now)
    db.execute(
        delete(SavingsAttribution).where(
            SavingsAttribution.project_id == project.id,
            SavingsAttribution.period_start == start,
            SavingsAttribution.period_end == end,
        )
    )
    db.execute(
        delete(RecommendationAction).where(
            RecommendationAction.project_id == project.id,
            RecommendationAction.action_type == "applied",
        )
    )
    db.flush()

    candidates = list(
        db.scalars(
            select(Recommendation)
            .where(
                Recommendation.project_id == project.id,
                Recommendation.status == "open",
                Recommendation.lever.is_not(None),
                Recommendation.estimated_monthly_savings_usd.is_not(None),
            )
            .order_by(Recommendation.estimated_monthly_savings_usd.desc())
        )
    )

    applied = 0
    applied_levers: set[str] = set()
    applied_targets: set[str] = set()
    for rec in candidates:
        if applied >= DEMO_APPLY_LIMIT:
            break
        # One cut per lever and per route/feature, so overlapping levers on the
        # same traffic (e.g. cheaper-model and routing on one route) are not
        # double-counted in Proof.
        target = rec.related_feature or rec.target_key or str(rec.id)
        if rec.lever in applied_levers or target in applied_targets:
            continue
        rec.status = "applied"
        rec.resolved_at = now
        record_applied_savings(db, project, rec, source="system", now=now)
        applied_levers.add(rec.lever)
        applied_targets.add(target)
        applied += 1
    return applied


def seed(db: Session) -> dict[str, object]:
    org = _get_or_create_org(db)
    project = _get_or_create_project(db, org)
    _get_or_create_user(db, org)
    api_key = _get_or_create_api_key(db, project)
    _seed_prices(db)
    inserted_events = _seed_usage(db, org, project, api_key)
    _upsert_levers(db, org, project)
    _upsert_guardrails(db, org, project)
    _upsert_customer_economics(db, org, project)
    _upsert_connections(db, org, project)
    # Generate recommendations from the seeded usage, then apply the top few so
    # realized savings and Proof are computed by the same code path the product
    # uses. Nothing about the savings is hard-coded.
    now = datetime.now(timezone.utc)
    refresh_recommendations(db, project)
    db.flush()
    applied = _apply_demo_recommendations(db, project, now)
    db.commit()
    open_recs = db.scalar(
        select(func.count()).select_from(Recommendation).where(
            Recommendation.project_id == project.id, Recommendation.status == "open"
        )
    )
    return {
        "organization_id": str(org.id),
        "project_id": str(project.id),
        "api_key": DEMO_API_KEY,
        "inserted_usage_events": inserted_events,
        "applied_recommendations": applied,
        "open_recommendations": open_recs,
    }


def main() -> int:
    db = SessionLocal()
    try:
        result = seed(db)
    finally:
        db.close()
    print("Seeded Varsten demo workspace")
    print(f"organization_id={result['organization_id']}")
    print(f"project_id={result['project_id']}")
    print(f"api_key={result['api_key']}")
    print(f"inserted_usage_events={result['inserted_usage_events']}")
    print(f"applied_recommendations={result['applied_recommendations']}")
    print(f"open_recommendations={result['open_recommendations']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
