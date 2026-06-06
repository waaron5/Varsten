import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_user, resolve_project
from app.db.session import get_db
from app.eval.gate import EvalGateError, apply_measured_savings, assert_appliable
from app.models import OrgMembership, Project, Recommendation, User
from app.proxy.execution import activate_execution, deactivate_execution
from app.recommendations import ensure_recommendations_fresh
from app.savings import record_applied_savings
from app.schemas import RecommendationOut, RecommendationUpdate

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


@router.get("", response_model=list[RecommendationOut])
def list_recommendations(
    project: Project = Depends(resolve_project),
    db: Session = Depends(get_db),
    status_filter: Literal["open", "applied", "dismissed", "rolled_back"] | None = Query(default=None, alias="status"),
) -> list[Recommendation]:
    ensure_recommendations_fresh(db, project)
    stmt = select(Recommendation).where(Recommendation.project_id == project.id)
    if status_filter is not None:
        stmt = stmt.where(Recommendation.status == status_filter)
    else:
        stmt = stmt.where(Recommendation.status == "open")
    stmt = stmt.order_by(Recommendation.created_at.desc())
    return list(db.scalars(stmt))


def _assert_can_update(user: User, recommendation: Recommendation, db: Session) -> None:
    membership = db.scalar(
        select(OrgMembership.id).where(
            OrgMembership.user_id == user.id,
            OrgMembership.organization_id == recommendation.organization_id,
        )
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="not a member of this recommendation's organization",
        )


@router.patch("/{recommendation_id}", response_model=RecommendationOut)
def update_recommendation(
    recommendation_id: uuid.UUID,
    payload: RecommendationUpdate,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> Recommendation:
    recommendation = db.get(Recommendation, recommendation_id)
    if recommendation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="recommendation not found")
    _assert_can_update(user, recommendation, db)
    now = datetime.now(UTC)
    if payload.status == "applied":
        # Medium-risk model-swap levers must clear a shadow eval first. The gate
        # raises if the route has not been proven safe; on a passing run it returns
        # the run so we attribute the MEASURED savings instead of the estimate.
        try:
            gating_run = assert_appliable(db, recommendation, automated=False)
        except EvalGateError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        apply_measured_savings(recommendation, gating_run)
        project = db.get(Project, recommendation.project_id)
        if project is not None:
            # Execution: activate the lever's policy (routing swap, trim transform, ...).
            activate_execution(db, project, recommendation, gating_run, now=now)
            record_applied_savings(db, project, recommendation, actor_user_id=user.id, source="user", now=now)
    elif payload.status in {"dismissed", "rolled_back"}:
        # Stop executing this lever; traffic returns to the original behaviour.
        deactivate_execution(db, recommendation)
    recommendation.status = payload.status
    recommendation.updated_at = now
    recommendation.resolved_at = now if payload.status != "open" else None
    db.commit()
    db.refresh(recommendation)
    return recommendation
