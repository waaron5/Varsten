"""Production outcome feedback ingestion.

A customer reports what happened to a prior Varsten request (the user accepted /
rejected / edited / regenerated / escalated / overrode the output). This is the
implicit quality signal the eval harness cannot see, and a core moat input: it
turns "this path was cheaper" into "this path was cheaper AND the output held up."

Content-free: only an outcome label, an optional score, and a failure mode. The
request is tied to a prior decision via request_id (the X-Varsten-Request-Id the
proxy returned) and/or usage_event_id. Tenant isolation is enforced: a key may
only attach feedback to its own project's requests.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import ApiKeyContext, require_api_key_context
from app.db.session import get_db
from app.models import RequestDecisionEvent, RequestFeedback, UsageEvent
from app.schemas.feedback import FeedbackCreate, FeedbackOut

router = APIRouter(tags=["feedback"])


@router.post("/feedback", response_model=FeedbackOut, status_code=status.HTTP_201_CREATED)
def create_feedback(
    payload: FeedbackCreate,
    api_context: ApiKeyContext = Depends(require_api_key_context),
    db: Session = Depends(get_db),
) -> RequestFeedback:
    project = api_context.project

    usage_event_id: uuid.UUID | None = None
    decision_event_id: uuid.UUID | None = None

    # Validate any supplied usage_event_id belongs to this project (tenant isolation).
    if payload.usage_event_id is not None:
        owned = db.scalar(
            select(UsageEvent.id).where(
                UsageEvent.id == payload.usage_event_id,
                UsageEvent.project_id == project.id,
            )
        )
        if owned is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="usage event not found")
        usage_event_id = owned

    # Resolve the decision event from request_id (preferred) and backfill the
    # usage_event link from it when the caller only sent a request_id.
    if payload.request_id is not None:
        decision = db.scalar(
            select(RequestDecisionEvent)
            .where(
                RequestDecisionEvent.project_id == project.id,
                RequestDecisionEvent.request_id == payload.request_id,
            )
            .order_by(RequestDecisionEvent.created_at.desc())
            .limit(1)
        )
        if decision is not None:
            decision_event_id = decision.id
            if usage_event_id is None:
                usage_event_id = decision.usage_event_id

    feedback = RequestFeedback(
        organization_id=project.organization_id,
        project_id=project.id,
        usage_event_id=usage_event_id,
        decision_event_id=decision_event_id,
        request_id=payload.request_id,
        outcome=payload.outcome,
        quality_score=payload.quality_score,
        failure_mode=payload.failure_mode,
        source="customer",
        event_metadata=payload.metadata or {},
    )
    db.add(feedback)
    db.commit()
    db.refresh(feedback)
    return feedback
