"""Plan-tier entitlements and observe-only enforcement.

Free is observe-only: Varsten meters, prices, records decision evidence, and
recommends, but may never activate a behaviour-changing lever. Performance
unlocks the savings levers. This is the single backend chokepoint that keeps a
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

from cachetools import TTLCache
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models import PLAN_FREE, PLAN_PERFORMANCE, Organization, Project

FEATURE_REQUIRES_PERFORMANCE = "feature_requires_performance"

# Process-local plan-tier cache so the proxy hot path can decide observe-only
# without a DB read every request. Short TTL plus explicit invalidation on a plan
# change keeps it from going stale. Single-process (mirrors the provider-key cache).
_TIER_TTL_SECONDS = 60
_tier_cache: TTLCache[str, str] = TTLCache(maxsize=8192, ttl=_TIER_TTL_SECONDS)
_tier_lock = threading.Lock()


def invalidate_plan_tier(organization_id: uuid.UUID | None = None) -> None:
    """Drop a cached tier (or all) after a plan change so it takes effect at once."""
    with _tier_lock:
        if organization_id is None:
            _tier_cache.clear()
        else:
            _tier_cache.pop(str(organization_id), None)


def plan_tier_for_project(db: Session, project: Project) -> str:
    org = db.get(Organization, project.organization_id)
    return org.plan_tier if org is not None else PLAN_FREE


def is_performance(db: Session, project: Project) -> bool:
    return plan_tier_for_project(db, project) == PLAN_PERFORMANCE


def is_performance_org(db: Session, organization_id: uuid.UUID) -> bool:
    org = db.get(Organization, organization_id)
    return org is not None and org.plan_tier == PLAN_PERFORMANCE


async def observe_only_async(db: AsyncSession, organization_id: uuid.UUID) -> bool:
    """Whether this org is observe-only (Free), for the async proxy hot path.

    Cached with a short TTL so it costs a dict lookup on the steady-state path.
    Fail-open: any error treats the org as observe-only (the safe default that
    never silently changes a customer's production behaviour)."""
    key = str(organization_id)
    with _tier_lock:
        cached = _tier_cache.get(key)
    if cached is not None:
        return cached != PLAN_PERFORMANCE
    try:
        org = await db.get(Organization, organization_id)
        tier = org.plan_tier if org is not None else PLAN_FREE
    except Exception:
        return True
    with _tier_lock:
        _tier_cache[key] = tier
    return tier != PLAN_PERFORMANCE


def require_performance(db: Session, project: Project, *, action: str) -> None:
    """Raise 403 unless the project's org is on the Performance plan. ``action`` is
    a short human phrase used in the error so the UI can show why it was blocked."""
    if is_performance(db, project):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": FEATURE_REQUIRES_PERFORMANCE,
            "action": action,
            "message": (
                f"{action} requires the Performance plan. This workspace is in "
                "observe-only mode: Varsten is measuring your AI traffic but is "
                "not changing any production behaviour."
            ),
        },
    )
