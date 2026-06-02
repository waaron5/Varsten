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

from sqlalchemy import func, select
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
    RecommendationAction,
    SavingsAttribution,
    UsageEvent,
    User,
)
from app.pricing.service import price_usage_event
from app.recommendations import refresh_recommendations

DEMO_ORG_NAME = "Varsten Demo Co"
DEMO_PROJECT_NAME = "Production AI"
DEMO_USER_EMAIL = "demo@varsten.local"
DEMO_API_KEY = "vk_demo_varsten_local_key"

LEVER_DEFAULTS = {
    "smart_routing": ("approve", Decimal("0")),
    "semantic_cache": ("auto", Decimal("1820.00")),
    "token_trim": ("auto", Decimal("940.00")),
    "cheaper_model": ("approve", Decimal("0")),
    "batching": ("auto", Decimal("410.00")),
}


@dataclass(frozen=True)
class PriceSeed:
    model_key: str
    provider: str
    input_cost: Decimal
    output_cost: Decimal
    tier: str
    cheaper_substitute_key: str | None = None
    batch_input_cost: Decimal | None = None
    batch_output_cost: Decimal | None = None


PRICES = [
    PriceSeed(
        model_key="gpt-4o",
        provider="openai",
        input_cost=Decimal("0.000005"),
        output_cost=Decimal("0.000015"),
        tier="frontier",
        cheaper_substitute_key="gpt-4o-mini",
    ),
    PriceSeed(
        model_key="gpt-4o-mini",
        provider="openai",
        input_cost=Decimal("0.0000006"),
        output_cost=Decimal("0.0000024"),
        tier="small",
        batch_input_cost=Decimal("0.0000003"),
        batch_output_cost=Decimal("0.0000012"),
    ),
    PriceSeed(
        model_key="claude-3-5-sonnet",
        provider="anthropic",
        input_cost=Decimal("0.000003"),
        output_cost=Decimal("0.000015"),
        tier="frontier",
        cheaper_substitute_key="claude-3-haiku",
    ),
    PriceSeed(
        model_key="claude-3-haiku",
        provider="anthropic",
        input_cost=Decimal("0.00000025"),
        output_cost=Decimal("0.00000125"),
        tier="small",
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
            monthly_spend_budget_usd=Decimal("14500.00"),
        )
        db.add(org)
        db.flush()
    else:
        org.monthly_spend_budget_usd = Decimal("14500.00")
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
            or latest.input_cost_per_token_batch != price.batch_input_cost
            or latest.output_cost_per_token_batch != price.batch_output_cost
        ):
            db.add(
                ModelPrice(
                    model_key=price.model_key,
                    provider=price.provider,
                    input_cost_per_token=price.input_cost,
                    output_cost_per_token=price.output_cost,
                    input_cost_per_token_batch=price.batch_input_cost,
                    output_cost_per_token_batch=price.batch_output_cost,
                    source="demo",
                )
            )
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
    if db.scalar(
        select(UsageEvent.id).where(
            UsageEvent.project_id == project.id,
            UsageEvent.idempotency_key == key,
        )
    ):
        return False

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
    db.add(
        UsageEvent(
            organization_id=org.id,
            project_id=project.id,
            api_key_id=api_key.id,
            provider=provider,
            model=model,
            operation=request_type,
            request_type=request_type,
            workflow=feature,
            feature=feature,
            external_user_id=user_id,
            user_id=user_id,
            customer_id=customer_id,
            team=team,
            department=department,
            environment=environment,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            cost_usd=cost,
            cost_source=cost_source,
            pricing_status=pricing_status,
            price_version_id=price_version_id,
            currency="USD",
            idempotency_key=key,
            status="success" if success else "error",
            success=success,
            error_code=error_code,
            latency_ms=latency_ms,
            occurred_at=occurred_at,
            event_timestamp=occurred_at,
            received_at=occurred_at,
            event_metadata=metadata or {},
        )
    )
    return True


def _seed_usage(db: Session, org: Organization, project: Project, api_key: ApiKey) -> int:
    now = datetime.now(timezone.utc)
    inserted = 0
    rows = [
        # Same route on expensive and cheap models, producing smart-routing signal.
        ("sr-expensive", "openai", "gpt-4o", "support_chat", "support_bot", "cust_acme", "user_1", "support", "cx", "production", 1, 3200, 700, 1280, True, None, {}),
        ("sr-cheap", "openai", "gpt-4o-mini", "support_chat", "support_bot", "cust_acme", "user_2", "support", "cx", "production", 2, 3000, 680, 940, True, None, {}),
        # High input/output ratio for token trim.
        ("trim-1", "openai", "gpt-4o-mini", "summarize_research", "research_agent", "cust_nova", "user_3", "product", "r_and_d", "production", 3, 12000, 900, 1610, True, None, {}),
        # Repeated semantic cache keys.
        ("cache-1", "openai", "gpt-4o-mini", "answer_faq", "support_bot", "cust_acme", "user_4", "support", "cx", "production", 4, 1500, 500, 720, True, None, {"semantic_cache_key": "faq:reset-password"}),
        ("cache-2", "openai", "gpt-4o-mini", "answer_faq", "support_bot", "cust_acme", "user_5", "support", "cx", "production", 5, 1480, 510, 735, True, None, {"semantic_cache_key": "faq:reset-password"}),
        ("cache-3", "openai", "gpt-4o-mini", "answer_faq", "support_bot", "cust_acme", "user_6", "support", "cx", "production", 6, 1510, 505, 710, True, None, {"semantic_cache_key": "faq:reset-password"}),
        # Batchable background work.
        ("batch-1", "openai", "gpt-4o-mini", "nightly_export", "analytics_exports", "cust_zenith", "system", "data", "analytics", "production", 7, 6200, 1400, 5800, True, None, {"batchable": "true"}),
        # Cheaper-model signal via catalog substitute.
        ("cheap-model-1", "anthropic", "claude-3-5-sonnet", "classify_ticket", "ticket_triage", "cust_nova", "user_7", "support", "cx", "production", 8, 2200, 300, 1120, True, None, {}),
        # Non-prod and failed spend keep trust/guardrail panels interesting.
        ("nonprod-1", "openai", "gpt-4o", "load_test", "eval_harness", "cust_internal", "engineer_1", "platform", "engineering", "staging", 9, 5000, 1200, 1330, True, None, {}),
        ("failed-1", "openai", "gpt-4o-mini", "support_chat", "support_bot", "cust_zenith", "user_8", "support", "cx", "production", 10, 1800, 100, 2100, False, "provider_timeout", {}),
        # Unknown model accepted as unpriced trust issue.
        ("unpriced-1", "openai", "unknown-frontier-demo", "prototype", "labs_agent", "cust_internal", "engineer_2", "labs", "r_and_d", "development", 11, 2000, 400, 1800, True, None, {}),
    ]
    for (
        key,
        provider,
        model,
        request_type,
        feature,
        customer_id,
        user_id,
        team,
        department,
        environment,
        hours_ago,
        input_tokens,
        output_tokens,
        latency_ms,
        success,
        error_code,
        metadata,
    ) in rows:
        if _event(
            db,
            org,
            project,
            api_key,
            key=f"demo:{key}",
            provider=provider,
            model=model,
            request_type=request_type,
            feature=feature,
            customer_id=customer_id,
            user_id=user_id,
            team=team,
            department=department,
            environment=environment,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            occurred_at=now - timedelta(hours=hours_ago),
            latency_ms=latency_ms,
            success=success,
            error_code=error_code,
            metadata=metadata,
        ):
            inserted += 1
    return inserted


def _upsert_levers(db: Session, org: Organization, project: Project) -> None:
    for lever, (mode, savings) in LEVER_DEFAULTS.items():
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
                    savings_to_date_usd=savings,
                )
            )
        else:
            config.enabled = True
            config.automation_mode = mode
            config.savings_to_date_usd = savings


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
        ("cust_acme", "Acme Support", Decimal("12000.00")),
        ("cust_nova", "Nova Labs", Decimal("900.00")),
        ("cust_zenith", "Zenith Analytics", Decimal("4200.00")),
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


def _upsert_proof_rows(db: Session, org: Organization, project: Project) -> None:
    now = datetime.now(timezone.utc)
    start = _month_start(now)
    end = _month_end(now)
    rows = [
        ("semantic_cache", Decimal("3100.00"), Decimal("1280.00"), "direct_avoidance"),
        ("token_trim", Decimal("4200.00"), Decimal("3260.00"), "backtested"),
        ("batching", Decimal("1850.00"), Decimal("1440.00"), "direct_rate_delta"),
    ]
    for lever, counterfactual, actual, method in rows:
        gross = counterfactual - actual
        fee = gross * Decimal("0.20")
        net = gross - fee
        attribution = db.scalar(
            select(SavingsAttribution).where(
                SavingsAttribution.project_id == project.id,
                SavingsAttribution.lever == lever,
                SavingsAttribution.period_start == start,
                SavingsAttribution.period_end == end,
            )
        )
        if attribution is None:
            attribution = SavingsAttribution(
                organization_id=org.id,
                project_id=project.id,
                lever=lever,
                measurement_method=method,
                status="estimated",
                period_start=start,
                period_end=end,
            )
            db.add(attribution)
        attribution.counterfactual_spend_usd = counterfactual
        attribution.actual_spend_usd = actual
        attribution.gross_savings_usd = gross
        attribution.varsten_fee_usd = fee
        attribution.net_savings_usd = net
        attribution.confidence_low_usd = gross * Decimal("0.80")
        attribution.confidence_high_usd = gross * Decimal("1.15")
        attribution.notes = "Demo proof row for the v1 estimated/backtested savings view."

        action = db.scalar(
            select(RecommendationAction).where(
                RecommendationAction.project_id == project.id,
                RecommendationAction.lever == lever,
                RecommendationAction.title == f"Demo {lever} action",
            )
        )
        if action is None:
            db.add(
                RecommendationAction(
                    organization_id=org.id,
                    project_id=project.id,
                    lever=lever,
                    action_type="auto_applied",
                    status="completed",
                    source="system",
                    title=f"Demo {lever} action",
                    detail="Seeded auto-action for Command Center activity.",
                    estimated_savings_usd=gross,
                    realized_savings_usd=net,
                    occurred_at=now - timedelta(days=1),
                )
            )


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
    _upsert_proof_rows(db, org, project)
    refresh_recommendations(db, project)
    db.commit()
    rec_count = db.scalar(
        select(func.count()).select_from(RecommendationAction).where(
            RecommendationAction.project_id == project.id
        )
    )
    return {
        "organization_id": str(org.id),
        "project_id": str(project.id),
        "api_key": DEMO_API_KEY,
        "inserted_usage_events": inserted_events,
        "recommendation_actions": rec_count,
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
