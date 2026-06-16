"""Customer-facing billing reads: plan/subscription, gain-share config, a live
preview of this month's billable amount, and invoice history. Operator-only
billing mutations (config, invoice generation) live in the operator router.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import billing as billing_service
from app.api.deps import resolve_project
from app.db.session import get_db
from app.models import Invoice, Organization, Project

router = APIRouter(tags=["billing"])


@router.get("/admin/billing", response_model=None)
def admin_billing(
    project: Project = Depends(resolve_project),
    db: Session = Depends(get_db),
) -> dict:
    """Plan, subscription, gain-share config, and a live preview of this month's
    billable amount (the org's VERIFIED savings times the gain-share percent, floor
    applied). The preview shows where the month is heading; the invoice is the
    authoritative record."""
    org = db.get(Organization, project.organization_id)
    preview = billing_service.current_period_billable(db, org)
    return {
        "plan_tier": org.plan_tier,
        "subscription_status": org.subscription_status,
        "plan_effective_at": org.plan_effective_at,
        "trial_ends_at": org.trial_ends_at,
        "pricing_model": "percentage_of_verified_savings_with_floor",
        "gain_share_percent": org.gain_share_percent,
        "monthly_fee_floor_usd": org.monthly_fee_floor_usd,
        "current_period": {
            "verified_savings_usd": preview.verified_savings_usd,
            "fee_usd": preview.fee_usd,
            "net_savings_usd": preview.net_savings_usd,
            "note": "Live preview of verified (measured) savings this month. Estimated savings are not billable.",
        },
    }


@router.get("/admin/billing/invoices", response_model=None)
def admin_billing_invoices(
    project: Project = Depends(resolve_project),
    db: Session = Depends(get_db),
    limit: int = 24,
) -> list[dict]:
    """Gain-share invoice history for this organization, newest first."""
    capped = max(1, min(limit, 120))
    return [
        {
            "id": str(inv.id),
            "period_start": inv.period_start,
            "period_end": inv.period_end,
            "verified_savings_usd": inv.verified_savings_usd,
            "gain_share_percent": inv.gain_share_percent,
            "fee_usd": inv.fee_usd,
            "net_savings_usd": inv.net_savings_usd,
            "currency": inv.currency,
            "status": inv.status,
            "created_at": inv.created_at,
        }
        for inv in db.scalars(
            select(Invoice)
            .where(Invoice.organization_id == project.organization_id)
            .order_by(Invoice.period_start.desc())
            .limit(capped)
        )
    ]
