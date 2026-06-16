"""Gain-share billing, computed from verified savings.

The fee is the org's gain-share percent of VERIFIED (measured) savings, with a
monthly floor. The floor is always capped at the savings, so the customer's net
is never negative -- the "no-brainer" guarantee. Estimated savings never bill.

Manual today: an operator generates an invoice for a period; there is no
auto-charge and no Stripe yet. The Invoice row is the durable billing record.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Invoice, Organization, Project
from app.savings import month_end, month_start
from app.savings_measurement import compute_verified_savings

_CENTS = Decimal("0.01")


def _q(value: Decimal) -> Decimal:
    return Decimal(value).quantize(_CENTS, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Billable:
    verified_savings_usd: Decimal
    gain_share_percent: Decimal
    monthly_fee_floor_usd: Decimal
    fee_usd: Decimal
    net_savings_usd: Decimal


def compute_fee(verified_savings: Decimal, percent: Decimal, floor: Decimal) -> Billable:
    """The fee on verified savings: percent of savings, lifted to the floor, then
    capped at the savings so net is always >= 0."""
    gross = _q(verified_savings)
    fee = _q(gross * percent)
    if floor > 0:
        fee = max(fee, _q(floor))
    # Never charge more than was verifiably saved -> the customer's net stays >= 0.
    fee = min(fee, gross)
    return Billable(
        verified_savings_usd=gross,
        gain_share_percent=percent,
        monthly_fee_floor_usd=_q(floor),
        fee_usd=fee,
        net_savings_usd=gross - fee,
    )


def org_verified_savings(db: Session, org: Organization, start: datetime, end: datetime) -> Decimal:
    """Verified savings for the whole org this period: the sum across its projects."""
    total = Decimal("0")
    for project in db.scalars(select(Project).where(Project.organization_id == org.id)):
        total += compute_verified_savings(db, project.id, start, end)["verified_savings_usd"]
    return _q(total)


def current_period_billable(db: Session, org: Organization, now: datetime | None = None) -> Billable:
    """A live preview of this month's billable amount (not persisted)."""
    now = now or datetime.now(UTC)
    start = month_start(now)
    end = month_end(now)
    verified = org_verified_savings(db, org, start, end)
    return compute_fee(verified, Decimal(org.gain_share_percent), Decimal(org.monthly_fee_floor_usd))


def generate_invoice(
    db: Session,
    org: Organization,
    period_start: datetime,
    period_end: datetime,
) -> Invoice:
    """Create or refresh the draft invoice for a period from verified savings. The
    rate/floor are snapshotted onto the row so a later config change never rewrites
    history. Re-generating a draft refreshes it; a finalized invoice is left alone."""
    verified = org_verified_savings(db, org, period_start, period_end)
    billable = compute_fee(verified, Decimal(org.gain_share_percent), Decimal(org.monthly_fee_floor_usd))

    invoice = db.scalar(
        select(Invoice).where(
            Invoice.organization_id == org.id,
            Invoice.period_start == period_start,
            Invoice.period_end == period_end,
        )
    )
    if invoice is not None and invoice.status != "draft":
        # Finalized/sent/paid invoices are immutable; return as-is.
        return invoice
    if invoice is None:
        invoice = Invoice(
            organization_id=org.id,
            period_start=period_start,
            period_end=period_end,
        )
        db.add(invoice)

    invoice.verified_savings_usd = billable.verified_savings_usd
    invoice.gain_share_percent = billable.gain_share_percent
    invoice.monthly_fee_floor_usd = billable.monthly_fee_floor_usd
    invoice.fee_usd = billable.fee_usd
    invoice.net_savings_usd = billable.net_savings_usd
    invoice.status = "draft"
    invoice.notes = "Gain-share on verified (measured) savings. Estimated savings are excluded."
    db.commit()
    db.refresh(invoice)
    return invoice


def previous_month_period(now: datetime | None = None) -> tuple[datetime, datetime]:
    """The last fully-elapsed month, the natural default billing period."""
    now = now or datetime.now(UTC)
    this_month_start = month_start(now)
    prev_end = this_month_start
    prev_start = month_start(this_month_start - timedelta(days=1))
    return prev_start, prev_end
