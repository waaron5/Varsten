"""Budget evaluation engine and the budget-status read endpoint, plus the
hot-path owner-matching used by enforcement.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from app.budgets import evaluate_budgets, period_spend
from app.models import BudgetRule, Project, UsageEvent
from app.proxy.budget_enforcement import matched_cap
from app.proxy.request_context import RequestContext
from tests.conftest import auth_headers


def _event(db, project_id, org_id, *, feature=None, team=None, customer_id=None, cost):
    db.add(
        UsageEvent(
            project_id=project_id,
            organization_id=org_id,
            provider="openai",
            model="gpt-4o-mini",
            operation="chat_completion",
            request_type="chat_completion",
            feature=feature,
            team=team,
            customer_id=customer_id,
            environment="production",
            input_tokens=1,
            output_tokens=1,
            total_tokens=2,
            cost_usd=Decimal(str(cost)),
            cost_source="catalog",
            pricing_status="priced",
            currency="USD",
            status="success",
            success=True,
            event_metadata={},
            received_at=datetime.now(UTC),
            occurred_at=datetime.now(UTC),
        )
    )
    db.commit()


def test_matched_cap_matches_request_owner():
    exhausted = frozenset({("feature", "support")})
    assert matched_cap(exhausted, RequestContext(feature="support")) == ("feature", "support")
    assert matched_cap(exhausted, RequestContext(feature="billing")) is None
    assert matched_cap(exhausted, RequestContext(team="support")) is None  # wrong dimension
    assert matched_cap(frozenset(), RequestContext(feature="support")) is None
    assert matched_cap(exhausted, None) is None


def test_evaluate_budgets_reports_spend_and_exhaustion(client, db_session, provision):
    p = provision(sub="auth0|bud", email="bud@example.com")
    pid, oid = uuid.UUID(p["project_id"]), uuid.UUID(p["org_id"])
    db_session.add(
        BudgetRule(
            organization_id=oid,
            project_id=pid,
            owner_type="feature",
            owner_key="support",
            monthly_budget_usd=Decimal("10.00"),
            hard_cap_enabled=True,
            enabled=True,
        )
    )
    db_session.commit()
    _event(db_session, pid, oid, feature="support", cost="12.00")

    statuses = evaluate_budgets(db_session, db_session.get(Project, pid))
    assert len(statuses) == 1
    s = statuses[0]
    assert s.spend_usd == Decimal("12.00")
    assert s.percent_used == Decimal("120.0")
    assert s.over_budget is True
    assert s.hard_cap_exhausted is True


def test_period_spend_is_owner_scoped(client, db_session, provision):
    p = provision(sub="auth0|sp", email="sp@example.com")
    pid, oid = uuid.UUID(p["project_id"]), uuid.UUID(p["org_id"])
    _event(db_session, pid, oid, feature="support", cost="3.00")
    _event(db_session, pid, oid, feature="billing", cost="9.00")
    start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    assert period_spend(db_session, pid, "feature", "support", start) == Decimal("3.00")
    assert period_spend(db_session, pid, "feature", "billing", start) == Decimal("9.00")


def test_budget_status_endpoint(client, db_session, provision):
    p = provision(sub="auth0|bs", email="bs@example.com")
    pid, oid = uuid.UUID(p["project_id"]), uuid.UUID(p["org_id"])
    db_session.add(
        BudgetRule(
            organization_id=oid,
            project_id=pid,
            owner_type="team",
            owner_key="cx",
            monthly_budget_usd=Decimal("100.00"),
            hard_cap_enabled=True,
            enabled=True,
        )
    )
    db_session.commit()
    _event(db_session, pid, oid, team="cx", cost="150.00")

    body = client.get(
        "/v1/guardrails/budgets/status",
        headers=auth_headers(p["token"]),
        params={"project_id": p["project_id"]},
    ).json()
    assert len(body) == 1
    assert body[0]["owner_key"] == "cx"
    assert Decimal(str(body[0]["spend_usd"])) == Decimal("150.00")
    assert body[0]["hard_cap_blocking"] is True
