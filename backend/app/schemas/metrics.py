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
