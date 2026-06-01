import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_api_key, resolve_project
from app.db.session import get_db
from app.models import Project, UsageEvent
from app.schemas import UsageEventCreate, UsageEventOut, UsageEventPage

router = APIRouter(tags=["usage-events"])


@router.post(
    "/usage-events",
    response_model=UsageEventOut,
    status_code=status.HTTP_201_CREATED,
)
def create_usage_event(
    payload: UsageEventCreate,
    project: Project = Depends(require_api_key),
    db: Session = Depends(get_db),
) -> UsageEvent:
    event = UsageEvent(
        project_id=project.id,
        provider=payload.provider,
        model=payload.model,
        operation=payload.operation,
        external_user_id=payload.external_user_id,
        workflow=payload.workflow,
        input_tokens=payload.input_tokens,
        output_tokens=payload.output_tokens,
        total_tokens=payload.input_tokens + payload.output_tokens,
        cost_usd=payload.cost_usd,
        currency=payload.currency,
        event_metadata=payload.metadata,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


@router.get("/usage-events", response_model=UsageEventPage)
def list_usage_events(
    project: Project = Depends(resolve_project),
    db: Session = Depends(get_db),
    provider: str | None = None,
    model: str | None = None,
    workflow: str | None = None,
    external_user_id: str | None = None,
    start: datetime | None = Query(default=None, description="received_at >= start (inclusive)"),
    end: datetime | None = Query(default=None, description="received_at <= end (inclusive)"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> UsageEventPage:
    stmt = select(UsageEvent).where(UsageEvent.project_id == project.id)
    if provider is not None:
        stmt = stmt.where(UsageEvent.provider == provider)
    if model is not None:
        stmt = stmt.where(UsageEvent.model == model)
    if workflow is not None:
        stmt = stmt.where(UsageEvent.workflow == workflow)
    if external_user_id is not None:
        stmt = stmt.where(UsageEvent.external_user_id == external_user_id)
    if start is not None:
        stmt = stmt.where(UsageEvent.received_at >= start)
    if end is not None:
        stmt = stmt.where(UsageEvent.received_at <= end)

    # id DESC is a stable tiebreaker so paging is deterministic when many rows
    # share a received_at. Fetch one extra to compute has_more without COUNT(*).
    stmt = (
        stmt.order_by(UsageEvent.received_at.desc(), UsageEvent.id.desc())
        .offset(offset)
        .limit(limit + 1)
    )
    rows = list(db.scalars(stmt))
    has_more = len(rows) > limit
    items = rows[:limit]
    return UsageEventPage(
        items=[UsageEventOut.model_validate(row) for row in items],
        limit=limit,
        offset=offset,
        has_more=has_more,
    )


@router.get("/usage-events/{event_id}", response_model=UsageEventOut)
def get_usage_event(
    event_id: uuid.UUID,
    project: Project = Depends(resolve_project),
    db: Session = Depends(get_db),
) -> UsageEvent:
    event = db.get(UsageEvent, event_id)
    if event is None or event.project_id != project.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="usage event not found"
        )
    return event
