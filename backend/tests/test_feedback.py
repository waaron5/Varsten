"""Production outcome feedback ingestion (POST /v1/feedback)."""

import uuid

from sqlalchemy import select

from app.models import RequestDecisionEvent, RequestFeedback, UsageEvent


def _make_usage_event(db_session, project_id: str) -> uuid.UUID:
    event = UsageEvent(
        project_id=uuid.UUID(project_id),
        organization_id=_org_for(db_session, project_id),
        provider="openai",
        model="gpt-4o-mini",
        operation="chat_completion",
        environment="production",
        input_tokens=10,
        output_tokens=2,
        total_tokens=12,
        cost_source="catalog",
        pricing_status="priced",
    )
    db_session.add(event)
    db_session.flush()
    return event.id


def _org_for(db_session, project_id: str) -> uuid.UUID:
    from app.models import Project

    return db_session.get(Project, uuid.UUID(project_id)).organization_id


def _auth(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}"}


def test_feedback_by_usage_event_id(client, provision, db_session):
    p = provision()
    event_id = _make_usage_event(db_session, p["project_id"])

    resp = client.post(
        "/v1/feedback",
        headers=_auth(p["api_key"]),
        json={"usage_event_id": str(event_id), "outcome": "accepted", "quality_score": 0.9},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["outcome"] == "accepted"
    assert body["usage_event_id"] == str(event_id)

    stored = db_session.scalar(select(RequestFeedback).where(RequestFeedback.usage_event_id == event_id))
    assert stored is not None
    assert stored.project_id == uuid.UUID(p["project_id"])
    assert stored.source == "customer"


def test_feedback_by_request_id_links_decision(client, provision, db_session):
    p = provision()
    event_id = _make_usage_event(db_session, p["project_id"])
    decision = RequestDecisionEvent(
        organization_id=_org_for(db_session, p["project_id"]),
        project_id=uuid.UUID(p["project_id"]),
        usage_event_id=event_id,
        request_id="req_abc",
        provider_requested="openai",
        model_requested="gpt-4o-mini",
        decision_type="passthrough",
    )
    db_session.add(decision)
    db_session.flush()

    resp = client.post(
        "/v1/feedback",
        headers=_auth(p["api_key"]),
        json={"request_id": "req_abc", "outcome": "edited"},
    )
    assert resp.status_code == 201
    stored = db_session.scalar(select(RequestFeedback).where(RequestFeedback.request_id == "req_abc"))
    assert stored.decision_event_id == decision.id
    # usage_event link is backfilled from the decision.
    assert stored.usage_event_id == event_id


def test_feedback_rejects_unknown_outcome(client, provision, db_session):
    p = provision()
    resp = client.post(
        "/v1/feedback",
        headers=_auth(p["api_key"]),
        json={"request_id": "req_x", "outcome": "loved_it"},
    )
    assert resp.status_code == 422


def test_feedback_requires_a_link(client, provision, db_session):
    p = provision()
    resp = client.post("/v1/feedback", headers=_auth(p["api_key"]), json={"outcome": "accepted"})
    assert resp.status_code == 422


def test_feedback_tenant_isolation(client, provision, db_session):
    a = provision(sub="auth0|a", email="a@example.com", project_name="a")
    b = provision(sub="auth0|b", email="b@example.com", project_name="b")
    # An event in project A.
    event_id = _make_usage_event(db_session, a["project_id"])

    # Project B's key may not attach feedback to project A's event.
    resp = client.post(
        "/v1/feedback",
        headers=_auth(b["api_key"]),
        json={"usage_event_id": str(event_id), "outcome": "accepted"},
    )
    assert resp.status_code == 404
