"""Best-effort writer for per-request moat evidence.

Builds and persists one ``RequestDecisionEvent`` per metered proxied request from
the facts gathered along the request lifecycle. It runs in the existing
post-response capture path (off the hot path), reads the realized economics from
the usage_events row that was just written, and never raises into the request: a
failure here is logged and dropped, the client's response already went out.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models import RequestDecisionEvent, UsageEvent
from app.proxy.request_context import EMPTY_CONTEXT, RequestContext

logger = get_logger("varsten.proxy.evidence")


@dataclass
class DecisionDraft:
    """Mutable accumulator for the decision facts known before the response is
    captured. Created once per request at the proxy entry point and populated as
    optimization decisions are made. Finalized into a row by record_request_decision."""

    request_id: str
    client_dialect: str
    provider_requested: str
    model_requested: str
    api_key_id: uuid.UUID | None = None
    request_type: str | None = "chat_completion"
    ctx: RequestContext = field(default_factory=lambda: EMPTY_CONTEXT)
    bypassed: bool = False
    bypass_reason: str | None = None
    # Set as optimization is resolved.
    lever: str | None = None
    policy_id: uuid.UUID | None = None
    source_recommendation_id: uuid.UUID | None = None
    trim_applied: bool = False
    route_eligible: bool | None = None
    route_ineligible_reason: str | None = None


def _to_decimal(value) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _decision_type(*, cache_status: str | None, bypassed: bool, arm: str | None, trim_applied: bool, routed: bool) -> str:
    if cache_status in {"hit", "semantic"}:
        return "cache"
    if bypassed:
        return "bypass"
    if arm:
        return f"experiment_{arm}"
    if trim_applied:
        return "trim"
    if routed:
        return "route"
    return "passthrough"


async def record_request_decision(
    db: AsyncSession,
    *,
    draft: DecisionDraft,
    event: UsageEvent | None,
    provider_chosen: str,
    model_chosen: str,
    cache_status: str | None,
    arm: str | None = None,
    routed_from: str | None = None,
    routed_from_provider: str | None = None,
    trim_applied: bool = False,
    latency_ms: int | None = None,
    quality_ok: bool | None = None,
    fallback_used: bool = False,
    fallback_reason: str | None = None,
    error_code: str | None = None,
    failure_mode: str | None = None,
) -> None:
    """Persist the decision evidence for one request. Best-effort: own try/except,
    own commit, logged-and-dropped on failure. In Phase 1 a decision row is only
    written alongside a metered ledger event, so a missing event is a no-op."""
    if event is None:
        return
    try:
        ctx = draft.ctx or EMPTY_CONTEXT
        meta = event.event_metadata or {}
        routed = routed_from is not None

        decision_type = _decision_type(
            cache_status=cache_status,
            bypassed=draft.bypassed,
            arm=arm,
            trim_applied=trim_applied,
            routed=routed,
        )
        optimization_applied = bool(
            cache_status in {"hit", "semantic"} or trim_applied or routed
        )

        # Realized economics come from the ledger row (single source of truth), so
        # pricing is never recomputed here.
        realized_actual = event.cost_usd if event is not None else None
        realized_naive = _to_decimal(meta.get("naive_cost_usd"))
        realized_savings = _to_decimal(meta.get("saved_usd"))

        counterfactual_model = routed_from or (model_chosen if cache_status in {"hit", "semantic"} else None)
        counterfactual_provider = routed_from_provider or (provider_chosen if counterfactual_model else None)

        row = RequestDecisionEvent(
            organization_id=event.organization_id,
            project_id=event.project_id,
            usage_event_id=event.id,
            api_key_id=draft.api_key_id,
            request_id=draft.request_id,
            provider_requested=draft.provider_requested,
            model_requested=draft.model_requested,
            client_dialect=draft.client_dialect,
            request_type=draft.request_type,
            feature=ctx.feature,
            workflow=ctx.workflow,
            customer_id=ctx.customer_id,
            external_user_id=ctx.external_user_id,
            team=ctx.team,
            department=ctx.department,
            environment=ctx.environment,
            task_type=ctx.task_type,
            task_confidence=_to_decimal(ctx.task_confidence),
            risk_level=ctx.risk_level,
            quality_threshold=ctx.quality_threshold,
            decision_type=decision_type,
            lever=draft.lever,
            policy_id=draft.policy_id,
            source_recommendation_id=draft.source_recommendation_id,
            arm=arm,
            optimization_applied=optimization_applied,
            bypassed=draft.bypassed,
            bypass_reason=draft.bypass_reason,
            cache_status=cache_status,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
            route_eligible=draft.route_eligible,
            route_ineligible_reason=draft.route_ineligible_reason,
            provider_chosen=provider_chosen,
            model_chosen=model_chosen,
            execution_path={"provider": provider_chosen, "model": model_chosen},
            provider_counterfactual=counterfactual_provider,
            model_counterfactual=counterfactual_model,
            counterfactual_path=(
                {"provider": counterfactual_provider, "model": counterfactual_model} if counterfactual_model else {}
            ),
            realized_naive_cost_usd=realized_naive,
            realized_actual_cost_usd=realized_actual,
            realized_savings_usd=realized_savings,
            price_version_id=event.price_version_id,
            pricing_status=event.pricing_status,
            cost_source=event.cost_source,
            quality_ok=quality_ok if quality_ok is not None else meta.get("quality_ok"),
            failure_mode=failure_mode,
            error_code=error_code,
            latency_ms=latency_ms,
            reason_detail={},
            event_metadata=ctx.task_metadata(),
            created_at=datetime.now(UTC),
        )
        db.add(row)
        await db.commit()
    except Exception:
        await db.rollback()
        logger.exception("request decision evidence write failed")
