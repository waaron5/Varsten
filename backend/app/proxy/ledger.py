"""Write a proxied call into the authoritative usage ledger.

Metadata only: model, token counts, derived cost, and proxy/cache flags. No
prompt or completion text reaches the ledger. On a cache hit the actual cost is
$0 (OpenAI was bypassed); the retail cost that was avoided is recorded as
metadata so the dashboard can show Naive Retail vs Varsten Optimized.
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import Project, UsageEvent
from app.pricing import price_usage_event


def record_proxy_usage(
    db: Session,
    project: Project,
    api_key_id: uuid.UUID | None,
    *,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int,
    cache_hit: bool,
    latency_ms: int | None = None,
    now: datetime | None = None,
) -> UsageEvent:
    at = now or datetime.now(timezone.utc)
    # What these tokens cost at catalog price = the naive retail cost.
    naive_cost, cost_source, pricing_status, price_version_id = price_usage_event(
        db,
        organization_id=project.organization_id,
        model_key=model,
        provider="openai",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_input_tokens=cached_input_tokens,
        reported_cost_usd=None,
        at=at,
    )

    if cache_hit:
        # Bypassed the provider entirely: actual spend is zero, retail was avoided.
        cost_usd = Decimal("0")
        metadata = {
            "proxy": True,
            "cache": "hit",
            "naive_cost_usd": str(naive_cost) if naive_cost is not None else None,
            "saved_usd": str(naive_cost) if naive_cost is not None else None,
        }
    else:
        cost_usd = naive_cost
        metadata = {"proxy": True, "cache": "miss"}

    event = UsageEvent(
        project_id=project.id,
        organization_id=project.organization_id,
        api_key_id=api_key_id,
        provider="openai",
        model=model,
        operation="chat_completion",
        request_type="chat_completion",
        feature="proxy",
        environment="production",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_input_tokens=cached_input_tokens,
        total_tokens=input_tokens + output_tokens,
        cost_usd=cost_usd,
        cost_source=cost_source,
        pricing_status=pricing_status,
        price_version_id=price_version_id,
        currency="USD",
        status="success",
        success=True,
        latency_ms=latency_ms,
        event_metadata=metadata,
        occurred_at=at,
    )
    db.add(event)
    db.commit()
    return event
