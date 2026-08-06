"""Stripe self-serve upgrade: collect a payment method for Pro.

Varsten's price is a percentage of verified savings (billed through the Invoice
flow), not a fixed monthly charge, so Checkout runs in `setup` mode: it collects
and vaults a payment method on the customer. Completing checkout during a trial
marks the org ready to continue after the trial; it is not itself a paid-active
transition. There is intentionally no fixed-price subscription here.

All transitions funnel through `billing_lifecycle`, so this module only translates
Stripe events into those calls; it never invents its own billing-state rules. The
webhook is the one unauthenticated surface, so it is signature-verified and the
handler is idempotent (re-delivered events re-apply the same terminal state).
"""

import stripe
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import billing_lifecycle
from app.core.config import settings
from app.core.logging import get_logger
from app.models import Organization

logger = get_logger("varsten.stripe")


class BillingDisabled(RuntimeError):
    """Self-serve billing is turned off (no Stripe config). Endpoints map this to 503."""


def enabled() -> bool:
    return settings.self_serve_billing_enabled


def _require_enabled() -> None:
    if not enabled():
        raise BillingDisabled("self-serve billing is not enabled")


def _client() -> "stripe":
    _require_enabled()
    stripe.api_key = settings.stripe_secret_key
    return stripe


def ensure_customer(db: Session, org: Organization, *, email: str | None = None) -> str:
    """Return the org's Stripe customer id, creating the customer on first use. The
    caller commits; we set the id on the org so a later checkout reuses it."""
    if org.stripe_customer_id:
        return org.stripe_customer_id
    client = _client()
    customer = client.Customer.create(
        name=org.name,
        email=email,
        metadata={"organization_id": str(org.id)},
    )
    org.stripe_customer_id = customer["id"]
    return customer["id"]


def create_checkout_session(org: Organization, *, customer_id: str) -> str:
    """A Checkout Session in setup mode (collect a payment method). Returns its URL."""
    client = _client()
    session = client.checkout.Session.create(
        mode="setup",
        customer=customer_id,
        success_url=settings.billing_success_url,
        cancel_url=settings.billing_cancel_url,
        metadata={"organization_id": str(org.id)},
    )
    return session["url"]


def create_portal_session(org: Organization, *, customer_id: str) -> str:
    """A Billing Portal session so the customer can manage their payment method."""
    client = _client()
    session = client.billing_portal.Session.create(
        customer=customer_id,
        return_url=settings.billing_success_url,
    )
    return session["url"]


def construct_event(payload: bytes, sig_header: str | None) -> stripe.Event:
    """Verify and parse an inbound webhook. Raises on a bad/forged signature."""
    _require_enabled()
    if not sig_header:
        raise stripe.error.SignatureVerificationError("missing signature", None)
    return stripe.Webhook.construct_event(payload, sig_header, settings.stripe_webhook_secret)


def _org_by_customer(db: Session, customer_id: str | None) -> Organization | None:
    if not customer_id:
        return None
    return db.scalar(select(Organization).where(Organization.stripe_customer_id == customer_id))


def handle_event(db: Session, event: dict) -> bool:
    """Apply a verified Stripe event to the org's billing state. Idempotent. Returns
    True if it changed state. Unknown event types are ignored (return False)."""
    event_type = event.get("type")
    obj = (event.get("data") or {}).get("object") or {}
    customer_id = obj.get("customer")
    org = _org_by_customer(db, customer_id)
    if org is None:
        logger.warning("stripe event for unknown customer", extra={"type": event_type, "customer": customer_id})
        return False

    if event_type == "checkout.session.completed":
        # Setup-mode checkout finished. During a live trial this marks payment
        # readiness only; expired/canceled/past-due/free orgs are explicitly
        # reactivated by completing checkout.
        subscription_id = obj.get("subscription")  # null in setup mode; set if we ever use subscriptions
        if subscription_id:
            billing_lifecycle.activate_performance(org, stripe_subscription_id=subscription_id)
        else:
            billing_lifecycle.complete_payment_method_setup(org)
    elif event_type in ("customer.subscription.deleted",):
        billing_lifecycle.cancel_subscription(org)
    elif event_type in ("invoice.payment_failed",):
        billing_lifecycle.mark_past_due(org)
    else:
        return False

    db.commit()
    logger.info("stripe event applied", extra={"type": event_type, "organization_id": str(org.id)})
    return True
