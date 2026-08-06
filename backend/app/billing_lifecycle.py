"""Central billing-state lifecycle for an organization.

Every billing-state transition lives here so Auth0 signup, trial expiration, the
entitlement read path, and Stripe activation never each invent their own rules.

Transitions mutate the passed Organization in place and do NOT commit; the caller
owns the transaction (one place decides when work is durable). Each transition that
changes entitlement-affecting state drops the process-local plan-tier cache so the
proxy hot path observes the change immediately.

A Stripe setup-mode checkout means "payment method ready", not "paid active".
During the trial that readiness is only stored; when the trial elapses, the lazy
read path / sweep either promotes the org to continuing active Pro or
downgrades it to Base.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import (
    PLAN_FREE,
    PLAN_PERFORMANCE,
    SUBSCRIPTION_ACTIVE,
    SUBSCRIPTION_CANCELED,
    SUBSCRIPTION_EXPIRED,
    SUBSCRIPTION_PAST_DUE,
    SUBSCRIPTION_TRIALING,
    Organization,
)


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(UTC)


def _invalidate(organization_id: uuid.UUID | None) -> None:
    # Lazy import: entitlements depends on this module's maybe_expire, so importing
    # it at module scope would be a cycle.
    if organization_id is None:
        return
    from app.auth.entitlements import invalidate_plan_tier

    invalidate_plan_tier(organization_id)


def start_trial(org: Organization, *, now: datetime | None = None) -> None:
    """Put a freshly provisioned workspace on the Pro plan, trialing for
    settings.free_trial_days. The single entry point for "a new org starts a trial"."""
    now = _now(now)
    org.plan_tier = PLAN_PERFORMANCE
    org.subscription_status = SUBSCRIPTION_TRIALING
    org.trial_started_at = now
    org.trial_ends_at = now + timedelta(days=settings.free_trial_days)
    org.plan_effective_at = now
    org.payment_method_ready_at = None
    _invalidate(org.id)


def activate_performance(
    org: Organization, *, stripe_subscription_id: str | None = None, now: datetime | None = None
) -> None:
    """Move an org to an active, continuing Pro plan."""
    now = _now(now)
    org.plan_tier = PLAN_PERFORMANCE
    org.subscription_status = SUBSCRIPTION_ACTIVE
    if stripe_subscription_id:
        org.stripe_subscription_id = stripe_subscription_id
    org.plan_effective_at = now
    _invalidate(org.id)


def has_payment_method_ready(org: Organization) -> bool:
    """True after setup-mode Checkout has confirmed a payment method is on file."""
    return org.payment_method_ready_at is not None


def complete_payment_method_setup(org: Organization, *, now: datetime | None = None) -> None:
    """Record setup-mode Checkout completion.

    If the org is still inside its trial, this only marks conversion readiness. If
    the org is expired/canceled/past_due/free, checkout is an explicit reactivation
    action and moves it to active Pro.
    """
    now = _now(now)
    if org.payment_method_ready_at is None:
        org.payment_method_ready_at = now
    if org.subscription_status == SUBSCRIPTION_TRIALING and not is_trial_elapsed(org, now=now):
        org.plan_tier = PLAN_PERFORMANCE
        _invalidate(org.id)
        return
    activate_performance(org, now=now)


def expire_trial(org: Organization, *, now: datetime | None = None) -> None:
    """Downgrade an unpaid, elapsed trial to Base. Traffic is never
    affected by this; only behaviour-changing levers lock (enforced in entitlements)."""
    now = _now(now)
    org.plan_tier = PLAN_FREE
    org.subscription_status = SUBSCRIPTION_EXPIRED
    org.plan_effective_at = now
    _invalidate(org.id)


def mark_past_due(org: Organization, *, now: datetime | None = None) -> None:
    """A payment failed. Treat as Base (entitlements gates on the status)
    without discarding the Stripe linkage, so a successful retry can reactivate."""
    org.subscription_status = SUBSCRIPTION_PAST_DUE
    org.plan_effective_at = _now(now)
    _invalidate(org.id)


def cancel_subscription(org: Organization, *, now: datetime | None = None) -> None:
    """A paid subscription ended (customer cancel / Stripe deletion). Back to Free."""
    now = _now(now)
    org.plan_tier = PLAN_FREE
    org.subscription_status = SUBSCRIPTION_CANCELED
    org.stripe_subscription_id = None
    org.plan_effective_at = now
    _invalidate(org.id)


def is_trial_expired(org: Organization, *, now: datetime | None = None) -> bool:
    """True when a trialing org has run past its end."""
    if org.subscription_status != SUBSCRIPTION_TRIALING:
        return False
    return is_trial_elapsed(org, now=now)


def is_trial_elapsed(org: Organization, *, now: datetime | None = None) -> bool:
    """True when the trial end timestamp has elapsed, independent of payment state."""
    end = org.trial_ends_at
    if end is None:
        return False
    if end.tzinfo is None:
        end = end.replace(tzinfo=UTC)
    return _now(now) >= end


def maybe_expire(org: Organization, *, now: datetime | None = None) -> bool:
    """Apply the trial-end transition on read.

    An elapsed trial with payment readiness becomes active continuing Pro;
    otherwise it becomes Base. Returns True if it changed durable state.
    """
    if is_trial_expired(org, now=now):
        if has_payment_method_ready(org):
            activate_performance(org, now=now)
        else:
            expire_trial(org, now=now)
        return True
    return False


def sweep_expired_trials(db: Session, *, now: datetime | None = None) -> list[uuid.UUID]:
    """Find every trialing org whose window elapsed and apply the trial-end transition.

    Returns the ids transitioned, whether they were promoted to active Pro
    or downgraded to Base.
    """
    now = _now(now)
    orgs = db.scalars(
        select(Organization).where(
            Organization.subscription_status == SUBSCRIPTION_TRIALING,
            Organization.trial_ends_at.is_not(None),
            Organization.trial_ends_at <= now,
        )
    ).all()
    transitioned: list[uuid.UUID] = []
    for org in orgs:
        if has_payment_method_ready(org):
            activate_performance(org, now=now)
        else:
            expire_trial(org, now=now)
        transitioned.append(org.id)
    if transitioned:
        db.commit()
    return transitioned
