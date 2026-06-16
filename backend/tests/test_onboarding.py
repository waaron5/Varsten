"""Self-serve onboarding status: derived setup state + first-request detection."""

import uuid

from app.models import UsageEvent
from tests.conftest import auth_headers


def _status(client, p) -> dict:
    resp = client.get(
        f"/v1/onboarding/status?project_id={p['project_id']}",
        headers=auth_headers(p["token"]),
    )
    assert resp.status_code == 200
    return resp.json()


def _add_event(db_session, p, **extra) -> None:
    defaults = {
        "project_id": uuid.UUID(p["project_id"]),
        "organization_id": uuid.UUID(p["org_id"]),
        "provider": "openai",
        "model": "gpt-4o-mini",
        "operation": "chat_completion",
        "environment": "production",
        "input_tokens": 10,
        "output_tokens": 2,
        "total_tokens": 12,
        "cost_source": "catalog",
        "pricing_status": "priced",
        "latency_ms": 120,
    }
    defaults.update(extra)
    db_session.add(UsageEvent(**defaults))
    db_session.flush()


def test_status_fresh_workspace_is_observe_only(client, provision, db_session):
    p = provision()
    s = _status(client, p)
    assert s["plan_tier"] == "free"
    assert s["observe_only"] is True
    assert s["has_project"] is True
    assert s["has_api_key"] is True  # provision creates one
    assert s["has_provider_connection"] is False
    assert s["first_request"]["seen"] is False
    assert s["first_request"]["request_count"] == 0
    assert s["onboarding_completed_at"] is None


def test_status_detects_first_request(client, provision, db_session):
    p = provision()
    _add_event(
        db_session,
        p,
        feature="support_reply",
        workflow="billing",
        event_metadata={"task_type": "support_reply.billing"},
    )
    s = _status(client, p)
    fr = s["first_request"]
    assert fr["seen"] is True
    assert fr["request_count"] == 1
    assert fr["provider"] == "openai"
    assert fr["model"] == "gpt-4o-mini"
    assert fr["latency_ms"] == 120
    assert fr["feature"] == "support_reply"
    assert fr["task_type"] == "support_reply.billing"
    assert fr["metadata_quality"]["level"] == "great"


def test_metadata_quality_nudges_when_sparse(client, provision, db_session):
    p = provision()
    _add_event(db_session, p)  # no feature/workflow/task_type
    s = _status(client, p)
    assert s["first_request"]["metadata_quality"]["level"] == "none"


def test_complete_sets_timestamp(client, provision, db_session):
    p = provision()
    resp = client.post(
        f"/v1/onboarding/complete?project_id={p['project_id']}",
        headers=auth_headers(p["token"]),
    )
    assert resp.status_code == 200
    assert resp.json()["onboarding_completed_at"] is not None
    assert _status(client, p)["onboarding_completed_at"] is not None


def test_status_tenant_isolation(client, provision, db_session):
    a = provision(sub="auth0|a", email="a@example.com", project_name="a")
    b = provision(sub="auth0|b", email="b@example.com", project_name="b")
    _add_event(db_session, a)
    # B's status must not see A's traffic.
    assert _status(client, b)["first_request"]["seen"] is False
    assert _status(client, a)["first_request"]["seen"] is True
