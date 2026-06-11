from datetime import UTC, datetime
from decimal import Decimal

from app.core.config import settings
from app.models import UsageEvent


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _sync(client, sub: str, email: str):
    return client.post("/v1/auth/sync", headers=auth_headers(sub), json={"email": email, "name": None})


def _provision_payload(**overrides):
    payload = {
        "customer_email": "buyer@example.com",
        "full_name": "Buyer Person",
        "company_name": "Acme",
        "organization_name": "Acme",
        "project_name": "Production",
        "api_key_name": "Production ingestion",
    }
    payload.update(overrides)
    return payload


def test_operator_provision_rejects_non_operator(client, monkeypatch):
    monkeypatch.setattr(settings, "operator_admin_emails", ["operator@example.com"])
    _sync(client, "auth0|member", "member@example.com")

    res = client.post(
        "/v1/operator/provision",
        headers=auth_headers("auth0|member"),
        json=_provision_payload(),
    )

    assert res.status_code == 403


def test_operator_can_provision_customer_org_project_and_one_time_key(client, monkeypatch):
    monkeypatch.setattr(settings, "operator_admin_emails", ["operator@example.com"])
    _sync(client, "auth0|operator", "operator@example.com")

    res = client.post(
        "/v1/operator/provision",
        headers=auth_headers("auth0|operator"),
        json=_provision_payload(),
    )

    assert res.status_code == 201
    body = res.json()
    assert body["organization_id"]
    assert body["project_id"]
    assert body["api_key_prefix"]
    assert body["plaintext_api_key"].startswith("vk_")


def test_preprovisioned_customer_login_attaches_existing_user_and_org(client, monkeypatch):
    monkeypatch.setattr(settings, "operator_admin_emails", ["operator@example.com"])
    _sync(client, "auth0|operator", "operator@example.com")
    provisioned = client.post(
        "/v1/operator/provision",
        headers=auth_headers("auth0|operator"),
        json=_provision_payload(customer_email="buyer@example.com"),
    ).json()

    synced = _sync(client, "auth0|buyer", "buyer@example.com")

    assert synced.status_code == 200
    org_ids = {org["id"] for org in synced.json()["organizations"]}
    assert provisioned["organization_id"] in org_ids


def test_operator_validation_summary_returns_metrics_and_draft(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "operator_admin_emails", ["operator@example.com"])
    _sync(client, "auth0|operator", "operator@example.com")
    provisioned = client.post(
        "/v1/operator/provision",
        headers=auth_headers("auth0|operator"),
        json=_provision_payload(),
    ).json()

    event = UsageEvent(
        project_id=provisioned["project_id"],
        organization_id=provisioned["organization_id"],
        provider="openai",
        model="gpt-4o-mini",
        operation="chat.completions",
        input_tokens=100,
        output_tokens=50,
        total_tokens=150,
        cost_usd=Decimal("0.001"),
        cost_source="catalog",
        pricing_status="priced",
        latency_ms=12,
        event_metadata={"saved_usd": "0.0025"},
        received_at=datetime.now(UTC),
    )
    db_session.add(event)
    db_session.commit()

    res = client.get(
        f"/v1/operator/projects/{provisioned['project_id']}/validation-summary",
        headers=auth_headers("auth0|operator"),
    )

    assert res.status_code == 200
    body = res.json()
    assert body["request_count"] == 1
    assert body["p95_latency_ms"] == 12
    assert body["saved_usd"] == "0.0025"
    assert "You successfully routed 1 requests" in body["follow_up_draft"]


def test_operator_validation_summary_handles_empty_traffic(client, monkeypatch):
    monkeypatch.setattr(settings, "operator_admin_emails", ["operator@example.com"])
    _sync(client, "auth0|operator", "operator@example.com")
    provisioned = client.post(
        "/v1/operator/provision",
        headers=auth_headers("auth0|operator"),
        json=_provision_payload(),
    ).json()

    res = client.get(
        f"/v1/operator/projects/{provisioned['project_id']}/validation-summary",
        headers=auth_headers("auth0|operator"),
    )

    assert res.status_code == 200
    body = res.json()
    assert body["request_count"] == 0
    assert "not seeing routed traffic" in body["follow_up_draft"]
