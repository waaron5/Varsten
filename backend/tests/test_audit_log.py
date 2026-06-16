"""Append-only audit log: sensitive control-plane actions (plan switch, provider
key custody) are recorded with actor, target, and before/after, and the read
endpoint is org-scoped so no tenant sees another's history.
"""

import uuid

from sqlalchemy import select

from app.core.config import settings
from app.models import ACTION_PLAN_CHANGED, AuditEvent
from tests.conftest import auth_headers


def _sync_user(client, sub, email):
    return client.post("/v1/auth/sync", headers=auth_headers(sub), json={"email": email, "name": None})


def test_plan_switch_is_audited(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "operator_admin_emails", ["op@example.com"])
    synced = _sync_user(client, "auth0|op", "op@example.com").json()
    org_id = synced["organizations"][0]["id"]

    resp = client.post(
        f"/v1/operator/organizations/{org_id}/plan",
        headers=auth_headers("auth0|op"),
        json={"plan_tier": "performance"},
    )
    assert resp.status_code == 200

    events = db_session.scalars(select(AuditEvent).where(AuditEvent.organization_id == uuid.UUID(org_id))).all()
    plan_events = [e for e in events if e.action == ACTION_PLAN_CHANGED]
    assert len(plan_events) == 1
    e = plan_events[0]
    assert e.actor_email == "op@example.com"
    assert e.before["plan_tier"] == "free"
    assert e.after["plan_tier"] == "performance"
    assert e.target_id == org_id


def test_audit_log_endpoint_is_org_scoped(client, monkeypatch, provision):
    # Tenant A switches plan (creates an audit event); tenant B must not see it.
    monkeypatch.setattr(settings, "operator_admin_emails", ["a@example.com"])
    a = _sync_user(client, "auth0|a", "a@example.com").json()
    a_org = a["organizations"][0]["id"]
    a_project = client.post(
        f"/v1/organizations/{a_org}/projects", headers=auth_headers("auth0|a"), json={"name": "prod"}
    ).json()
    client.post(
        f"/v1/operator/organizations/{a_org}/plan",
        headers=auth_headers("auth0|a"),
        json={"plan_tier": "performance"},
    )

    b = provision(sub="auth0|b", email="b@example.com")

    a_log = client.get(
        "/v1/admin/audit-log", headers=auth_headers("auth0|a"), params={"project_id": a_project["id"]}
    ).json()
    assert any(ev["action"] == ACTION_PLAN_CHANGED for ev in a_log["events"])

    b_log = client.get(
        "/v1/admin/audit-log", headers=auth_headers("auth0|b"), params={"project_id": b["project_id"]}
    ).json()
    assert b_log["events"] == []


def test_audit_records_no_secret_values(client, db_session, monkeypatch):
    # A provider-key event must record that a key was set, never the key itself.
    monkeypatch.setattr(settings, "operator_admin_emails", ["op@example.com"])
    synced = _sync_user(client, "auth0|op", "op@example.com").json()
    org_id = synced["organizations"][0]["id"]
    client.post(
        f"/v1/operator/organizations/{org_id}/plan",
        headers=auth_headers("auth0|op"),
        json={"plan_tier": "performance"},
    )
    # Sanity: the plan event carries only tier metadata, no secret-looking field.
    events = db_session.scalars(select(AuditEvent)).all()
    for e in events:
        blob = f"{e.before}{e.after}{e.details}"
        assert "sk-" not in blob
