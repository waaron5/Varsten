"""Write a proxied call into the authoritative usage ledger.

Metadata only: model, token counts, derived cost, and proxy/cache flags. No
prompt or completion text reaches the ledger. On a cache hit the actual cost is
$0 (OpenAI was bypassed); the retail cost that was avoided is recorded as
metadata so the dashboard can show Naive Retail vs Varsten Optimized.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.engine.route_identity import route_key_from_context
from app.models import Project, UsageEvent
from app.pricing import price_usage_event
from app.proxy.request_context import RequestContext

logger = get_logger("varsten.proxy.ledger")


async def _cost_and_base_metadata(
    db: AsyncSession,
    project: Project,
    at: datetime,
    *,
    model: str,
    provider: str,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int,
    used_cost: Decimal | None,
    cache_hit: bool,
    naive_model: str | None,
    naive_provider: str | None,
) -> tuple[Decimal, dict[str, Any]]:
    """Actual cost of the call and the base ledger metadata for it.

    Three cases: a cache hit (provider bypassed, $0 actual, retail avoided), a
    model-downshift route (the direct method -- actual is the candidate's cost, the
    incumbent's cost for the same tokens is the naive baseline), or a plain miss.
    """
    if cache_hit:
        return Decimal("0"), {
            "proxy": True,
            "cache": "hit",
            "naive_cost_usd": str(used_cost) if used_cost is not None else None,
            "saved_usd": str(used_cost) if used_cost is not None else None,
        }

    # Routed to a lower-cost model/provider. The truthiness check also narrows
    # naive_model to a concrete str for the priced baseline call below.
    if naive_model and (naive_model != model or (naive_provider is not None and naive_provider != provider)):
        naive_cost, _, _, _ = await price_usage_event(
            db,
            organization_id=project.organization_id,
            model_key=naive_model,
            provider=naive_provider or provider,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=cached_input_tokens,
            reported_cost_usd=None,
            at=at,
        )
        saved = (naive_cost - used_cost) if (naive_cost is not None and used_cost is not None) else None
        return used_cost or Decimal("0"), {
            "proxy": True,
            "cache": "miss",
            "routed": True,
            "routed_from": naive_model,
            "routed_to": model,
            "routed_from_provider": naive_provider or provider,
            "routed_to_provider": provider,
            "naive_cost_usd": str(naive_cost) if naive_cost is not None else None,
            "saved_usd": str(saved) if saved is not None else None,
        }

    return used_cost or Decimal("0"), {"proxy": True, "cache": "miss"}


def _augment_metadata(
    metadata: dict[str, Any],
    *,
    cached_input_tokens: int,
    arm: str | None,
    experiment_from: str | None,
    experiment_to: str | None,
    quality_ok: bool | None,
    ctx: RequestContext | None,
) -> None:
    """Layer the provider-cache fact, holdback A/B tags, and client task context
    onto the base metadata in place."""
    # Provider-native prompt-cache discount. This is the PROVIDER's saving, never
    # Varsten's, so it is labelled distinctly and deliberately kept out of
    # saved_usd. Keeps the Proof page unassailable: Varsten only claims its levers.
    if cached_input_tokens:
        metadata["provider_cached_input_tokens"] = cached_input_tokens

    # Live holdback A/B tags. The control arm carries no savings (it is the
    # baseline); both arms carry the experiment pair so the rigorous A/B can group
    # them straight from the ledger, with no separate experiment table.
    if arm:
        metadata["holdback"] = True
        metadata["arm"] = arm
        metadata["experiment_from"] = experiment_from
        metadata["experiment_to"] = experiment_to
        metadata["route_key"] = route_key_from_context(ctx, request_type="chat_completion")
        # Objective response-health for the live drift guard (a metadata fact, not
        # content). Compared across arms to catch a candidate that degrades.
        if quality_ok is not None:
            metadata["quality_ok"] = quality_ok

    # Client-supplied business/task context. Business dimensions populate the
    # first-class columns (see _context_fields); task/quality context rides in
    # metadata for Phase 1 (and is mirrored, indexed, onto decision-evidence).
    if ctx is not None and not ctx.is_empty:
        metadata.update(ctx.task_metadata())


def _context_fields(ctx: RequestContext | None) -> dict[str, Any]:
    """First-class UsageEvent business dimensions from the request context.

    `feature` is a pure business dimension now: it stays NULL unless the client
    supplies it, so it never doubles as a "came through the proxy" marker (the
    `source` column does that). Absent context still defaults environment to
    production, the right assumption for inline gateway traffic."""
    if ctx is None:
        return {"environment": "production"}
    return {
        "feature": ctx.feature,
        "workflow": ctx.workflow,
        "customer_id": ctx.customer_id,
        "external_user_id": ctx.external_user_id,
        "user_id": ctx.user_id,
        "team": ctx.team,
        "department": ctx.department,
        "environment": ctx.environment or "production",
    }


async def record_proxy_usage(
    db: AsyncSession,
    project: Project,
    api_key_id: uuid.UUID | None,
    *,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int,
    cache_hit: bool,
    provider: str = "openai",
    naive_model: str | None = None,
    naive_provider: str | None = None,
    arm: str | None = None,
    experiment_from: str | None = None,
    experiment_to: str | None = None,
    quality_ok: bool | None = None,
    latency_ms: int | None = None,
    context: RequestContext | None = None,
    now: datetime | None = None,
) -> UsageEvent:
    at = now or datetime.now(UTC)
    # Cost of these tokens at catalog price for the model actually used.
    used_cost, cost_source, pricing_status, price_version_id = await price_usage_event(
        db,
        organization_id=project.organization_id,
        model_key=model,
        provider=provider,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_input_tokens=cached_input_tokens,
        reported_cost_usd=None,
        at=at,
    )

    cost_usd, metadata = await _cost_and_base_metadata(
        db,
        project,
        at,
        model=model,
        provider=provider,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_input_tokens=cached_input_tokens,
        used_cost=used_cost,
        cache_hit=cache_hit,
        naive_model=naive_model,
        naive_provider=naive_provider,
    )
    _augment_metadata(
        metadata,
        cached_input_tokens=cached_input_tokens,
        arm=arm,
        experiment_from=experiment_from,
        experiment_to=experiment_to,
        quality_ok=quality_ok,
        ctx=context,
    )

    event = UsageEvent(
        project_id=project.id,
        organization_id=project.organization_id,
        api_key_id=api_key_id,
        source="proxy",
        provider=provider,
        model=model,
        operation="chat_completion",
        request_type="chat_completion",
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
        **_context_fields(context),
    )
    db.add(event)
    await db.commit()
    return event


async def record_overhead_usage(
    db: AsyncSession,
    project: Project,
    *,
    provider: str,
    model: str,
    operation: str,
    input_tokens: int,
    output_tokens: int,
    overhead: str,
    now: datetime | None = None,
) -> UsageEvent | None:
    """Meter optimization overhead into the usage ledger.

    These rows are not customer workload traffic, but they are real cost incurred
    to prove or execute an optimization. Verified savings subtract them before
    billing. Best-effort: failures are logged and return None.
    """
    at = now or datetime.now(UTC)
    try:
        cost, cost_source, pricing_status, price_version_id = await price_usage_event(
            db,
            organization_id=project.organization_id,
            model_key=model,
            provider=provider,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=0,
            reported_cost_usd=None,
            at=at,
        )
        event = UsageEvent(
            project_id=project.id,
            organization_id=project.organization_id,
            api_key_id=None,
            source="overhead",
            provider=provider,
            model=model,
            operation=operation,
            request_type=operation,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=0,
            total_tokens=input_tokens + output_tokens,
            cost_usd=cost,
            cost_source=cost_source,
            pricing_status=pricing_status,
            price_version_id=price_version_id,
            currency="USD",
            status="success",
            success=True,
            event_metadata={"overhead": overhead},
            occurred_at=at,
            environment="production",
        )
        db.add(event)
        await db.commit()
        return event
    except Exception:
        logger.exception("overhead ledger write failed", extra={"project_id": str(project.id), "overhead": overhead})
        return None


def record_batch_usage(
    db: Session,
    project: Project,
    api_key_id: uuid.UUID | None,
    *,
    model: str,
    input_tokens: int,
    output_tokens: int,
    actual_cost_usd: Decimal | None,
    naive_cost_usd: Decimal | None,
    request_count: int,
    now: datetime | None = None,
) -> UsageEvent:
    """Record one model's slice of a completed batch in the ledger. The batch lever
    is the direct method: actual spend is the batch-priced cost, the naive baseline
    is the synchronous price for the same tokens, and the difference is measured
    savings (no holdback needed -- batch pricing is a contractual discount on
    identical tokens). Metadata only; the .jsonl never reaches the ledger."""
    at = now or datetime.now(UTC)
    saved = naive_cost_usd - actual_cost_usd if (naive_cost_usd is not None and actual_cost_usd is not None) else None
    metadata = {
        "proxy": True,
        "batch": True,
        "lever": "batching",
        "request_count": request_count,
        "naive_cost_usd": str(naive_cost_usd) if naive_cost_usd is not None else None,
        "saved_usd": str(saved) if saved is not None else None,
    }
    event = UsageEvent(
        project_id=project.id,
        organization_id=project.organization_id,
        api_key_id=api_key_id,
        source="proxy",
        provider="openai",
        model=model,
        operation="batch",
        request_type="batch",
        environment="production",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_input_tokens=0,
        total_tokens=input_tokens + output_tokens,
        cost_usd=actual_cost_usd,
        cost_source="catalog" if actual_cost_usd is not None else "unknown",
        pricing_status="priced" if actual_cost_usd is not None else "model_not_in_catalog",
        price_version_id=None,
        currency="USD",
        status="success",
        success=True,
        latency_ms=None,
        event_metadata=metadata,
        occurred_at=at,
    )
    db.add(event)
    db.commit()
    return event
