"""Shared recommendation state transitions.

Both recommendation mutation endpoints call this module so apply/dismiss/rollback
cannot drift. Route-level membership still belongs in the API layer; this service
owns project scoping, entitlement gates, eval/governance gates, execution policy
changes, action logging, and the final durable status update.
"""

from datetime import UTC, datetime
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.auth.entitlements import require_performance
from app.engine import governance
from app.eval.gate import EvalGateError, apply_measured_savings, assert_appliable
from app.lever_controls import lever_enabled
from app.models import Project, Recommendation, RecommendationAction, User
from app.proxy.compression import TransformConflictError
from app.proxy.execution import activate_execution, deactivate_execution
from app.savings import record_applied_savings

RecommendationStatus = Literal["open", "applied", "dismissed", "rolled_back"]


def transition_recommendation(
    db: Session,
    *,
    project: Project,
    recommendation: Recommendation,
    actor: User,
    next_status: RecommendationStatus,
    now: datetime | None = None,
) -> Recommendation:
    """Apply the canonical transition for a recommendation status mutation."""
    if recommendation.project_id != project.id or recommendation.organization_id != project.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="recommendation not found")

    now = now or datetime.now(UTC)
    if next_status == "applied":
        _apply_recommendation(db, project=project, recommendation=recommendation, now=now, automated=False)
    elif next_status in {"dismissed", "rolled_back"}:
        deactivate_execution(db, recommendation)
        governance.mark_change_request_rolled_back(db, recommendation, now=now)

    recommendation.status = next_status
    recommendation.updated_at = now
    recommendation.resolved_at = now if next_status != "open" else None

    if next_status == "applied":
        record_applied_savings(db, project, recommendation, actor_user_id=actor.id, source="user", now=now)
    elif next_status != "open":
        db.add(
            RecommendationAction(
                organization_id=project.organization_id,
                project_id=project.id,
                recommendation_id=recommendation.id,
                actor_user_id=actor.id,
                lever=recommendation.lever,
                action_type=next_status,
                status="completed",
                source="user",
                title=recommendation.title,
                estimated_savings_usd=recommendation.estimated_monthly_savings_usd,
                occurred_at=now,
            )
        )

    db.commit()
    db.refresh(recommendation)
    return recommendation


def apply_recommendation_automated(
    db: Session,
    *,
    project: Project,
    recommendation: Recommendation,
    now: datetime | None = None,
) -> Recommendation:
    """Apply an open recommendation from the engine automation loop.

    This is intentionally narrower than the HTTP transition: it has no actor, records
    a system action, and passes ``automated=True`` through the eval gate so
    subjective/needs-human runs cannot slip into auto-apply.
    """
    if recommendation.project_id != project.id or recommendation.organization_id != project.organization_id:
        raise ValueError("recommendation does not belong to project")
    if recommendation.status != "open":
        return recommendation

    now = now or datetime.now(UTC)
    _apply_recommendation(db, project=project, recommendation=recommendation, now=now, automated=True)
    recommendation.status = "applied"
    recommendation.updated_at = now
    recommendation.resolved_at = now
    record_applied_savings(db, project, recommendation, actor_user_id=None, source="system", now=now)
    return recommendation


def _apply_recommendation(
    db: Session,
    *,
    project: Project,
    recommendation: Recommendation,
    now: datetime,
    automated: bool,
) -> None:
    require_performance(db, project, action="Applying a recommendation")
    if recommendation.lever and not lever_enabled(db, project.id, recommendation.lever):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{recommendation.lever} is turned off for this project.",
        )
    try:
        gating_run = assert_appliable(db, recommendation, automated=automated)
    except EvalGateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    try:
        governance.assert_change_request_approved(db, recommendation)
    except governance.GovernanceError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    apply_measured_savings(recommendation, gating_run)
    try:
        activate_execution(db, project, recommendation, gating_run, now=now)
    except TransformConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    governance.mark_change_request_active(db, recommendation, now=now)
