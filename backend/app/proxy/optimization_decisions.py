"""Durable audit records for routing and optimization decisions."""

import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models import OptimizationDecision

INELIGIBLE_DECISION = "ineligible"

INELIGIBILITY_REASON_CODES = {
    "anthropic_cache_control",
    "anthropic_beta_unsupported",
    "gemini_safety_settings",
    "server_side_tool",
    "native_multimodal_unmapped",
}


def _validate_ineligible(decision: str, reason_code: str) -> None:
    if decision != INELIGIBLE_DECISION:
        raise ValueError(f"unsupported ineligible optimization decision: {decision}")
    if reason_code not in INELIGIBILITY_REASON_CODES:
        raise ValueError(f"unsupported optimization ineligibility reason: {reason_code}")


def _build_ineligible_decision(
    *,
    organization_id: uuid.UUID,
    project_id: uuid.UUID,
    request_id: str,
    client_dialect: str,
    requested_provider: str,
    requested_model: str,
    candidate_provider: str,
    candidate_model: str,
    decision: str,
    reason_code: str,
    reason_detail: Mapping[str, Any] | None,
) -> OptimizationDecision:
    _validate_ineligible(decision, reason_code)
    return OptimizationDecision(
        organization_id=organization_id,
        project_id=project_id,
        request_id=request_id,
        client_dialect=client_dialect,
        requested_provider=requested_provider,
        requested_model=requested_model,
        candidate_provider=candidate_provider,
        candidate_model=candidate_model,
        decision=decision,
        reason_code=reason_code,
        reason_detail=dict(reason_detail or {}),
    )


def record_ineligible_decision(
    db: Session,
    *,
    organization_id: uuid.UUID,
    project_id: uuid.UUID,
    request_id: str,
    client_dialect: str,
    requested_provider: str,
    requested_model: str,
    candidate_provider: str,
    candidate_model: str,
    decision: str = INELIGIBLE_DECISION,
    reason_code: str,
    reason_detail: Mapping[str, Any] | None = None,
) -> OptimizationDecision:
    """Persist why a candidate route was rejected.

    The caller owns transaction boundaries. We flush so the returned object has a
    stable primary key and DB constraints fail before request handling moves on.
    """
    row = _build_ineligible_decision(
        organization_id=organization_id,
        project_id=project_id,
        request_id=request_id,
        client_dialect=client_dialect,
        requested_provider=requested_provider,
        requested_model=requested_model,
        candidate_provider=candidate_provider,
        candidate_model=candidate_model,
        decision=decision,
        reason_code=reason_code,
        reason_detail=reason_detail,
    )
    db.add(row)
    db.flush()
    return row


async def record_ineligible_decision_async(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    project_id: uuid.UUID,
    request_id: str,
    client_dialect: str,
    requested_provider: str,
    requested_model: str,
    candidate_provider: str,
    candidate_model: str,
    decision: str = INELIGIBLE_DECISION,
    reason_code: str,
    reason_detail: Mapping[str, Any] | None = None,
    commit: bool = False,
) -> OptimizationDecision:
    row = _build_ineligible_decision(
        organization_id=organization_id,
        project_id=project_id,
        request_id=request_id,
        client_dialect=client_dialect,
        requested_provider=requested_provider,
        requested_model=requested_model,
        candidate_provider=candidate_provider,
        candidate_model=candidate_model,
        decision=decision,
        reason_code=reason_code,
        reason_detail=reason_detail,
    )
    db.add(row)
    await db.flush()
    if commit:
        await db.commit()
    return row
