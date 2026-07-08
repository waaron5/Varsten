"""Self-serve onboarding status: derived setup state + first-request detection."""

import uuid
from datetime import UTC, datetime

from app.models import ProviderConnection, UsageEvent
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
    assert s["selected_path"] == "base_url"
    assert s["selection_saved"] is False
    assert s["can_complete"] is False
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


def _select(client, p, path="sdk", provider="openai") -> dict:
    resp = client.post(
        f"/v1/onboarding/selection?project_id={p['project_id']}",
        headers=auth_headers(p["token"]),
        json={"path": path, "provider": provider},
    )
    assert resp.status_code == 200
    return resp.json()


def _snippet_viewed(client, p) -> None:
    resp = client.post(
        f"/v1/onboarding/event?project_id={p['project_id']}",
        headers=auth_headers(p["token"]),
        json={"event": "snippet_viewed"},
    )
    assert resp.status_code == 200


def _connect_provider(db_session, p, provider="openai") -> None:
    now = datetime.now(UTC)
    db_session.add(
        ProviderConnection(
            organization_id=uuid.UUID(p["org_id"]),
            project_id=uuid.UUID(p["project_id"]),
            provider=provider,
            connection_method="secrets_manager",
            status="connected",
            secret_ref=f"test/{p['project_id']}/{provider}",
            last_sync_at=now,
            last_verified_at=now,
        )
    )
    db_session.flush()


def test_complete_sets_timestamp_after_verified_metadata_ingest(client, provision, db_session):
    p = provision()
    _select(client, p, path="metadata", provider=None)
    _add_event(db_session, p, source="ingest")
    resp = client.post(
        f"/v1/onboarding/complete?project_id={p['project_id']}",
        headers=auth_headers(p["token"]),
    )
    assert resp.status_code == 200
    assert resp.json()["onboarding_completed_at"] is not None
    assert _status(client, p)["onboarding_completed_at"] is not None


def test_complete_rejects_until_selected_setup_is_verified(client, provision, db_session):
    p = provision()
    _select(client, p, path="sdk", provider="openai")
    resp = client.post(
        f"/v1/onboarding/complete?project_id={p['project_id']}",
        headers=auth_headers(p["token"]),
    )
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["code"] == "onboarding_incomplete"
    missing = {step["key"] for step in detail["missing_steps"]}
    assert {"has_provider_connection", "first_request"} <= missing
    assert "integration_snippet_viewed" not in missing


def test_delayed_first_request_ingestion_controls_completion(client, provision, db_session):
    p = provision()
    _select(client, p, path="base_url", provider="openai")
    _connect_provider(db_session, p)

    before = client.post(
        f"/v1/onboarding/complete?project_id={p['project_id']}",
        headers=auth_headers(p["token"]),
    )
    assert before.status_code == 409
    assert _status(client, p)["verification_status"] == "waiting"

    _add_event(db_session, p, source="proxy")
    after = client.post(
        f"/v1/onboarding/complete?project_id={p['project_id']}",
        headers=auth_headers(p["token"]),
    )
    assert after.status_code == 200
    assert _status(client, p)["verification_status"] == "verified"


def test_sdk_completion_requires_sdk_marked_selected_provider_traffic(client, provision, db_session):
    p = provision()
    _select(client, p, path="sdk", provider="openai")
    _connect_provider(db_session, p)
    _add_event(db_session, p, source="proxy", event_metadata={"sdk_client": "@varsten/openai@0.1.0"})
    s = _status(client, p)
    assert s["verified_method"] == "sdk"
    assert s["verification_status"] == "verified"
    assert s["can_complete"] is True


def test_sdk_selection_rejects_base_url_only_traffic(client, provision, db_session):
    p = provision()
    _select(client, p, path="sdk", provider="openai")
    _connect_provider(db_session, p)
    _snippet_viewed(client, p)
    _add_event(db_session, p, source="proxy")
    s = _status(client, p)
    assert s["verified_method"] == "base_url"
    assert s["verification_status"] == "path_mismatch"
    assert s["can_complete"] is False
    resp = client.post(
        f"/v1/onboarding/complete?project_id={p['project_id']}",
        headers=auth_headers(p["token"]),
    )
    assert resp.status_code == 409


def test_metadata_checklist_skips_provider_connection(client, provision, db_session):
    p = provision()
    _select(client, p, path="metadata", provider=None)
    s = _status(client, p)
    checklist = _checklist(s)
    assert "has_provider_connection" not in checklist
    assert s["selected_provider"] is None
    assert {step["key"] for step in s["missing_steps"]} == {"first_request"}


def test_status_tenant_isolation(client, provision, db_session):
    a = provision(sub="auth0|a", email="a@example.com", project_name="a")
    b = provision(sub="auth0|b", email="b@example.com", project_name="b")
    _add_event(db_session, a)
    # B's status must not see A's traffic.
    assert _status(client, b)["first_request"]["seen"] is False
    assert _status(client, a)["first_request"]["seen"] is True


def _checklist(status: dict) -> dict:
    return {item["key"]: item["complete"] for item in status["checklist"]}


def test_status_exposes_full_checklist(client, provision, db_session):
    p = provision()
    cl = _checklist(_status(client, p))
    assert set(cl) == {
        "selected_path",
        "has_api_key",
        "has_provider_connection",
        "integration_snippet_viewed",
        "first_request",
        "dashboard_entered",
    }
    assert cl["selected_path"] is False
    assert cl["has_api_key"] is True  # provision creates one
    assert cl["integration_snippet_viewed"] is False
    assert cl["dashboard_entered"] is False


def test_event_marks_snippet_viewed_and_dashboard_entered(client, provision, db_session):
    p = provision()
    for event in ("snippet_viewed", "dashboard_entered"):
        resp = client.post(
            f"/v1/onboarding/event?project_id={p['project_id']}",
            headers=auth_headers(p["token"]),
            json={"event": event},
        )
        assert resp.status_code == 200
    s = _status(client, p)
    assert s["integration_snippet_viewed"] is True
    assert s["dashboard_entered"] is True
    cl = _checklist(s)
    assert cl["integration_snippet_viewed"] is True
    assert cl["dashboard_entered"] is True


def test_event_is_first_write_wins(client, provision, db_session):
    p = provision()
    first = client.post(
        f"/v1/onboarding/event?project_id={p['project_id']}",
        headers=auth_headers(p["token"]),
        json={"event": "snippet_viewed"},
    ).json()["recorded_at"]
    second = client.post(
        f"/v1/onboarding/event?project_id={p['project_id']}",
        headers=auth_headers(p["token"]),
        json={"event": "snippet_viewed"},
    ).json()["recorded_at"]
    assert first == second  # the timestamp does not move on re-fire


def test_event_rejects_unknown_event(client, provision, db_session):
    p = provision()
    resp = client.post(
        f"/v1/onboarding/event?project_id={p['project_id']}",
        headers=auth_headers(p["token"]),
        json={"event": "bogus"},
    )
    assert resp.status_code == 422


def _integration_by_provider(status: dict) -> dict:
    return {row["provider"]: row for row in status["integration"]["providers"]}


def test_integration_fresh_workspace_has_no_method(client, provision, db_session):
    p = provision()
    integ = _status(client, p)["integration"]
    assert integ["any_sdk"] is False
    assert integ["base_url_without_sdk"] is False
    assert _integration_by_provider({"integration": integ})["openai"]["method"] == "none"


def test_integration_detects_sdk_traffic(client, provision, db_session):
    p = provision()
    _add_event(db_session, p, source="proxy", event_metadata={"sdk_client": "@varsten/openai@0.1.0"})
    s = _status(client, p)
    integ = s["integration"]
    assert integ["any_sdk"] is True
    assert integ["base_url_without_sdk"] is False
    row = _integration_by_provider(s)["openai"]
    assert row["method"] == "sdk"
    assert row["sdk_client"] == "@varsten/openai@0.1.0"
    assert s["first_request"]["source"] == "proxy"


def test_integration_flags_base_url_without_sdk(client, provision, db_session):
    p = provision()
    _add_event(db_session, p, source="proxy")  # inline proxy, no SDK marker
    s = _status(client, p)
    integ = s["integration"]
    assert integ["any_sdk"] is False
    assert integ["base_url_without_sdk"] is True
    assert _integration_by_provider(s)["openai"]["method"] == "base_url"


def test_integration_detects_metadata_ingest(client, provision, db_session):
    p = provision()
    _add_event(db_session, p, source="ingest")
    s = _status(client, p)
    integ = s["integration"]
    assert integ["any_sdk"] is False
    assert integ["base_url_without_sdk"] is False
    assert _integration_by_provider(s)["openai"]["method"] == "metadata"
    assert s["first_request"]["source"] == "ingest"
