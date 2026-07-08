"""Stripe self-serve upgrade: a signature-verified webhook records payment readiness;
forged events are rejected; the handler is idempotent; checkout/portal endpoints
are gated behind the self-serve billing flag and org membership.
"""

import hashlib
import hmac
import json
import time
import uuid

import pytest

from app import stripe_billing
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
from tests.conftest import auth_headers

WEBHOOK_SECRET = "whsec_test_secret"


@pytest.fixture
def billing_on(monkeypatch):
    monkeypatch.setattr(settings, "self_serve_billing_enabled", True)
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_x")
    monkeypatch.setattr(settings, "stripe_webhook_secret", WEBHOOK_SECRET)


def _org(db, org_id: str) -> Organization:
    return db.get(Organization, uuid.UUID(org_id))


_OBJECT_TYPE = {
    "checkout.session.completed": "checkout.session",
    "customer.subscription.deleted": "subscription",
    "invoice.payment_failed": "invoice",
}


def _event(event_type: str, customer: str, **obj) -> dict:
    # Real Stripe resources carry an "object" type discriminator; the SDK's event
    # parser uses it to pick the resource class, so the fixtures include it.
    resource = {"object": _OBJECT_TYPE.get(event_type, "event"), "customer": customer, **obj}
    return {
        "id": f"evt_{uuid.uuid4().hex}",
        "object": "event",
        "type": event_type,
        "data": {"object": resource},
    }


def _signed_headers(payload: bytes, secret: str = WEBHOOK_SECRET) -> dict:
    ts = int(time.time())
    signature = hmac.new(secret.encode(), f"{ts}.{payload.decode()}".encode(), hashlib.sha256).hexdigest()
    return {"stripe-signature": f"t={ts},v1={signature}"}


# --- handler (pure transition) ------------------------------------------------


def test_checkout_completed_during_trial_records_payment_readiness(db_session, provision):
    p = provision(plan="trialing")
    org = _org(db_session, p["org_id"])
    org.stripe_customer_id = "cus_activate"
    db_session.commit()

    handled = stripe_billing.handle_event(db_session, _event("checkout.session.completed", "cus_activate"))
    assert handled is True
    db_session.refresh(org)
    assert org.plan_tier == PLAN_PERFORMANCE
    assert org.subscription_status == SUBSCRIPTION_TRIALING
    assert org.payment_method_ready_at is not None


def test_handler_is_idempotent(db_session, provision):
    p = provision(plan="trialing")
    org = _org(db_session, p["org_id"])
    org.stripe_customer_id = "cus_idem"
    db_session.commit()
    evt = _event("checkout.session.completed", "cus_idem")
    assert stripe_billing.handle_event(db_session, evt) is True
    assert stripe_billing.handle_event(db_session, evt) is True
    db_session.refresh(org)
    assert org.subscription_status == SUBSCRIPTION_TRIALING
    assert org.payment_method_ready_at is not None


def test_checkout_completed_reactivates_expired_org(db_session, provision):
    p = provision()
    org = _org(db_session, p["org_id"])
    org.stripe_customer_id = "cus_reactivate"
    org.plan_tier = PLAN_FREE
    org.subscription_status = SUBSCRIPTION_EXPIRED
    db_session.commit()

    assert stripe_billing.handle_event(db_session, _event("checkout.session.completed", "cus_reactivate")) is True
    db_session.refresh(org)
    assert org.plan_tier == PLAN_PERFORMANCE
    assert org.subscription_status == SUBSCRIPTION_ACTIVE
    assert org.payment_method_ready_at is not None


def test_subscription_deleted_downgrades(db_session, provision):
    p = provision(plan="performance")
    org = _org(db_session, p["org_id"])
    org.stripe_customer_id = "cus_cancel"
    db_session.commit()
    assert stripe_billing.handle_event(db_session, _event("customer.subscription.deleted", "cus_cancel")) is True
    db_session.refresh(org)
    assert org.subscription_status == SUBSCRIPTION_CANCELED


def test_payment_failed_marks_past_due(db_session, provision):
    p = provision(plan="performance")
    org = _org(db_session, p["org_id"])
    org.stripe_customer_id = "cus_pastdue"
    db_session.commit()
    assert stripe_billing.handle_event(db_session, _event("invoice.payment_failed", "cus_pastdue")) is True
    db_session.refresh(org)
    assert org.subscription_status == SUBSCRIPTION_PAST_DUE


def test_unknown_customer_is_ignored(db_session):
    assert stripe_billing.handle_event(db_session, _event("checkout.session.completed", "cus_nobody")) is False


# --- webhook endpoint (signature verification) --------------------------------


def test_webhook_404_when_billing_disabled(client):
    resp = client.post("/webhooks/stripe", content=b"{}", headers={"stripe-signature": "x"})
    assert resp.status_code == 404


def test_webhook_marks_payment_ready_with_valid_signature(client, db_session, provision, billing_on):
    p = provision(plan="trialing")
    org = _org(db_session, p["org_id"])
    org.stripe_customer_id = "cus_webhook"
    db_session.commit()

    payload = json.dumps(_event("checkout.session.completed", "cus_webhook")).encode()
    resp = client.post("/webhooks/stripe", content=payload, headers=_signed_headers(payload))
    assert resp.status_code == 200
    assert resp.json()["handled"] is True
    db_session.refresh(org)
    assert org.subscription_status == SUBSCRIPTION_TRIALING
    assert org.payment_method_ready_at is not None


def test_webhook_rejects_bad_signature(client, db_session, provision, billing_on):
    p = provision(plan="trialing")
    org = _org(db_session, p["org_id"])
    org.stripe_customer_id = "cus_bad"
    db_session.commit()

    payload = json.dumps(_event("checkout.session.completed", "cus_bad")).encode()
    resp = client.post("/webhooks/stripe", content=payload, headers={"stripe-signature": "t=1,v1=deadbeef"})
    assert resp.status_code == 400
    db_session.refresh(org)
    assert org.subscription_status == SUBSCRIPTION_TRIALING  # unchanged


# --- checkout endpoint gating -------------------------------------------------


def test_checkout_endpoint_503_when_disabled(client, provision):
    p = provision()
    resp = client.post(
        f"/v1/organizations/{p['org_id']}/billing/checkout-session",
        headers=auth_headers(p["token"]),
    )
    assert resp.status_code == 503


def test_checkout_endpoint_returns_url(client, db_session, provision, billing_on, monkeypatch):
    p = provision(plan="trialing")
    monkeypatch.setattr(stripe_billing.stripe.Customer, "create", lambda **kw: {"id": "cus_new"})
    monkeypatch.setattr(
        stripe_billing.stripe.checkout.Session, "create", lambda **kw: {"url": "https://checkout.stripe/x"}
    )
    resp = client.post(
        f"/v1/organizations/{p['org_id']}/billing/checkout-session",
        headers=auth_headers(p["token"]),
    )
    assert resp.status_code == 200
    assert resp.json()["url"] == "https://checkout.stripe/x"
    org = _org(db_session, p["org_id"])
    db_session.refresh(org)
    assert org.stripe_customer_id == "cus_new"


def test_checkout_endpoint_requires_membership(client, provision, billing_on):
    p = provision(sub="auth0|owner", email="owner@example.com")
    other = provision(sub="auth0|intruder", email="intruder@example.com")
    resp = client.post(
        f"/v1/organizations/{p['org_id']}/billing/checkout-session",
        headers=auth_headers(other["token"]),
    )
    assert resp.status_code == 403
