"""Self-serve trial lifecycle: a new signup is a Performance trial, the trial
unlocks Performance until it ends, and an unpaid trial that elapses falls back to
Free observe-only (durably, by sweep and lazily on read) without blocking traffic.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app import billing_lifecycle
from app.models import (
    PLAN_FREE,
    PLAN_PERFORMANCE,
    SUBSCRIPTION_ACTIVE,
    SUBSCRIPTION_EXPIRED,
    SUBSCRIPTION_TRIALING,
    Organization,
    Project,
)
from tests.conftest import auth_headers


def _org(db, org_id: str) -> Organization:
    return db.get(Organization, uuid.UUID(org_id))


def _sync(client, sub="auth0|trial", email="trial@example.com"):
    return client.post("/v1/auth/sync", headers=auth_headers(sub), json={"email": email, "name": None}).json()


def _sync_with_intent(client, *, intent: str, sub="auth0|intent", email="intent@example.com"):
    return client.post(
        "/v1/auth/sync",
        headers=auth_headers(sub),
        json={"email": email, "name": None, "onboarding_intent": intent},
    ).json()


def _entitlements(client, p) -> dict:
    resp = client.get(f"/v1/entitlements?project_id={p['project_id']}", headers=auth_headers(p["token"]))
    assert resp.status_code == 200
    return resp.json()


def test_new_signup_is_performance_trialing_with_default_project(client, db_session):
    body = _sync(client)
    org_id = body["organizations"][0]["id"]
    org = _org(db_session, org_id)
    assert org.plan_tier == PLAN_PERFORMANCE
    assert org.subscription_status == SUBSCRIPTION_TRIALING
    assert org.trial_started_at is not None
    assert org.trial_ends_at is not None
    # ~14 days out (allowing for clock skew in the test run).
    assert timedelta(days=13) < (org.trial_ends_at - org.trial_started_at) < timedelta(days=15)
    projects = list(db_session.scalars(select(Project).where(Project.organization_id == org.id)))
    assert len(projects) == 1
    assert projects[0].name == "Production"


def test_new_signup_with_observe_intent_is_free_observe_only(client, db_session):
    body = _sync_with_intent(client, intent="observe", sub="auth0|observe", email="observe@example.com")
    org_id = body["organizations"][0]["id"]
    org = _org(db_session, org_id)
    assert org.plan_tier == PLAN_FREE
    assert org.subscription_status == SUBSCRIPTION_ACTIVE
    assert org.trial_started_at is None
    assert org.trial_ends_at is None
    projects = list(db_session.scalars(select(Project).where(Project.organization_id == org.id)))
    assert len(projects) == 1
    ent = _entitlements(client, {"project_id": str(projects[0].id), "token": "auth0|observe"})
    assert ent["plan_tier"] == PLAN_FREE
    assert ent["observe_only"] is True
    assert ent["features"]["enable_caching"] is False


def test_existing_free_user_with_trial_intent_starts_unused_trial(client, db_session):
    body = _sync_with_intent(client, intent="observe", sub="auth0|observe-to-trial", email="upgrade@example.com")
    org = _org(db_session, body["organizations"][0]["id"])
    assert org.plan_tier == PLAN_FREE
    assert org.trial_started_at is None

    _sync_with_intent(client, intent="trial", sub="auth0|observe-to-trial", email="upgrade@example.com")
    db_session.refresh(org)
    assert org.plan_tier == PLAN_PERFORMANCE
    assert org.subscription_status == SUBSCRIPTION_TRIALING
    assert org.trial_started_at is not None
    assert org.trial_ends_at is not None


def test_observe_intent_does_not_downgrade_existing_trial(client, db_session):
    body = _sync(client, sub="auth0|trial-stays", email="trial-stays@example.com")
    org = _org(db_session, body["organizations"][0]["id"])
    started = org.trial_started_at

    _sync_with_intent(client, intent="observe", sub="auth0|trial-stays", email="trial-stays@example.com")
    db_session.refresh(org)
    assert org.plan_tier == PLAN_PERFORMANCE
    assert org.subscription_status == SUBSCRIPTION_TRIALING
    assert org.trial_started_at == started


def test_trial_intent_does_not_restart_expired_trial(client, db_session):
    body = _sync(client, sub="auth0|expired-trial", email="expired@example.com")
    org = _org(db_session, body["organizations"][0]["id"])
    org.trial_ends_at = datetime.now(UTC) - timedelta(hours=1)
    db_session.commit()
    billing_lifecycle._invalidate(org.id)

    projects = list(db_session.scalars(select(Project).where(Project.organization_id == org.id)))
    _entitlements(client, {"project_id": str(projects[0].id), "token": "auth0|expired-trial"})
    db_session.refresh(org)
    assert org.plan_tier == PLAN_FREE
    assert org.subscription_status == SUBSCRIPTION_EXPIRED
    expired_started = org.trial_started_at

    _sync_with_intent(client, intent="trial", sub="auth0|expired-trial", email="expired@example.com")
    db_session.refresh(org)
    assert org.plan_tier == PLAN_FREE
    assert org.subscription_status == SUBSCRIPTION_EXPIRED
    assert org.trial_started_at == expired_started


def test_trialing_org_has_performance_entitlements(client, db_session, provision):
    p = provision(plan="trialing")
    body = _entitlements(client, p)
    assert body["plan_tier"] == PLAN_PERFORMANCE
    assert body["observe_only"] is False
    assert body["features"]["apply_recommendations"] is True
    assert body["features"]["enable_caching"] is True
    assert body["trial"]["trial_expired"] is False


def test_expired_unpaid_trial_falls_back_to_free_on_read(client, db_session, provision):
    p = provision(plan="trialing")
    org = _org(db_session, p["org_id"])
    org.trial_ends_at = datetime.now(UTC) - timedelta(hours=1)
    db_session.commit()
    billing_lifecycle._invalidate(org.id)

    # The entitlement read both reports observe-only AND durably downgrades the row.
    body = _entitlements(client, p)
    assert body["observe_only"] is True
    assert body["plan_tier"] == PLAN_FREE
    assert body["features"]["apply_recommendations"] is False

    db_session.refresh(org)
    assert org.plan_tier == PLAN_FREE
    assert org.subscription_status == SUBSCRIPTION_EXPIRED


def test_sweep_downgrades_unpaid_expired_trial(db_session, provision):
    p = provision(plan="trialing")
    org = _org(db_session, p["org_id"])
    org.trial_ends_at = datetime.now(UTC) - timedelta(hours=1)
    db_session.commit()

    expired = billing_lifecycle.sweep_expired_trials(db_session)
    assert org.id in expired
    db_session.refresh(org)
    assert org.plan_tier == PLAN_FREE
    assert org.subscription_status == SUBSCRIPTION_EXPIRED


def test_sweep_leaves_paid_trial_alone(db_session, provision):
    p = provision(plan="trialing")
    org = _org(db_session, p["org_id"])
    org.trial_ends_at = datetime.now(UTC) - timedelta(hours=1)
    org.stripe_subscription_id = "sub_paid_123"  # a payment method on file means "paid"
    db_session.commit()

    expired = billing_lifecycle.sweep_expired_trials(db_session)
    assert org.id not in expired
    db_session.refresh(org)
    assert org.plan_tier == PLAN_PERFORMANCE
    assert org.subscription_status == SUBSCRIPTION_TRIALING


def test_expired_org_keeps_visibility_but_locks_optimization(client, db_session, provision):
    """Requirement 7: expiry locks behaviour-changing levers but never blocks the
    metering/visibility surface."""
    p = provision(plan="trialing")
    org = _org(db_session, p["org_id"])
    org.trial_ends_at = datetime.now(UTC) - timedelta(hours=1)
    db_session.commit()
    billing_lifecycle._invalidate(org.id)

    # Visibility surface (onboarding status / metering) stays available.
    status = client.get(f"/v1/onboarding/status?project_id={p['project_id']}", headers=auth_headers(p["token"]))
    assert status.status_code == 200

    # Optimization is locked.
    ent = _entitlements(client, p)
    assert ent["observe_only"] is True
    assert ent["features"]["enable_routing"] is False
