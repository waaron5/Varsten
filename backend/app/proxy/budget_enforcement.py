"""Hard-cap budget enforcement on the proxy hot path.

When a request's workload owner (team / feature / customer) has a hard-cap budget
that is already exhausted this month, the proxy blocks the forward to the provider
so the cap actually stops spend. Three safety rules, in order of importance:

1. **Fail-open.** Any error resolving budget state allows the request. A bug here
   must never take down a customer's traffic.
2. **$0 is never blocked.** Cache hits are served before this check runs, so a
   cap never blocks a request that costs nothing.
3. **Opt-in + kill-switchable.** Only hard-cap budgets (a deliberate customer
   choice, Performance-only) block, the global setting can disable it, and a
   bypassed request is never blocked.

Budget state is read through a short-TTL process-local cache so the hot path does
not sum the ledger on every request (single-process, like the plan-tier cache).
"""

import threading
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from cachetools import TTLCache
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.budgets import OWNER_COLUMN
from app.core.config import settings
from app.core.logging import get_logger
from app.models import BudgetRule, UsageEvent
from app.proxy.request_context import RequestContext
from app.savings import month_start

logger = get_logger("varsten.proxy.budget")

# project_id -> frozenset[(owner_type, owner_key)] of exhausted hard caps.
_cache: TTLCache[str, frozenset[tuple[str, str]]] = TTLCache(
    maxsize=4096, ttl=max(1, settings.budget_enforcement_cache_ttl_seconds)
)
_lock = threading.Lock()


def clear_budget_cache(project_id: uuid.UUID | None = None) -> None:
    """Drop cached budget state (after a budget change, or for test isolation)."""
    with _lock:
        if project_id is None:
            _cache.clear()
        else:
            _cache.pop(str(project_id), None)


async def _compute_exhausted(db: AsyncSession, project_id: uuid.UUID, now: datetime) -> frozenset[tuple[str, str]]:
    start = month_start(now)
    rules = (
        await db.scalars(
            select(BudgetRule).where(
                BudgetRule.project_id == project_id,
                BudgetRule.enabled.is_(True),
                BudgetRule.hard_cap_enabled.is_(True),
            )
        )
    ).all()
    exhausted: set[tuple[str, str]] = set()
    for rule in rules:
        column = OWNER_COLUMN.get(rule.owner_type)
        if column is None or rule.monthly_budget_usd <= 0:
            continue
        spend = await db.scalar(
            select(func.coalesce(func.sum(UsageEvent.cost_usd), 0)).where(
                UsageEvent.project_id == project_id,
                column == rule.owner_key,
                UsageEvent.received_at >= start,
            )
        )
        if Decimal(spend or 0) >= Decimal(rule.monthly_budget_usd):
            exhausted.add((rule.owner_type, rule.owner_key))
    return frozenset(exhausted)


async def exhausted_hard_caps(db: AsyncSession, project_id: uuid.UUID) -> frozenset[tuple[str, str]]:
    """The owners whose hard cap is exhausted this month, cached. Fail-open: returns
    an empty set on any error so a lookup failure never blocks traffic."""
    if not settings.budget_enforcement_enabled:
        return frozenset()
    key = str(project_id)
    with _lock:
        cached = _cache.get(key)
    if cached is not None:
        return cached
    try:
        result = await _compute_exhausted(db, project_id, datetime.now(UTC))
    except Exception:
        logger.exception("budget enforcement lookup failed; allowing request (fail-open)")
        return frozenset()
    with _lock:
        _cache[key] = result
    return result


def matched_cap(exhausted: frozenset[tuple[str, str]], ctx: RequestContext | None) -> tuple[str, str] | None:
    """The exhausted hard cap this request hits via its workload tags, or None."""
    if not exhausted or ctx is None:
        return None
    owner_values = {"team": ctx.team, "feature": ctx.feature, "customer": ctx.customer_id}
    for owner_type, owner_key in exhausted:
        if owner_values.get(owner_type) and owner_values[owner_type] == owner_key:
            return (owner_type, owner_key)
    return None
