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
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.engine import CandidateStatus, OptimizationPlan, plan_to_metadata, runtime_trace_event
from app.engine.route_identity import route_key_from_context
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
    compression_applied: bool = False
    route_eligible: bool | None = None
    route_ineligible_reason: str | None = None
    # Content-free fingerprint of the request's cacheable prefix (system/tools),
    # for measured prompt-cache prefix-stability analysis. Hash only, never text.
    prefix_hash: str | None = None
    # Content-free fingerprint of the whole request body, for trace-level
    # redundant-call (agent loop) detection. Hash only, never text.
    request_fingerprint: str | None = None
    optimization_plan: OptimizationPlan | None = None
    runtime_trace: list[dict[str, Any]] = field(default_factory=list)

    def add_runtime_trace(
        self,
        *,
        stage: str,
        lever: str,
        action: str,
        reason_code: str,
        enforced: bool = False,
        policy_id: str | uuid.UUID | None = None,
        source_recommendation_id: str | uuid.UUID | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self.runtime_trace.append(
            runtime_trace_event(
                stage=stage,
                lever=lever,
                action=action,
                reason_code=reason_code,
                enforced=enforced,
                policy_id=str(policy_id) if policy_id else None,
                source_recommendation_id=str(source_recommendation_id) if source_recommendation_id else None,
                detail=detail,
            )
        )


def _to_decimal(value) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _decision_type(
    *,
    cache_status: str | None,
    bypassed: bool,
    arm: str | None,
    trim_applied: bool,
    routed: bool,
    compression_applied: bool = False,
) -> str:
    if cache_status in {"hit", "semantic"}:
        return "cache"
    if bypassed:
        return "bypass"
    if arm:
        return f"experiment_{arm}"
    if trim_applied:
        return "trim"
    if compression_applied:
        return "compression"
    if routed:
        return "route"
    return "passthrough"


def _applied_lever(
    *,
    cache_status: str | None,
    arm: str | None,
    trim_applied: bool,
    routed: bool,
    compression_applied: bool = False,
) -> str | None:
    """The primary optimization lever the proxy actually applied, in planner
    vocabulary, or None for plain passthrough. A held-back control arm applied no
    optimization (it stayed on the incumbent), so it is passthrough here."""
    if cache_status == "hit":
        return "exact_cache"
    if cache_status == "semantic":
        return "semantic_cache"
    if routed:
        return "model_routing"
    if trim_applied:
        return "token_trim"
    if compression_applied:
        return "prompt_compression"
    if arm == "treatment":
        return "model_routing"
    return None


def add_planner_parity_trace(
    draft: DecisionDraft,
    *,
    cache_status: str | None,
    arm: str | None,
    trim_applied: bool,
    routed: bool,
    compression_applied: bool = False,
) -> None:
    """Record whether the optimization the proxy applied was authorized by the
    planner (parity). This is the A4 shadow: every applied lever must trace back to
    a non-rejected planner candidate. A mismatch means the proxy applied something
    the planner would have blocked — the exact drift to catch before the planner is
    made authoritative. Bypassed requests skip the planner entirely, so no parity."""
    plan = draft.optimization_plan
    if plan is None or draft.bypassed:
        return
    applied = _applied_lever(
        cache_status=cache_status,
        arm=arm,
        trim_applied=trim_applied,
        routed=routed,
        compression_applied=compression_applied,
    )
    if applied is None:
        # Passthrough is always consistent with an advisory planner (it forces
        # nothing); record it so parity coverage is visible, not silently skipped.
        draft.add_runtime_trace(
            stage="planner_parity",
            lever="none",
            action="match",
            reason_code="passthrough",
            detail={"planner_selected": plan.selected.action, "applied": None},
        )
        return
    candidate = plan.candidate_for(applied)
    blocked = {CandidateStatus.REJECTED, CandidateStatus.UNAVAILABLE}
    if candidate is None:
        action, reason = "mismatch", "no_candidate"
    elif candidate.status in blocked:
        action, reason = "mismatch", f"applied_{candidate.status.value}"
    else:
        action, reason = "match", candidate.status.value
    draft.add_runtime_trace(
        stage="planner_parity",
        lever=applied,
        action=action,
        reason_code=reason,
        detail={"planner_selected": plan.selected.action, "applied": applied},
    )


def _money(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _quality_status(quality_ok: bool | None) -> str:
    if quality_ok is True:
        return "passed"
    if quality_ok is False:
        return "failed"
    return "not_measured"


def _savings_method(
    *,
    cache_status: str | None,
    bypassed: bool,
    arm: str | None,
    trim_applied: bool,
    routed: bool,
    compression_applied: bool = False,
) -> str:
    if cache_status in {"hit", "semantic"}:
        return "cache_avoidance"
    if routed:
        return "route_counterfactual"
    if arm and trim_applied:
        return "trim_holdback_observation"
    if arm and compression_applied:
        return "compression_holdback_observation"
    if arm:
        return "holdback_observation"
    if bypassed:
        return "bypass"
    return "none"


def _savings_confidence(
    *,
    realized_naive: Decimal | None,
    realized_savings: Decimal | None,
    pricing_status: str | None,
    arm: str | None,
    optimization_applied: bool,
) -> str:
    if realized_naive is not None and realized_savings is not None and pricing_status == "priced":
        return "measured_priced"
    if realized_naive is not None and realized_savings is not None:
        return "measured_pricing_uncertain"
    if arm:
        return "requires_aggregate_holdback"
    if optimization_applied:
        return "unmeasured"
    return "not_applicable"


def _savings_reason_codes(
    *,
    realized_naive: Decimal | None,
    realized_actual: Decimal | None,
    realized_savings: Decimal | None,
    quality_ok: bool | None,
    arm: str | None,
    optimization_applied: bool,
) -> list[str]:
    reasons: list[str] = []
    if realized_naive is None:
        reasons.append("baseline_unavailable")
    if realized_actual is None:
        reasons.append("actual_cost_unavailable")
    if realized_savings is None and optimization_applied:
        reasons.append("savings_unavailable")
    if arm and realized_savings is None:
        reasons.append("aggregate_holdback_required")
    reasons.append("optimization_overhead_not_measured")
    if quality_ok is None:
        reasons.append("quality_not_measured")
    return reasons


def _savings_proof(
    *,
    event: UsageEvent,
    cache_status: str | None,
    bypassed: bool,
    arm: str | None,
    trim_applied: bool,
    routed: bool,
    optimization_applied: bool,
    realized_naive: Decimal | None,
    realized_actual: Decimal | None,
    realized_savings: Decimal | None,
    quality_ok: bool | None,
    compression_applied: bool = False,
) -> dict[str, Any]:
    overhead_cost: Decimal | None = None
    return {
        "method": _savings_method(
            cache_status=cache_status,
            bypassed=bypassed,
            arm=arm,
            trim_applied=trim_applied,
            routed=routed,
            compression_applied=compression_applied,
        ),
        "baseline_cost_usd": _money(realized_naive),
        "actual_cost_usd": _money(realized_actual),
        "gross_savings_usd": _money(realized_savings),
        "optimization_overhead_cost_usd": _money(overhead_cost),
        "net_savings_usd": _money(realized_savings - overhead_cost)
        if realized_savings is not None and overhead_cost is not None
        else None,
        "confidence": _savings_confidence(
            realized_naive=realized_naive,
            realized_savings=realized_savings,
            pricing_status=event.pricing_status,
            arm=arm,
            optimization_applied=optimization_applied,
        ),
        "quality_status": _quality_status(quality_ok),
        "pricing_status": event.pricing_status,
        "cost_source": event.cost_source,
        "price_version_id": str(event.price_version_id) if event.price_version_id else None,
        "reason_codes": _savings_reason_codes(
            realized_naive=realized_naive,
            realized_actual=realized_actual,
            realized_savings=realized_savings,
            quality_ok=quality_ok,
            arm=arm,
            optimization_applied=optimization_applied,
        ),
    }


def _decision_metadata(draft: DecisionDraft, savings_proof: dict[str, Any] | None = None) -> dict:
    metadata = draft.ctx.task_metadata() if draft.ctx else {}
    if draft.optimization_plan is not None:
        metadata["optimization_plan"] = plan_to_metadata(draft.optimization_plan)
    if draft.runtime_trace:
        metadata["runtime_trace"] = list(draft.runtime_trace)
    if savings_proof is not None:
        metadata["savings_proof"] = savings_proof
    return metadata


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
        compression_applied = draft.compression_applied

        add_planner_parity_trace(
            draft,
            cache_status=cache_status,
            arm=arm,
            trim_applied=trim_applied,
            routed=routed,
            compression_applied=compression_applied,
        )

        decision_type = _decision_type(
            cache_status=cache_status,
            bypassed=draft.bypassed,
            arm=arm,
            trim_applied=trim_applied,
            routed=routed,
            compression_applied=compression_applied,
        )
        optimization_applied = bool(
            cache_status in {"hit", "semantic"} or trim_applied or routed or compression_applied
        )

        # Realized economics come from the ledger row (single source of truth), so
        # pricing is never recomputed here.
        realized_actual = event.cost_usd if event is not None else None
        realized_naive = _to_decimal(meta.get("naive_cost_usd"))
        realized_savings = _to_decimal(meta.get("saved_usd"))
        effective_quality_ok = quality_ok if quality_ok is not None else meta.get("quality_ok")
        proof = _savings_proof(
            event=event,
            cache_status=cache_status,
            bypassed=draft.bypassed,
            arm=arm,
            trim_applied=trim_applied,
            routed=routed,
            compression_applied=compression_applied,
            optimization_applied=optimization_applied,
            realized_naive=realized_naive,
            realized_actual=realized_actual,
            realized_savings=realized_savings,
            quality_ok=effective_quality_ok,
        )

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
            route_key=route_key_from_context(ctx, request_type=draft.request_type),
            prefix_hash=draft.prefix_hash,
            trace_id=ctx.trace_id,
            request_fingerprint=draft.request_fingerprint,
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
            quality_ok=effective_quality_ok,
            failure_mode=failure_mode,
            error_code=error_code,
            latency_ms=latency_ms,
            reason_detail={},
            event_metadata=_decision_metadata(draft, proof),
            created_at=datetime.now(UTC),
        )
        db.add(row)
        await db.commit()
    except Exception:
        await db.rollback()
        logger.exception("request decision evidence write failed")
