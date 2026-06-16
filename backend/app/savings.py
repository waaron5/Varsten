"""Realized-savings accounting.

When a recommendation is applied, Varsten records the savings it claims so the
Proof section reports numbers that trace back to a real recommendation, derived
from real usage and real pricing, rather than seeded constants.

v1 honesty: savings are the recommendation's run-rate *estimate*, labelled with
its measurement_method. A true randomized-holdback measurement (the product
guide's destination) needs elapsed time and is deferred. But the entire chain
here is computed, never hard-coded.
"""

import calendar
import uuid
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import TypedDict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    LeverConfig,
    Project,
    Recommendation,
    RecommendationAction,
    SavingsAttribution,
    UsageEvent,
)
from app.savings_measurement import METHOD_ESTIMATED, compute_verified_savings, is_measured

# Varsten's share of verified savings. One business parameter, not a fabricated
# output; later this moves to per-org billing config.
FEE_PERCENT = Decimal("0.20")

_CENTS = Decimal("0.01")


class SavingsSummary(TypedDict):
    period_start: datetime
    period_end: datetime
    actual_spend_usd: Decimal
    # NOTE: the gross/fee/net/counterfactual fields below are the ESTIMATED impact
    # of applied optimizations, derived from recommendation estimates. They are NOT
    # measured savings and must never be presented as "saved" — see the verified_*
    # fields, which are the audited number. Kept under these names for backward
    # compatibility with existing read paths.
    counterfactual_spend_usd: Decimal
    gross_savings_usd: Decimal
    varsten_fee_usd: Decimal
    net_savings_usd: Decimal
    # Estimated opportunity still on the table (open, not-yet-applied recommendations).
    estimated_opportunity_usd: Decimal
    # Verified (measured) savings — direct + holdback, from the ledger. The honest
    # "saved" number, with the fee and net Varsten can actually bill.
    direct_measured_usd: Decimal
    holdback_measured_usd: Decimal
    holdback_ci_low_usd: Decimal
    holdback_ci_high_usd: Decimal
    holdback_has_signal: bool
    verified_savings_usd: Decimal
    verified_fee_usd: Decimal
    verified_net_usd: Decimal
    billable_savings_usd: Decimal


def month_start(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def month_end(now: datetime) -> datetime:
    return (month_start(now) + timedelta(days=32)).replace(day=1) - timedelta(seconds=1)


def _q(value: Decimal) -> Decimal:
    return Decimal(value).quantize(_CENTS, rounding=ROUND_HALF_UP)


def _refresh_lever_savings(
    db: Session,
    project: Project,
    lever: str,
    period_start: datetime,
    period_end: datetime,
) -> None:
    """Set the lever's savings-to-date to the sum of its attributed savings this
    period, so the Levers screen never shows an invented number."""
    total = db.scalar(
        select(func.coalesce(func.sum(SavingsAttribution.gross_savings_usd), 0)).where(
            SavingsAttribution.project_id == project.id,
            SavingsAttribution.lever == lever,
            SavingsAttribution.period_start == period_start,
            SavingsAttribution.period_end == period_end,
        )
    ) or Decimal("0")
    config = db.scalar(select(LeverConfig).where(LeverConfig.project_id == project.id, LeverConfig.lever == lever))
    if config is not None:
        config.savings_to_date_usd = _q(total)


def record_applied_savings(
    db: Session,
    project: Project,
    recommendation: Recommendation,
    *,
    actor_user_id: uuid.UUID | None = None,
    source: str = "user",
    now: datetime | None = None,
) -> SavingsAttribution | None:
    """Record applying a recommendation: an action row (always) plus, when the
    recommendation carries a measurable lever savings, a savings attribution and a
    refreshed lever total. Returns the attribution, or None for a governance /
    unpriced recommendation that has no dollar lever savings to attribute."""
    now = now or datetime.now(UTC)
    start = month_start(now)
    end = month_end(now)
    gross_raw = recommendation.estimated_monthly_savings_usd

    action = RecommendationAction(
        organization_id=project.organization_id,
        project_id=project.id,
        recommendation_id=recommendation.id,
        actor_user_id=actor_user_id,
        lever=recommendation.lever,
        action_type="applied",
        status="completed",
        source=source,
        title=recommendation.title,
        estimated_savings_usd=gross_raw,
        occurred_at=now,
    )
    db.add(action)

    if recommendation.lever is None or gross_raw is None or gross_raw <= 0:
        return None

    gross = _q(gross_raw)
    fee = _q(gross * FEE_PERCENT)
    net = gross - fee

    # One attribution per (lever, period): re-applying refreshes it rather than
    # stacking duplicate savings.
    attribution = db.scalar(
        select(SavingsAttribution).where(
            SavingsAttribution.project_id == project.id,
            SavingsAttribution.lever == recommendation.lever,
            SavingsAttribution.period_start == start,
            SavingsAttribution.period_end == end,
        )
    )
    method = recommendation.measurement_method or METHOD_ESTIMATED
    # A row is "measured" only when its method is one of the measured methods
    # (replay/holdback/direct). Otherwise it is honestly an estimate.
    row_status = "measured" if is_measured(method) else "estimated"
    if attribution is None:
        attribution = SavingsAttribution(
            organization_id=project.organization_id,
            project_id=project.id,
            lever=recommendation.lever,
            measurement_method=method,
            status=row_status,
            period_start=start,
            period_end=end,
        )
        db.add(attribution)

    attribution.recommendation_id = recommendation.id
    attribution.measurement_method = method
    attribution.status = row_status
    attribution.gross_savings_usd = gross
    attribution.varsten_fee_usd = fee
    attribution.net_savings_usd = net
    attribution.confidence_low_usd = _q(gross * Decimal("0.80"))
    attribution.confidence_high_usd = _q(gross * Decimal("1.15"))
    attribution.notes = f"Derived from recommendation {recommendation.id} ({recommendation.measurement_method})."
    action.realized_savings_usd = net

    db.flush()
    _refresh_lever_savings(db, project, recommendation.lever, start, end)
    return attribution


def compute_savings_summary(db: Session, project: Project, now: datetime | None = None) -> SavingsSummary:
    """The month's savings accounting, derived end to end:

    actual          = month-to-date spend, run-rated to the full month
    gross           = sum of attributed lever savings this month
    counterfactual  = actual + gross (what spend would have been without the cuts)
    fee / net       = Varsten fee and the customer's net, from the attributions

    No value here is hard-coded; every number traces to usage events and applied
    recommendations.
    """
    now = now or datetime.now(UTC)
    start = month_start(now)
    end = month_end(now)

    actual_mtd = db.scalar(
        select(func.coalesce(func.sum(UsageEvent.cost_usd), 0)).where(
            UsageEvent.project_id == project.id, UsageEvent.received_at >= start
        )
    ) or Decimal("0")
    days_in_month = calendar.monthrange(now.year, now.month)[1]
    actual = _q(Decimal(actual_mtd) / Decimal(now.day) * Decimal(days_in_month)) if now.day else Decimal("0")

    agg = db.execute(
        select(
            func.coalesce(func.sum(SavingsAttribution.gross_savings_usd), 0).label("gross"),
            func.coalesce(func.sum(SavingsAttribution.varsten_fee_usd), 0).label("fee"),
            func.coalesce(func.sum(SavingsAttribution.net_savings_usd), 0).label("net"),
        ).where(
            SavingsAttribution.project_id == project.id,
            SavingsAttribution.period_start == start,
            SavingsAttribution.period_end == end,
        )
    ).one()
    gross = _q(agg.gross)
    fee = _q(agg.fee)
    net = _q(agg.net)

    # Estimated opportunity still open (not yet applied). Clearly an estimate.
    opportunity = db.scalar(
        select(func.coalesce(func.sum(Recommendation.estimated_monthly_savings_usd), 0)).where(
            Recommendation.project_id == project.id,
            Recommendation.status == "open",
        )
    ) or Decimal("0")

    # Verified (measured) savings from the ledger. This is the audited "saved"
    # number; the fee is charged on it (billable), never on the estimate.
    verified = compute_verified_savings(db, project.id, start, end)
    verified_gross = verified["verified_savings_usd"]
    verified_fee = _q(verified_gross * FEE_PERCENT)
    verified_net = verified_gross - verified_fee

    return {
        "period_start": start,
        "period_end": now,
        "actual_spend_usd": actual,
        "counterfactual_spend_usd": actual + gross,
        "gross_savings_usd": gross,
        "varsten_fee_usd": fee,
        "net_savings_usd": net,
        "estimated_opportunity_usd": _q(opportunity),
        "direct_measured_usd": verified["direct_measured_usd"],
        "holdback_measured_usd": verified["holdback_measured_usd"],
        "holdback_ci_low_usd": verified["holdback_ci_low_usd"],
        "holdback_ci_high_usd": verified["holdback_ci_high_usd"],
        "holdback_has_signal": verified["holdback_has_signal"],
        "verified_savings_usd": verified_gross,
        "verified_fee_usd": verified_fee,
        "verified_net_usd": verified_net,
        "billable_savings_usd": verified_gross,
    }
