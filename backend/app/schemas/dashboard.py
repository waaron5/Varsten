"""Consolidated dashboard snapshot.

One authoritative, period-scoped payload for the whole dashboard, computed in a
single read so every panel reconciles to the same window, fee, and savings
source (see app/savings.py::compute_savings_for_window). The frontend renders
this directly; it does not stitch together separate endpoints.
"""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel


class KpiDeltaOut(BaseModel):
    current: Decimal | None
    previous: Decimal | None
    # Signed fraction vs the same-elapsed prior window (0.18 == +18%). None when
    # not comparable (a side is absent, or the prior value is 0).
    delta_pct: Decimal | None


class DashboardKpi(BaseModel):
    key: str  # net_saved | gross_saved | without_varsten | actual_spend
    label: str
    detail: str
    value: Decimal | None
    delta: KpiDeltaOut
    tone: str | None = None  # "brand" marks the hero tile (net saved)


class SavingsTrendBucket(BaseModel):
    date: date
    optimized_usd: Decimal  # what was actually paid in the bucket
    saved_usd: Decimal  # measured (non-holdback) savings in the bucket
    baseline_usd: Decimal  # optimized + saved == naive-retail height


class TrendStats(BaseModel):
    # Per-bucket averages; the bucket size is the snapshot's granularity.
    avg_spend_per_bucket_usd: Decimal | None
    avg_saved_per_bucket_usd: Decimal | None
    effective_savings_rate: Decimal | None


class DashboardLever(BaseModel):
    lever: str
    label: str
    enabled: bool
    status: str  # "Active" | "Off"
    value_usd: Decimal | None
    share: Decimal | None  # fraction of gross this lever contributed
    source: str  # "measured" | "estimated" | ""


class DriverRow(BaseModel):
    key: str | None  # None is the untagged bucket
    label: str
    spend_usd: Decimal
    share: Decimal | None  # fraction of actual spend


class DashboardDrivers(BaseModel):
    actual_total_usd: Decimal | None
    team: list[DriverRow]
    feature: list[DriverRow]


class ProofTrust(BaseModel):
    score: Decimal | None  # 0..1 trust score (priced share)
    confidence_label: str
    confidence_note: str
    pricing_coverage: Decimal | None  # priced / (priced + unpriced)
    attribution_share: Decimal | None  # share of requests tagged with team or feature
    # Verified savings: the ledger-measured portion of the reported gross.
    verified_savings_usd: Decimal | None
    claimed_savings_usd: Decimal | None  # = gross savings being reported
    measured_share: Decimal | None  # verified / claimed, clamped [0,1]
    # Measurement method provenance.
    measurement_method_label: str  # "Direct + A/B" | "Direct ledger" | "A/B holdback" | "Not yet active"
    has_direct_ledger: bool
    has_ab_holdback: bool


class FallbackCoverageRow(BaseModel):
    """Per-provider fail-open readiness, derived from real traffic.

    ``sdk_enabled`` is true when traffic for this provider was seen carrying the
    Varsten fail-open SDK's ``X-Varsten-Client`` marker in the window -- the only
    integration that turns a Varsten outage into automatic direct-to-provider
    fallback. A provider with a key but no SDK is base-URL mode: it gets typed
    errors but no automatic fallback. Honest by construction: nothing here is
    hardcoded, it reflects what this project actually ran.
    """

    provider: str  # openai | anthropic | gemini
    label: str
    sdk_enabled: bool
    sdk_client: str | None  # the most recent SDK version string seen, if any
    key_configured: bool
    status: str  # "SDK enabled" | "Key set, no SDK" | "Not enabled"


class DashboardSnapshot(BaseModel):
    period: str  # month | quarter | year
    granularity: str  # day | week | month
    period_start: datetime
    period_end: datetime
    label: str
    mode: str  # measured | estimated | spend_only | empty
    fee_percent: Decimal  # the org gain-share fraction these numbers used
    gross_savings_usd: Decimal | None  # lever-footer total; reconciles with the gross_saved KPI
    # Auditable measured-savings provenance, surfaced at the top level so the UI can
    # bind the headline "Saved" figures directly to ledger facts instead of the
    # estimate-derived gross. verified is net of measurement and optimization
    # overhead -- the exact number billing charges the fee on.
    # Distinct from proof_trust.verified_savings_usd, which is clamped to the claimed
    # gross because it is the basis for the measured_share ratio.
    verified_savings_usd: Decimal | None
    verified_gross_savings_usd: Decimal | None = None
    measurement_cost_usd: Decimal | None = None
    optimization_overhead_cost_usd: Decimal | None = None
    direct_measured_usd: Decimal | None
    holdback_measured_usd: Decimal | None
    holdback_has_signal: bool
    kpis: list[DashboardKpi]
    savings_trend: list[SavingsTrendBucket]
    trend_stats: TrendStats
    levers: list[DashboardLever]
    drivers: DashboardDrivers
    proof_trust: ProofTrust
    # Per-provider fail-open coverage (OpenAI / Anthropic / Gemini). Always present
    # with one row per supported provider so the panel can show "not enabled" rows.
    fallback_coverage: list[FallbackCoverageRow]
