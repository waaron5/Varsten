"""Budget evaluation: current-period spend per budget owner, against the cap.

Shared by three callers:
- the guardrails read endpoint (so a budget shows real spend vs its cap),
- the alert sweep (which fires notifications on threshold crossings),
- hard-cap enforcement in the proxy (see app/proxy/budget_enforcement.py, which
  re-implements the spend query on the async session for the hot path).

A budget owner is a workload dimension a request is tagged with: a team, a
feature, or a customer. Spend is summed from the authoritative ledger for the
current month, so the number a budget shows is the same number Proof shows.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import BudgetRule, Project, UsageEvent
from app.savings import month_start

# Budget owner_type -> the ledger column a request carries it on.
OWNER_COLUMN = {
    "team": UsageEvent.team,
    "feature": UsageEvent.feature,
    "customer": UsageEvent.customer_id,
}


@dataclass(frozen=True)
class BudgetStatus:
    rule_id: object
    owner_type: str
    owner_key: str
    budget_usd: Decimal
    spend_usd: Decimal
    hard_cap_enabled: bool

    @property
    def percent_used(self) -> Decimal | None:
        if self.budget_usd <= 0:
            return None
        return (self.spend_usd / self.budget_usd * Decimal("100")).quantize(Decimal("0.1"))

    @property
    def over_budget(self) -> bool:
        return self.budget_usd > 0 and self.spend_usd >= self.budget_usd

    @property
    def hard_cap_exhausted(self) -> bool:
        return self.hard_cap_enabled and self.over_budget


def period_spend(db: Session, project_id, owner_type: str, owner_key: str, start: datetime) -> Decimal:
    """Month-to-date spend attributed to one budget owner, from the ledger."""
    column = OWNER_COLUMN.get(owner_type)
    if column is None:
        return Decimal("0")
    total = db.scalar(
        select(func.coalesce(func.sum(UsageEvent.cost_usd), 0)).where(
            UsageEvent.project_id == project_id,
            column == owner_key,
            UsageEvent.received_at >= start,
        )
    )
    return Decimal(total or 0)


def evaluate_budgets(db: Session, project: Project, now: datetime | None = None) -> list[BudgetStatus]:
    """Status of every enabled budget for the project this month."""
    from datetime import UTC

    now = now or datetime.now(UTC)
    start = month_start(now)
    rules = db.scalars(
        select(BudgetRule).where(BudgetRule.project_id == project.id, BudgetRule.enabled.is_(True))
    ).all()
    return [
        BudgetStatus(
            rule_id=rule.id,
            owner_type=rule.owner_type,
            owner_key=rule.owner_key,
            budget_usd=Decimal(rule.monthly_budget_usd),
            spend_usd=period_spend(db, project.id, rule.owner_type, rule.owner_key, start),
            hard_cap_enabled=rule.hard_cap_enabled,
        )
        for rule in rules
    ]
