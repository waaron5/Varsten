"""Gain-share billing: fee math (percent, floor, net>=0 guarantee), invoice
generation from verified savings only, and the operator/customer endpoints.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from app import billing
from app.core.config import settings
from app.models import Organization, UsageEvent
from app.savings import month_end, month_start
from tests.conftest import auth_headers


def _cache_saving(db, pid, oid, saved):
    """A measured cache-hit ledger event: $0 actual cost, `saved` avoided."""
    db.add(
        UsageEvent(
            project_id=pid,
            organization_id=oid,
            provider="openai",
            model="gpt-4o-mini",
            operation="chat_completion",
            request_type="chat_completion",
            feature="proxy",
            environment="production",
            input_tokens=1,
            output_tokens=1,
            total_tokens=2,
            cost_usd=Decimal("0"),
            cost_source="catalog",
            pricing_status="priced",
            currency="USD",
            status="success",
            success=True,
            event_metadata={"proxy": True, "cache": "hit", "saved_usd": str(saved)},
            received_at=datetime.now(UTC),
            occurred_at=datetime.now(UTC),
        )
    )
    db.commit()


def test_compute_fee_percent_floor_and_net_guarantee():
    # Plain percentage.
    b = billing.compute_fee(Decimal("100"), Decimal("0.20"), Decimal("0"))
    assert b.fee_usd == Decimal("20.00") and b.net_savings_usd == Decimal("80.00")
    # Floor lifts a small fee...
    b = billing.compute_fee(Decimal("40"), Decimal("0.20"), Decimal("15"))
    assert b.fee_usd == Decimal("15.00")
    # ...but the floor is capped at the savings, so net is never negative.
    b = billing.compute_fee(Decimal("5"), Decimal("0.20"), Decimal("50"))
    assert b.fee_usd == Decimal("5.00") and b.net_savings_usd == Decimal("0.00")
    # No savings, no fee.
    b = billing.compute_fee(Decimal("0"), Decimal("0.20"), Decimal("0"))
    assert b.fee_usd == Decimal("0.00") and b.net_savings_usd == Decimal("0.00")


def test_generate_invoice_from_verified_savings_only(client, db_session, provision):
    p = provision(sub="auth0|inv", email="inv@example.com")
    pid, oid = uuid.UUID(p["project_id"]), uuid.UUID(p["org_id"])
    _cache_saving(db_session, pid, oid, "100.00")  # measured, billable
    org = db_session.get(Organization, oid)

    now = datetime.now(UTC)
    invoice = billing.generate_invoice(db_session, org, month_start(now), month_end(now))
    assert invoice.verified_savings_usd == Decimal("100.00")
    assert invoice.gain_share_percent == Decimal("0.2000")  # snapshot of org default
    assert invoice.fee_usd == Decimal("20.00")
    assert invoice.net_savings_usd == Decimal("80.00")
    assert invoice.status == "draft"


def test_generate_invoice_idempotent_and_immutable_after_finalize(client, db_session, provision):
    p = provision(sub="auth0|inv2", email="inv2@example.com")
    pid, oid = uuid.UUID(p["project_id"]), uuid.UUID(p["org_id"])
    _cache_saving(db_session, pid, oid, "50.00")
    org = db_session.get(Organization, oid)
    now = datetime.now(UTC)
    start, end = month_start(now), month_end(now)

    first = billing.generate_invoice(db_session, org, start, end)
    first_id = first.id
    # Re-generating the draft updates in place (same row).
    second = billing.generate_invoice(db_session, org, start, end)
    assert second.id == first_id

    # Once finalized, regeneration leaves it untouched.
    first.status = "finalized"
    first.fee_usd = Decimal("10.00")
    db_session.commit()
    third = billing.generate_invoice(db_session, org, start, end)
    assert third.status == "finalized"
    assert third.fee_usd == Decimal("10.00")  # not recomputed


def test_admin_billing_preview_and_history(client, db_session, provision):
    p = provision(sub="auth0|inv3", email="inv3@example.com")
    pid, oid = uuid.UUID(p["project_id"]), uuid.UUID(p["org_id"])
    _cache_saving(db_session, pid, oid, "100.00")

    body = client.get(
        "/v1/admin/billing", headers=auth_headers(p["token"]), params={"project_id": p["project_id"]}
    ).json()
    assert body["pricing_model"] == "percentage_of_verified_savings_with_floor"
    assert Decimal(str(body["current_period"]["verified_savings_usd"])) == Decimal("100.00")
    assert Decimal(str(body["current_period"]["fee_usd"])) == Decimal("20.00")

    # Generate an invoice directly, then it shows in history.
    org = db_session.get(Organization, oid)
    now = datetime.now(UTC)
    billing.generate_invoice(db_session, org, month_start(now), month_end(now))
    history = client.get(
        "/v1/admin/billing/invoices", headers=auth_headers(p["token"]), params={"project_id": p["project_id"]}
    ).json()
    assert len(history) == 1
    assert Decimal(str(history[0]["fee_usd"])) == Decimal("20.00")


def test_operator_sets_billing_config(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "operator_admin_emails", ["op@example.com"])
    synced = client.post(
        "/v1/auth/sync", headers=auth_headers("auth0|op"), json={"email": "op@example.com", "name": None}
    ).json()
    org_id = synced["organizations"][0]["id"]

    resp = client.post(
        f"/v1/operator/organizations/{org_id}/billing",
        headers=auth_headers("auth0|op"),
        json={"gain_share_percent": "0.25", "monthly_fee_floor_usd": "500", "subscription_status": "trialing"},
    )
    assert resp.status_code == 200
    assert Decimal(str(resp.json()["gain_share_percent"])) == Decimal("0.2500")
    assert resp.json()["subscription_status"] == "trialing"

    # Invalid subscription status is rejected.
    bad = client.post(
        f"/v1/operator/organizations/{org_id}/billing",
        headers=auth_headers("auth0|op"),
        json={"subscription_status": "bogus"},
    )
    assert bad.status_code == 422


def test_operator_only_can_generate_invoice(client, db_session, provision, monkeypatch):
    p = provision(sub="auth0|cust", email="cust@example.com")
    # A non-operator cannot generate invoices.
    monkeypatch.setattr(settings, "operator_admin_emails", ["op@example.com"])
    denied = client.post(
        f"/v1/operator/organizations/{p['org_id']}/invoices",
        headers=auth_headers(p["token"]),
        json={},
    )
    assert denied.status_code == 403
