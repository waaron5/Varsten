"""Plan-tier entitlements and observe-only enforcement.

Free is observe-only: Varsten meters, prices, records decision evidence, and
recommends, but may never activate a behaviour-changing lever. Optimize unlocks
the savings levers. This is the single backend chokepoint that keeps a
free workspace from accidentally altering production AI traffic.

Enforcement lives here (not in the frontend) and is applied at the points where
an enabled, behaviour-changing proxy_policy / lever_config would be created:
applying a recommendation, enabling a route/trim policy, enabling a lever or its
automation, and submitting a batch. The proxy itself only ever acts on enabled
policies, so a free org that can never create one stays observe-only by
construction.
"""

import threading
import uuid
from datetime import UTC, datetime, timedelta
from typing import NamedTuple

from cachetools import TTLCache
from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app import billing_lifecycle
from app.core.config import settings
from app.models import (
    PLAN_FREE,
    PLAN_PERFORMANCE,
    SUBSCRIPTION_CANCELED,
    SUBSCRIPTION_EXPIRED,
    SUBSCRIPTION_PAST_DUE,
    SUBSCRIPTION_TRIALING,
    Organization,
    Project,
    UsageEvent,
)

FEATURE_REQUIRES_PERFORMANCE = "feature_requires_performance"

# Process-local plan-tier cache so the proxy hot path can decide observe-only
# without a DB read every request. Short TTL plus explicit invalidation on a plan
# change keeps it from going stale. Single-process (mirrors the provider-key cache).
_TIER_TTL_SECONDS = 60


class EntitlementState(NamedTuple):
    plan_tier: str
    observe_only: bool
    reason: str | None
    monthly_requests: int
    monthly_request_limit: int
    requests_remaining: int | None
    trial_ends_at: datetime | None
    trial_expired: bool


_tier_cache: TTLCache[str, EntitlementState] = TTLCache(maxsize=8192, ttl=_TIER_TTL_SECONDS)
_tier_lock = threading.Lock()


def invalidate_plan_tier(organization_id: uuid.UUID | None = None) -> None:
    """Drop a cached tier (or all) after a plan change so it takes effect at once."""
    with _tier_lock:
        if organization_id is None:
            _tier_cache.clear()
        else:
            _tier_cache.pop(str(organization_id), None)


def is_performance(db: Session, project: Project) -> bool:
    state = entitlement_state_for_project(db, project)
    return state.plan_tier == PLAN_PERFORMANCE and not state.observe_only


def _month_start(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _default_trial_end(org: Organization) -> datetime | None:
    if org.subscription_status != SUBSCRIPTION_TRIALING:
        return org.trial_ends_at
    if org.trial_ends_at is not None:
        return org.trial_ends_at
    created = org.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return created + timedelta(days=settings.free_trial_days)


def _requests_remaining(monthly_requests: int, limit: int) -> int:
    return max(0, limit - monthly_requests)


def _entitlement_state(
    *,
    monthly_requests: int,
    now: datetime,
    org: Organization | None,
) -> EntitlementState:
    limit = settings.free_monthly_request_limit
    if org is None:
        return EntitlementState(
            plan_tier=PLAN_FREE,
            observe_only=True,
            reason="missing_organization",
            monthly_requests=monthly_requests,
            monthly_request_limit=limit,
            requests_remaining=_requests_remaining(monthly_requests, limit),
            trial_ends_at=None,
            trial_expired=False,
        )

    plan_tier = org.plan_tier or PLAN_FREE
    trial_ends_at = _default_trial_end(org)
    trial_expired = bool(org.subscription_status == SUBSCRIPTION_TRIALING and trial_ends_at and now >= trial_ends_at)
    quota_exceeded = bool(org.subscription_status == SUBSCRIPTION_TRIALING and limit > 0 and monthly_requests >= limit)

    reason: str | None = None
    observe_only = plan_tier != PLAN_PERFORMANCE
    if trial_expired:
        # Unpaid trial ran out. The durable downgrade is done by the sweep / lazy
        # read; this read-time gate holds even before that row write lands.
        observe_only = True
        reason = "trial_expired"
    elif org.subscription_status == SUBSCRIPTION_PAST_DUE:
        # Payment failed; lock optimization until a retry reactivates. Traffic flows.
        observe_only = True
        reason = "past_due"
    elif org.subscription_status in (SUBSCRIPTION_CANCELED, SUBSCRIPTION_EXPIRED):
        observe_only = True
        reason = org.subscription_status
    elif quota_exceeded:
        observe_only = True
        reason = "monthly_request_limit_exceeded"
    elif observe_only:
        reason = "free_plan"

    return EntitlementState(
        plan_tier=plan_tier,
        observe_only=observe_only,
        reason=reason,
        monthly_requests=monthly_requests,
        monthly_request_limit=limit,
        requests_remaining=_requests_remaining(monthly_requests, limit) if limit > 0 else None,
        trial_ends_at=trial_ends_at,
        trial_expired=trial_expired,
    )


def _monthly_proxy_requests(db: Session, organization_id: uuid.UUID, now: datetime) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(UsageEvent)
            .where(
                UsageEvent.organization_id == organization_id,
                UsageEvent.source == "proxy",
                UsageEvent.received_at >= _month_start(now),
            )
        )
        or 0
    )


async def _monthly_proxy_requests_async(db: AsyncSession, organization_id: uuid.UUID, now: datetime) -> int:
    result = await db.scalar(
        select(func.count())
        .select_from(UsageEvent)
        .where(
            UsageEvent.organization_id == organization_id,
            UsageEvent.source == "proxy",
            UsageEvent.received_at >= _month_start(now),
        )
    )
    return int(result or 0)


def _entitlement_state_for_org(db: Session, org: Organization | None) -> EntitlementState:
    now = datetime.now(UTC)
    # Lazy expiry: correct an elapsed unpaid trial the next time the org is read on
    # the control plane, so the durable state is right without waiting on the sweep.
    # The async proxy hot path deliberately does not write here (it stays read-only
    # and fail-open); its state still reports observe-only via trial_expired.
    if org is not None and billing_lifecycle.maybe_expire(org, now=now):
        db.commit()
    monthly_requests = _monthly_proxy_requests(db, org.id, now) if org is not None else 0
    return _entitlement_state(monthly_requests=monthly_requests, now=now, org=org)


def entitlement_state_for_project(db: Session, project: Project) -> EntitlementState:
    org = db.get(Organization, project.organization_id)
    return _entitlement_state_for_org(db, org)


async def entitlement_state_async(db: AsyncSession, organization_id: uuid.UUID) -> EntitlementState:
    key = str(organization_id)
    with _tier_lock:
        cached = _tier_cache.get(key)
    if cached is not None:
        return cached
    try:
        now = datetime.now(UTC)
        org = await db.get(Organization, organization_id)
        monthly_requests = await _monthly_proxy_requests_async(db, organization_id, now)
        state = _entitlement_state(monthly_requests=monthly_requests, now=now, org=org)
    except Exception:
        return EntitlementState(
            plan_tier=PLAN_FREE,
            observe_only=True,
            reason="entitlement_lookup_failed",
            monthly_requests=0,
            monthly_request_limit=settings.free_monthly_request_limit,
            requests_remaining=None,
            trial_ends_at=None,
            trial_expired=False,
        )
    with _tier_lock:
        _tier_cache[key] = state
    return state


async def observe_only_async(db: AsyncSession, organization_id: uuid.UUID) -> bool:
    """Whether this org is observe-only (Free), for the async proxy hot path.

    Cached with a short TTL so it costs a dict lookup on the steady-state path.
    Fail-open: any error treats the org as observe-only (the safe default that
    never silently changes a customer's production behaviour)."""
    return (await entitlement_state_async(db, organization_id)).observe_only


def require_performance(db: Session, project: Project, *, action: str) -> None:
    """Raise 403 unless the project's org is on the Optimize plan. ``action`` is
    a short human phrase used in the error so the UI can show why it was blocked."""
    if is_performance(db, project):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": FEATURE_REQUIRES_PERFORMANCE,
            "action": action,
            "message": (
                f"{action} requires the Optimize plan. This workspace is in "
                "observe-only mode: Varsten is measuring your AI traffic but is "
                "not changing any production behaviour."
            ),
        },
    )
