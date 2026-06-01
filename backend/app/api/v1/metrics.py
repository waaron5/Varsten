from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_api_key
from app.db.session import get_db
from app.models import Project, UsageEvent
from app.schemas.metrics import (
    Breakdown,
    BreakdownRow,
    MetricsOverview,
    SpendTrend,
    SpendTrendPoint,
)

router = APIRouter(prefix="/metrics", tags=["metrics"])

# Whitelist of groupable columns. Keys are the public dimension names; values
# are the actual columns. Using a fixed map (not a raw string) keeps the
# GROUP BY column safe and the indexes meaningful.
BREAKDOWN_DIMENSIONS = {
    "provider": UsageEvent.provider,
    "model": UsageEvent.model,
    "workflow": UsageEvent.workflow,
    "external_user_id": UsageEvent.external_user_id,
}


def _utc_day_start(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


@router.get("/overview", response_model=MetricsOverview)
def overview(
    project: Project = Depends(require_api_key),
    db: Session = Depends(get_db),
) -> MetricsOverview:
    now = datetime.now(timezone.utc)
    day_start = _utc_day_start(now)
    month_start = day_start.replace(day=1)

    cost = UsageEvent.cost_usd
    recv = UsageEvent.received_at
    is_today = recv >= day_start

    # One scan bounded by month_start, with FILTER for the today subset, instead
    # of separate today/month queries.
    stmt = (
        select(
            func.coalesce(func.sum(cost).filter(is_today), 0).label("spend_today"),
            func.coalesce(func.sum(cost), 0).label("spend_month"),
            func.count().filter(is_today).label("requests_today"),
            func.count().label("requests_month"),
            func.coalesce(
                func.sum(UsageEvent.input_tokens).filter(is_today), 0
            ).label("input_tokens_today"),
            func.coalesce(
                func.sum(UsageEvent.output_tokens).filter(is_today), 0
            ).label("output_tokens_today"),
        )
        .where(UsageEvent.project_id == project.id, recv >= month_start)
    )
    row = db.execute(stmt).one()

    avg_today = row.spend_today / row.requests_today if row.requests_today else None
    return MetricsOverview(
        spend_today=row.spend_today,
        spend_month=row.spend_month,
        requests_today=row.requests_today,
        requests_month=row.requests_month,
        input_tokens_today=row.input_tokens_today,
        output_tokens_today=row.output_tokens_today,
        avg_cost_per_request_today=avg_today,
    )


@router.get("/spend-trend", response_model=SpendTrend)
def spend_trend(
    project: Project = Depends(require_api_key),
    db: Session = Depends(get_db),
    days: int = Query(default=30, ge=1, le=365),
) -> SpendTrend:
    now = datetime.now(timezone.utc)
    start = _utc_day_start(now) - timedelta(days=days - 1)

    day = func.date_trunc("day", UsageEvent.received_at).label("day")
    stmt = (
        select(
            day,
            func.coalesce(func.sum(UsageEvent.cost_usd), 0).label("spend"),
            func.count().label("requests"),
        )
        .where(UsageEvent.project_id == project.id, UsageEvent.received_at >= start)
        .group_by(day)
        .order_by(day)
    )
    points = [
        SpendTrendPoint(date=r.day.date(), spend=r.spend, requests=r.requests)
        for r in db.execute(stmt)
    ]
    return SpendTrend(granularity="day", points=points)


@router.get("/breakdown", response_model=Breakdown)
def breakdown(
    project: Project = Depends(require_api_key),
    db: Session = Depends(get_db),
    dimension: Literal["provider", "model", "workflow", "external_user_id"] = Query(
        ..., description="Column to group spend by"
    ),
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=10, ge=1, le=100),
) -> Breakdown:
    col = BREAKDOWN_DIMENSIONS[dimension]
    start = _utc_day_start(datetime.now(timezone.utc)) - timedelta(days=days - 1)

    spend = func.coalesce(func.sum(UsageEvent.cost_usd), 0).label("spend")
    stmt = (
        select(
            col.label("key"),
            spend,
            func.count().label("requests"),
            func.coalesce(func.sum(UsageEvent.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(UsageEvent.output_tokens), 0).label("output_tokens"),
        )
        .where(UsageEvent.project_id == project.id, UsageEvent.received_at >= start)
        .group_by(col)
        .order_by(spend.desc())
        .limit(limit)
    )
    rows = [
        BreakdownRow(
            key=r.key,
            spend=r.spend,
            requests=r.requests,
            input_tokens=r.input_tokens,
            output_tokens=r.output_tokens,
        )
        for r in db.execute(stmt)
    ]
    return Breakdown(dimension=dimension, rows=rows)
