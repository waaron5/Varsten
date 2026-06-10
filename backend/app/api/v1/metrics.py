import calendar
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Numeric, cast, func, select
from sqlalchemy.orm import Session

from app.api.deps import resolve_project
from app.db.session import get_db
from app.models import BatchJob, Project, UsageEvent
from app.recommendations import ensure_recommendations_fresh
from app.schemas.metrics import (
    Breakdown,
    BreakdownRow,
    CacheTrafficPoint,
    LatencyPoint,
    MetricsOverview,
    ProxyTraffic,
    SavingsTrend,
    SavingsTrendPoint,
    SpendTrend,
    SpendTrendPoint,
)

# JSONB numeric extraction: event_metadata->>'saved_usd' cast to Numeric. Rows
# missing the key extract to NULL, which SUM ignores. saved_usd is written by the
# proxy for cache hits, routed requests, and batches.
_SAVED = cast(UsageEvent.event_metadata["saved_usd"].astext, Numeric)
_CACHE = UsageEvent.event_metadata["cache"].astext

router = APIRouter(prefix="/metrics", tags=["metrics"])

# Whitelist of groupable columns. Keys are the public dimension names; values
# are the actual columns. Using a fixed map (not a raw string) keeps the
# GROUP BY column safe and the indexes meaningful.
BREAKDOWN_DIMENSIONS = {
    "provider": UsageEvent.provider,
    "model": UsageEvent.model,
    "workflow": UsageEvent.feature,
    "external_user_id": UsageEvent.user_id,
    "feature": UsageEvent.feature,
    "customer_id": UsageEvent.customer_id,
    "user_id": UsageEvent.user_id,
    "team": UsageEvent.team,
    "department": UsageEvent.department,
    "environment": UsageEvent.environment,
    "request_type": UsageEvent.request_type,
}


def _utc_day_start(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


@router.get("/overview", response_model=MetricsOverview)
def overview(
    project: Project = Depends(resolve_project),
    db: Session = Depends(get_db),
) -> MetricsOverview:
    ensure_recommendations_fresh(db, project)

    now = datetime.now(UTC)
    day_start = _utc_day_start(now)
    month_start = day_start.replace(day=1)

    cost = UsageEvent.cost_usd
    recv = UsageEvent.received_at
    is_today = recv >= day_start
    is_catalog = UsageEvent.cost_source == "catalog"
    is_override = UsageEvent.cost_source == "override"
    is_reported = UsageEvent.cost_source == "reported"
    is_unknown = UsageEvent.cost_source == "unknown"
    is_priced = UsageEvent.pricing_status == "priced"
    is_unpriced = UsageEvent.pricing_status != "priced"

    # One scan bounded by month_start, with FILTER for the today subset, instead
    # of separate today/month queries.
    stmt = select(
        func.coalesce(func.sum(cost).filter(is_today), 0).label("spend_today"),
        func.coalesce(func.sum(cost), 0).label("spend_month"),
        func.coalesce(func.sum(cost).filter(is_catalog), 0).label("catalog_spend_month"),
        func.coalesce(func.sum(cost).filter(is_override), 0).label("override_spend_month"),
        func.coalesce(func.sum(cost).filter(is_reported), 0).label("reported_spend_month"),
        func.coalesce(func.sum(cost).filter(is_unknown), 0).label("unknown_spend_month"),
        func.coalesce(func.sum(cost).filter(is_catalog | is_override), 0).label("authoritative_spend_month"),
        func.count().filter(is_today).label("requests_today"),
        func.count().label("requests_month"),
        func.count().filter(is_priced).label("priced_event_count_month"),
        func.count().filter(is_unpriced).label("unpriced_event_count_month"),
        func.coalesce(func.sum(UsageEvent.total_tokens).filter(is_unpriced), 0).label("unpriced_token_count_month"),
        func.coalesce(func.sum(UsageEvent.input_tokens).filter(is_today), 0).label("input_tokens_today"),
        func.coalesce(func.sum(UsageEvent.output_tokens).filter(is_today), 0).label("output_tokens_today"),
        func.count().filter(UsageEvent.feature.is_not(None)).label("feature_tagged"),
        func.count().filter(UsageEvent.customer_id.is_not(None)).label("customer_tagged"),
        func.count().filter(UsageEvent.team.is_not(None)).label("team_tagged"),
        func.count()
        .filter((UsageEvent.environment.is_not(None)) & (UsageEvent.environment != "unknown"))
        .label("environment_tagged"),
    ).where(UsageEvent.project_id == project.id, recv >= month_start)
    row = db.execute(stmt).one()

    avg_today = row.spend_today / row.requests_today if row.requests_today else None
    trust_share = row.authoritative_spend_month / row.spend_month if row.spend_month else None
    days_in_month = calendar.monthrange(now.year, now.month)[1]
    monthly_forecast = row.spend_month / Decimal(now.day) * Decimal(days_in_month) if now.day else Decimal("0")
    budget = project.organization.monthly_spend_budget_usd
    budget_variance = monthly_forecast - budget if budget is not None else None
    budget_burn = row.spend_month / budget if budget else None
    unpriced_share = (
        Decimal(row.unpriced_event_count_month) / Decimal(row.requests_month) if row.requests_month else None
    )

    def quality(count: int) -> Decimal | None:
        return Decimal(count) / Decimal(row.requests_month) if row.requests_month else None

    return MetricsOverview(
        spend_today=row.spend_today,
        spend_month=row.spend_month,
        requests_today=row.requests_today,
        requests_month=row.requests_month,
        input_tokens_today=row.input_tokens_today,
        output_tokens_today=row.output_tokens_today,
        avg_cost_per_request_today=avg_today,
        monthly_forecast_usd=monthly_forecast,
        monthly_budget_usd=budget,
        budget_variance_usd=budget_variance,
        budget_burn_percent=budget_burn,
        days_elapsed_days_remaining=f"{now.day}/{days_in_month - now.day}",
        authoritative_spend_month=row.authoritative_spend_month,
        authoritative_spend_share_month=trust_share,
        catalog_spend_month=row.catalog_spend_month,
        override_spend_month=row.override_spend_month,
        reported_spend_month=row.reported_spend_month,
        unknown_spend_month=row.unknown_spend_month,
        priced_event_count_month=row.priced_event_count_month,
        unpriced_event_count_month=row.unpriced_event_count_month,
        unpriced_token_count_month=row.unpriced_token_count_month,
        unpriced_event_share_month=unpriced_share,
        metadata_quality={
            "feature": quality(row.feature_tagged),
            "customer_id": quality(row.customer_tagged),
            "team": quality(row.team_tagged),
            "environment": quality(row.environment_tagged),
        },
    )


@router.get("/spend-trend", response_model=SpendTrend)
def spend_trend(
    project: Project = Depends(resolve_project),
    db: Session = Depends(get_db),
    days: int = Query(default=30, ge=1, le=365),
) -> SpendTrend:
    now = datetime.now(UTC)
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
    points = [SpendTrendPoint(date=r.day.date(), spend=r.spend, requests=r.requests) for r in db.execute(stmt)]
    return SpendTrend(granularity="day", points=points)


@router.get("/savings-trend", response_model=SavingsTrend)
def savings_trend(
    project: Project = Depends(resolve_project),
    db: Session = Depends(get_db),
    days: int = Query(default=30, ge=1, le=365),
) -> SavingsTrend:
    """Saved-vs-baseline over time, the Proof/Margin narrative. baseline is naive
    retail (optimized + saved); the cumulative line is what a CFO watches climb.
    All derived from the ledger: optimized = SUM(cost_usd), saved = SUM(saved_usd)."""
    now = datetime.now(UTC)
    start = _utc_day_start(now) - timedelta(days=days - 1)

    day = func.date_trunc("day", UsageEvent.received_at).label("day")
    stmt = (
        select(
            day,
            func.coalesce(func.sum(UsageEvent.cost_usd), 0).label("optimized"),
            func.coalesce(func.sum(_SAVED), 0).label("saved"),
        )
        .where(UsageEvent.project_id == project.id, UsageEvent.received_at >= start)
        .group_by(day)
        .order_by(day)
    )

    points: list[SavingsTrendPoint] = []
    cumulative = Decimal("0")
    total_saved = Decimal("0")
    total_baseline = Decimal("0")
    for r in db.execute(stmt):
        optimized = Decimal(r.optimized)
        saved = Decimal(r.saved)
        baseline = optimized + saved
        cumulative += saved
        total_saved += saved
        total_baseline += baseline
        points.append(
            SavingsTrendPoint(
                date=r.day.date(),
                baseline_usd=baseline,
                optimized_usd=optimized,
                saved_usd=saved,
                cumulative_saved_usd=cumulative,
            )
        )
    return SavingsTrend(
        granularity="day",
        points=points,
        total_saved_usd=total_saved,
        total_baseline_usd=total_baseline,
    )


@router.get("/proxy-traffic", response_model=ProxyTraffic)
def proxy_traffic(
    project: Project = Depends(resolve_project),
    db: Session = Depends(get_db),
    days: int = Query(default=30, ge=1, le=365),
) -> ProxyTraffic:
    """Cache hit-rate, batching volume, and latency health for proxy traffic. The
    latency percentiles are over events that carry a captured latency, so they read
    null on a project with no proxy traffic yet rather than showing a fake number."""
    now = datetime.now(UTC)
    start = _utc_day_start(now) - timedelta(days=days - 1)
    proxy_window = (
        UsageEvent.project_id == project.id,
        UsageEvent.received_at >= start,
        UsageEvent.feature == "proxy",
    )

    is_hit = _CACHE == "hit"
    is_miss = _CACHE == "miss"
    totals = db.execute(
        select(
            func.count().label("requests"),
            func.count().filter(is_hit).label("hit"),
            func.count().filter(is_miss).label("miss"),
            func.coalesce(func.sum(_SAVED).filter(is_hit), 0).label("cache_saved"),
            func.percentile_cont(0.5).within_group(UsageEvent.latency_ms).label("p50"),
            func.percentile_cont(0.95).within_group(UsageEvent.latency_ms).label("p95"),
            func.percentile_cont(0.99).within_group(UsageEvent.latency_ms).label("p99"),
        ).where(*proxy_window)
    ).one()

    hit_rate = Decimal(totals.hit) / Decimal(totals.requests) if totals.requests else None

    # Per-day cache hit-rate series.
    day = func.date_trunc("day", UsageEvent.received_at).label("day")
    series_rows = db.execute(
        select(
            day,
            func.count().label("requests"),
            func.count().filter(is_hit).label("hit"),
            func.percentile_cont(0.5).within_group(UsageEvent.latency_ms).label("p50"),
            func.percentile_cont(0.95).within_group(UsageEvent.latency_ms).label("p95"),
            func.percentile_cont(0.99).within_group(UsageEvent.latency_ms).label("p99"),
        )
        .where(*proxy_window)
        .group_by(day)
        .order_by(day)
    ).all()
    cache_series = [
        CacheTrafficPoint(
            date=r.day.date(),
            requests=r.requests,
            hit_rate=(Decimal(r.hit) / Decimal(r.requests) if r.requests else None),
        )
        for r in series_rows
    ]
    latency_series = [
        LatencyPoint(
            date=r.day.date(),
            p50_ms=int(r.p50) if r.p50 is not None else None,
            p95_ms=int(r.p95) if r.p95 is not None else None,
            p99_ms=int(r.p99) if r.p99 is not None else None,
        )
        for r in series_rows
    ]

    batch = db.execute(
        select(
            func.count().label("jobs"),
            func.coalesce(func.sum(BatchJob.request_count), 0).label("requests"),
            func.coalesce(func.sum(BatchJob.saved_usd), 0).label("saved"),
        ).where(BatchJob.project_id == project.id, BatchJob.created_at >= start)
    ).one()

    return ProxyTraffic(
        window_days=days,
        requests=totals.requests,
        hit=totals.hit,
        miss=totals.miss,
        hit_rate=hit_rate,
        cache_saved_usd=Decimal(totals.cache_saved),
        cache_series=cache_series,
        batch_jobs=batch.jobs,
        batch_requests=batch.requests,
        batch_saved_usd=Decimal(batch.saved),
        latency_p50_ms=int(totals.p50) if totals.p50 is not None else None,
        latency_p95_ms=int(totals.p95) if totals.p95 is not None else None,
        latency_p99_ms=int(totals.p99) if totals.p99 is not None else None,
        latency_series=latency_series,
    )


@router.get("/breakdown", response_model=Breakdown)
def breakdown(
    project: Project = Depends(resolve_project),
    db: Session = Depends(get_db),
    dimension: Literal[
        "provider",
        "model",
        "workflow",
        "external_user_id",
        "feature",
        "customer_id",
        "user_id",
        "team",
        "department",
        "environment",
        "request_type",
    ] = Query(..., description="Column to group spend by"),
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=10, ge=1, le=100),
) -> Breakdown:
    col = BREAKDOWN_DIMENSIONS[dimension]
    start = _utc_day_start(datetime.now(UTC)) - timedelta(days=days - 1)

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
