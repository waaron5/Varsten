"""Customer-facing billing reads: plan/subscription, gain-share config, a live
preview of this month's billable amount, and invoice history. Operator-only
billing mutations (config, invoice generation) live in the operator router.
"""

import json

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import billing as billing_service
from app import stripe_billing
from app.api.deps import require_org_member, require_user, resolve_project
from app.core.logging import get_logger
from app.db.session import get_db
from app.models import Invoice, Organization, Project, User

logger = get_logger("varsten.api.billing")

router = APIRouter(tags=["billing"])


def _require_billing_enabled() -> None:
    if not stripe_billing.enabled():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "billing_disabled", "message": "Self-serve billing is not enabled."},
        )


@router.get("/admin/billing", response_model=None)
def admin_billing(
    project: Project = Depends(resolve_project),
    db: Session = Depends(get_db),
) -> dict:
    """Plan, subscription, gain-share config, and a live preview of this month's
    billable amount (the org's VERIFIED savings times the gain-share percent,
    capped at 25%, with any floor capped at the same maximum). The preview shows
    where the month is heading; the invoice is the authoritative record."""
    org = db.get(Organization, project.organization_id)
    preview = billing_service.current_period_billable(db, org)
    return {
        "plan_tier": org.plan_tier,
        "subscription_status": org.subscription_status,
        "plan_effective_at": org.plan_effective_at,
        "trial_ends_at": org.trial_ends_at,
        "payment_method_ready_at": org.payment_method_ready_at,
        "pricing_model": "percentage_of_verified_savings_capped_at_25_percent",
        "gain_share_percent": billing_service.effective_gain_share_percent(org.gain_share_percent),
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


# --- Self-serve upgrade (Stripe). Org-level: billing is per workspace, not per
# project, so these are authorized by org membership, not a project_id. ----------


@router.post("/organizations/{organization_id}/billing/checkout-session", response_model=None)
def create_checkout_session(
    org: Organization = Depends(require_org_member),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    """Start Stripe Checkout (setup mode) to add a payment method.

    During an active trial, completion marks the org ready to continue after the
    trial. Expired/canceled/past-due/free orgs are reactivated by completion.
    Returns the hosted Checkout URL for the client to redirect to.
    """
    _require_billing_enabled()
    try:
        customer_id = stripe_billing.ensure_customer(db, org, email=user.email)
        url = stripe_billing.create_checkout_session(org, customer_id=customer_id)
        db.commit()
    except stripe_billing.BillingDisabled as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="billing disabled") from exc
    except stripe.error.StripeError as exc:
        logger.warning("stripe checkout failed", extra={"organization_id": str(org.id), "error": str(exc)})
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="could not start checkout") from exc
    return {"url": url}


@router.post("/organizations/{organization_id}/billing/portal-session", response_model=None)
def create_portal_session(
    org: Organization = Depends(require_org_member),
    db: Session = Depends(get_db),
) -> dict:
    """A Stripe Billing Portal session so the customer can manage their payment
    method. Requires an existing Stripe customer (created during checkout)."""
    _require_billing_enabled()
    if not org.stripe_customer_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "no_stripe_customer", "message": "Add a payment method first."},
        )
    try:
        url = stripe_billing.create_portal_session(org, customer_id=org.stripe_customer_id)
    except stripe_billing.BillingDisabled as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="billing disabled") from exc
    except stripe.error.StripeError as exc:
        logger.warning("stripe portal failed", extra={"organization_id": str(org.id), "error": str(exc)})
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="could not open billing portal") from exc
    return {"url": url}


# The webhook is unauthenticated (Stripe calls it) but signature-verified. Kept on
# its own router with no auth dependency so it never inherits session auth.
webhook_router = APIRouter(tags=["billing"])


@webhook_router.post("/webhooks/stripe", response_model=None)
async def stripe_webhook(request: Request, db: Session = Depends(get_db)) -> dict:
    """Receive Stripe events, verify the signature, and apply billing-state changes.
    A forged or unverifiable event is rejected before it can touch any plan."""
    if not stripe_billing.enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    try:
        stripe_billing.construct_event(payload, sig_header)  # verify signature only
    except (stripe.error.SignatureVerificationError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid signature") from exc
    # The signature is verified against the exact raw bytes, so parsing them as JSON
    # gives a plain nested dict without Stripe's lazy typed wrappers.
    handled = stripe_billing.handle_event(db, json.loads(payload))
    return {"received": True, "handled": handled}
