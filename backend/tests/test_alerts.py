"""Alert evaluation, delivery, dedup, and the delivery-history record/endpoint.

Delivery is recorded for every crossing (status skipped when no channel is
configured, failed when a send raises, sent on success), once per period.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from app import alerts as alerts_mod
from app.alerts import evaluate_and_deliver
from app.core.config import settings
from app.models import DELIVERY_FAILED, DELIVERY_SKIPPED, AlertDelivery, AlertRule, BudgetRule, Project, UsageEvent
from tests.conftest import auth_headers


def _event(db, pid, oid, *, feature=None, cost):
    db.add(
        UsageEvent(
            project_id=pid,
            organization_id=oid,
            provider="openai",
            model="gpt-4o-mini",
            operation="chat_completion",
            request_type="chat_completion",
            feature=feature,
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


def _ids(provision, sub, email):
    p = provision(sub=sub, email=email)
    return p, uuid.UUID(p["project_id"]), uuid.UUID(p["org_id"])


def test_spend_threshold_alert_records_and_dedupes(client, db_session, provision, monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", "")  # no channel -> recorded as skipped
    _, pid, oid = _ids(provision, "auth0|spend", "spend@example.com")
    db_session.add(
        AlertRule(
            organization_id=oid,
            project_id=pid,
            alert_type="spend",
            threshold_usd=Decimal("50.00"),
            destination_type="email",
            destination="ops@example.com",
            enabled=True,
        )
    )
    db_session.commit()
    _event(db_session, pid, oid, cost="75.00")

    project = db_session.get(Project, pid)
    delivered = evaluate_and_deliver(db_session, project)
    assert len(delivered) == 1
    assert delivered[0].status == DELIVERY_SKIPPED
    assert delivered[0].observed_usd == Decimal("75.00")

    # Same crossing does not re-fire this period.
    assert evaluate_and_deliver(db_session, project) == []
    rows = db_session.scalars(select_deliveries(pid)).all()
    assert len(rows) == 1


def test_budget_percent_alert_owner_tagged(client, db_session, provision, monkeypatch):
    monkeypatch.setattr(settings, "slack_alerts_enabled", False)  # recorded as skipped
    _, pid, oid = _ids(provision, "auth0|pct", "pct@example.com")
    db_session.add(
        BudgetRule(
            organization_id=oid,
            project_id=pid,
            owner_type="feature",
            owner_key="support",
            monthly_budget_usd=Decimal("100.00"),
            hard_cap_enabled=False,
            enabled=True,
        )
    )
    db_session.add(
        AlertRule(
            organization_id=oid,
            project_id=pid,
            alert_type="budget",
            threshold_percent=Decimal("80"),
            destination_type="slack",
            destination="https://hooks.slack.test/x",
            enabled=True,
        )
    )
    db_session.commit()
    _event(db_session, pid, oid, feature="support", cost="90.00")  # 90% of 100

    delivered = evaluate_and_deliver(db_session, db_session.get(Project, pid))
    assert len(delivered) == 1
    assert delivered[0].owner_type == "feature"
    assert delivered[0].owner_key == "support"
    assert delivered[0].status == DELIVERY_SKIPPED


def test_failed_delivery_is_recorded(client, db_session, provision, monkeypatch):
    # Slack enabled but the HTTP post raises -> recorded as failed with the error.
    monkeypatch.setattr(settings, "slack_alerts_enabled", True)

    def boom(*args, **kwargs):
        raise RuntimeError("webhook down")

    monkeypatch.setattr(alerts_mod.httpx, "post", boom)
    _, pid, oid = _ids(provision, "auth0|fail", "fail@example.com")
    db_session.add(
        AlertRule(
            organization_id=oid,
            project_id=pid,
            alert_type="spend",
            threshold_usd=Decimal("10.00"),
            destination_type="slack",
            destination="https://hooks.slack.test/x",
            enabled=True,
        )
    )
    db_session.commit()
    _event(db_session, pid, oid, cost="20.00")

    delivered = evaluate_and_deliver(db_session, db_session.get(Project, pid))
    assert len(delivered) == 1
    assert delivered[0].status == DELIVERY_FAILED
    assert "webhook down" in delivered[0].error


def test_alert_history_endpoint(client, db_session, provision, monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", "")
    p, pid, oid = _ids(provision, "auth0|hist", "hist@example.com")
    db_session.add(
        AlertRule(
            organization_id=oid,
            project_id=pid,
            alert_type="spend",
            threshold_usd=Decimal("5.00"),
            destination_type="email",
            destination="ops@example.com",
            enabled=True,
        )
    )
    db_session.commit()
    _event(db_session, pid, oid, cost="9.00")
    evaluate_and_deliver(db_session, db_session.get(Project, pid))

    body = client.get(
        "/v1/guardrails/alerts/history",
        headers=auth_headers(p["token"]),
        params={"project_id": p["project_id"]},
    ).json()
    assert len(body) == 1
    assert body[0]["alert_type"] == "spend"
    assert body[0]["status"] == DELIVERY_SKIPPED


def select_deliveries(pid):
    from sqlalchemy import select

    return select(AlertDelivery).where(AlertDelivery.project_id == pid)
