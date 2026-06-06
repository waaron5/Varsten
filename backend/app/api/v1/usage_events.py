import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import ApiKeyContext, require_api_key_context, resolve_project
from app.db.session import get_db
from app.models import Project, UsageEvent
from app.pricing import price_usage_event
from app.schemas import UsageEventCreate, UsageEventOut, UsageEventPage

router = APIRouter(tags=["usage-events"])


@router.post(
    "/usage-events",
    response_model=UsageEventOut,
    status_code=status.HTTP_201_CREATED,
)
def create_usage_event(
    payload: UsageEventCreate,
    response: Response,
    api_context: ApiKeyContext = Depends(require_api_key_context),
    db: Session = Depends(get_db),
) -> UsageEvent:
    project = api_context.project
    # v1 prices in USD only. Blending currencies in SUM(cost_usd) would silently
    # corrupt every total, so reject rather than guess an FX rate.
    if payload.currency.upper() != "USD":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="only USD is supported in v1",
        )

    # occurred_at picks the price version that was live when the call happened.
    at = payload.occurred_at or datetime.now(UTC)
    cost_usd, cost_source, pricing_status, price_version_id = price_usage_event(
        db,
        organization_id=project.organization_id,
        model_key=payload.model,
        provider=payload.provider,
        input_tokens=payload.input_tokens,
        output_tokens=payload.output_tokens,
        cached_input_tokens=payload.cached_input_tokens,
        reported_cost_usd=payload.cost_usd,
        at=at,
    )

    event = UsageEvent(
        project_id=project.id,
        organization_id=project.organization_id,
        api_key_id=api_context.api_key.id,
        provider=payload.provider,
        model=payload.model,
        operation=payload.operation,
        external_user_id=payload.external_user_id,
        workflow=payload.workflow,
        request_type=payload.request_type,
        feature=payload.feature,
        customer_id=payload.customer_id,
        user_id=payload.user_id,
        team=payload.team,
        department=payload.department,
        environment=payload.environment or "unknown",
        input_tokens=payload.input_tokens,
        output_tokens=payload.output_tokens,
        cached_input_tokens=payload.cached_input_tokens,
        reasoning_tokens=payload.reasoning_tokens,
        total_tokens=payload.input_tokens + payload.output_tokens,
        cost_usd=cost_usd,
        reported_cost_usd=payload.cost_usd,
        cost_source=cost_source,
        pricing_status=pricing_status,
        price_version_id=price_version_id,
        currency=payload.currency.upper(),
        status=payload.status,
        success=bool(payload.success),
        error_code=payload.error_code,
        latency_ms=payload.latency_ms,
        idempotency_key=payload.idempotency_key,
        event_timestamp=payload.event_timestamp,
        occurred_at=payload.occurred_at,
        event_metadata=payload.metadata,
    )
    db.add(event)
    try:
        db.commit()
    except IntegrityError:
        # A retry with a previously seen idempotency_key. Return the stored event
        # instead of double-counting spend.
        db.rollback()
        existing = db.scalar(
            select(UsageEvent).where(
                UsageEvent.project_id == project.id,
                UsageEvent.idempotency_key == payload.idempotency_key,
            )
        )
        if existing is None:
            raise
        response.status_code = status.HTTP_200_OK
        return existing
    db.refresh(event)
    # Recommendations are recomputed on read (overview / command center / engine),
    # never on the write path: a full month-scan per ingested event would cap
    # ingestion throughput, which is the endpoint that has to stay fast at volume.
    return event


@router.get("/usage-events", response_model=UsageEventPage)
def list_usage_events(
    project: Project = Depends(resolve_project),
    db: Session = Depends(get_db),
    provider: str | None = None,
    model: str | None = None,
    workflow: str | None = None,
    external_user_id: str | None = None,
    feature: str | None = None,
    customer_id: str | None = None,
    user_id: str | None = None,
    team: str | None = None,
    environment: str | None = None,
    request_type: str | None = None,
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
        stmt = stmt.where(UsageEvent.feature == workflow)
    if external_user_id is not None:
        stmt = stmt.where(UsageEvent.user_id == external_user_id)
    if feature is not None:
        stmt = stmt.where(UsageEvent.feature == feature)
    if customer_id is not None:
        stmt = stmt.where(UsageEvent.customer_id == customer_id)
    if user_id is not None:
        stmt = stmt.where(UsageEvent.user_id == user_id)
    if team is not None:
        stmt = stmt.where(UsageEvent.team == team)
    if environment is not None:
        stmt = stmt.where(UsageEvent.environment == environment)
    if request_type is not None:
        stmt = stmt.where(UsageEvent.request_type == request_type)
    if start is not None:
        stmt = stmt.where(UsageEvent.received_at >= start)
    if end is not None:
        stmt = stmt.where(UsageEvent.received_at <= end)

    # id DESC is a stable tiebreaker so paging is deterministic when many rows
    # share a received_at. Fetch one extra to compute has_more without COUNT(*).
    stmt = stmt.order_by(UsageEvent.received_at.desc(), UsageEvent.id.desc()).offset(offset).limit(limit + 1)
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="usage event not found")
    return event
