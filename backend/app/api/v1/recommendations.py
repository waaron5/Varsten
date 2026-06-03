import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_user, resolve_project
from app.db.session import get_db
from app.models import OrgMembership, Project, Recommendation, User
from app.recommendations import ensure_recommendations_fresh
from app.savings import record_applied_savings
from app.schemas import RecommendationOut, RecommendationUpdate

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


@router.get("", response_model=list[RecommendationOut])
def list_recommendations(
    project: Project = Depends(resolve_project),
    db: Session = Depends(get_db),
    status_filter: Literal["open", "applied", "dismissed", "rolled_back"] | None = Query(
        default=None, alias="status"
    ),
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="recommendation not found"
        )
    _assert_can_update(user, recommendation, db)
    now = datetime.now(timezone.utc)
    recommendation.status = payload.status
    recommendation.updated_at = now
    recommendation.resolved_at = now if payload.status != "open" else None
    if payload.status == "applied":
        project = db.get(Project, recommendation.project_id)
        if project is not None:
            record_applied_savings(
                db, project, recommendation, actor_user_id=user.id, source="user", now=now
            )
    db.commit()
    db.refresh(recommendation)
    return recommendation
