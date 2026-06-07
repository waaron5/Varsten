from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class MetricsOverview(BaseModel):
    """Stat-card numbers for the overview dashboard. Windows are UTC-day based
    (v1 has no per-org timezone setting yet)."""

    spend_today: Decimal
    spend_month: Decimal
    requests_today: int
    requests_month: int
    input_tokens_today: int
    output_tokens_today: int
    avg_cost_per_request_today: Decimal | None
    monthly_forecast_usd: Decimal
    monthly_budget_usd: Decimal | None
    budget_variance_usd: Decimal | None
    budget_burn_percent: Decimal | None
    days_elapsed_days_remaining: str
    # Trust signal: share of this month's spend that Varsten priced itself
    # (catalog or per-org override) vs echoed from the client
    # (reported). None when there is no spend yet.
    authoritative_spend_month: Decimal
    authoritative_spend_share_month: Decimal | None
    catalog_spend_month: Decimal
    override_spend_month: Decimal
    reported_spend_month: Decimal
    unknown_spend_month: Decimal
    priced_event_count_month: int
    unpriced_event_count_month: int
    unpriced_token_count_month: int
    unpriced_event_share_month: Decimal | None
    metadata_quality: dict[str, Decimal | None]


class SpendTrendPoint(BaseModel):
    date: date
    spend: Decimal
    requests: int


class SpendTrend(BaseModel):
    """Daily spend buckets. Only days with events are returned; gap-filling is a
    frontend/follow-up concern."""

    granularity: str
    points: list[SpendTrendPoint]


class BreakdownRow(BaseModel):
    # None is the untagged bucket (nullable workflow / external_user_id).
    key: str | None
    spend: Decimal
    requests: int
    input_tokens: int
    output_tokens: int


class Breakdown(BaseModel):
    dimension: str
    rows: list[BreakdownRow]


# --- Command Center narrative 1: savings vs baseline over time ---


class SavingsTrendPoint(BaseModel):
    date: date
    # baseline = naive retail (what it would have cost without Varsten) =
    # optimized + saved; optimized = actual Varsten-metered spend.
    baseline_usd: Decimal
    optimized_usd: Decimal
    saved_usd: Decimal
    cumulative_saved_usd: Decimal


class SavingsTrend(BaseModel):
    granularity: str
    points: list[SavingsTrendPoint]
    total_saved_usd: Decimal
    total_baseline_usd: Decimal


# --- Command Center narrative 2: proxy traffic health ---


class CacheTrafficPoint(BaseModel):
    date: date
    requests: int
    hit_rate: Decimal | None


class LatencyPoint(BaseModel):
    date: date
    p50_ms: int | None
    p95_ms: int | None


class ProxyTraffic(BaseModel):
    """Cache, batching, and latency health for proxy traffic over the window.

    The ledger records cache as hit vs miss (exact-hash is the Day One lever;
    semantic, when enabled, is also counted as a hit). Latency is the per-event
    proxy time-to-first-byte; percentiles are over events that carry it, so a
    fresh project reports null until proxy traffic accrues."""

    window_days: int
    requests: int
    hit: int
    miss: int
    hit_rate: Decimal | None
    cache_saved_usd: Decimal
    cache_series: list[CacheTrafficPoint]
    batch_jobs: int
    batch_requests: int
    batch_saved_usd: Decimal
    latency_p50_ms: int | None
    latency_p95_ms: int | None
    latency_p99_ms: int | None
    latency_series: list[LatencyPoint]
