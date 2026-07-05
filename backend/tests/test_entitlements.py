"""Observe-only enforcement: a Free workspace can never activate a
behaviour-changing lever. Performance can. Enforcement is backend-side."""

import uuid
from decimal import Decimal

from sqlalchemy import func, select

from app.models import Organization, ProxyPolicy, Recommendation
from tests.conftest import auth_headers


def _make_recommendation(db_session, p, *, lever="semantic_cache", status="open") -> Recommendation:
    rec = Recommendation(
        organization_id=uuid.UUID(p["org_id"]),
        project_id=uuid.UUID(p["project_id"]),
        dedupe_key=f"{lever}:test:{uuid.uuid4()}",
        type=lever,
        lever=lever,
        title="Test recommendation",
        description="x",
        estimated_monthly_savings_usd=Decimal("100"),
        measurement_method="estimated",
        risk_level="low",
        confidence="high",
        status=status,
    )
    db_session.add(rec)
    db_session.flush()
    return rec


def _set_performance(db_session, org_id: str) -> None:
    org = db_session.get(Organization, uuid.UUID(org_id))
    org.plan_tier = "performance"
    db_session.flush()


def _q(project_id: str) -> str:
    return f"?project_id={project_id}"


def test_free_cannot_apply_recommendation(client, provision, db_session):
    p = provision()
    rec = _make_recommendation(db_session, p)

    resp = client.patch(
        f"/v1/engine/recommendations/{rec.id}{_q(p['project_id'])}",
        headers=auth_headers(p["token"]),
        json={"status": "applied"},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "feature_requires_performance"

    # Observe-only held: recommendation stayed open and no policy was activated.
    db_session.refresh(rec)
    assert rec.status == "open"
    policies = db_session.scalar(
        select(func.count()).select_from(ProxyPolicy).where(ProxyPolicy.project_id == uuid.UUID(p["project_id"]))
    )
    assert policies == 0


def test_free_can_dismiss_recommendation(client, provision, db_session):
    p = provision()
    rec = _make_recommendation(db_session, p)
    resp = client.patch(
        f"/v1/engine/recommendations/{rec.id}{_q(p['project_id'])}",
        headers=auth_headers(p["token"]),
        json={"status": "dismissed"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "dismissed"


def test_performance_can_apply_recommendation(client, provision, db_session):
    p = provision()
    _set_performance(db_session, p["org_id"])
    rec = _make_recommendation(db_session, p, lever="semantic_cache")

    resp = client.patch(
        f"/v1/engine/recommendations/{rec.id}{_q(p['project_id'])}",
        headers=auth_headers(p["token"]),
        json={"status": "applied"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "applied"


def _make_route_policy(db_session, p, *, enabled=False) -> ProxyPolicy:
    policy = ProxyPolicy(
        organization_id=uuid.UUID(p["org_id"]),
        project_id=uuid.UUID(p["project_id"]),
        lever="model_downshift",
        target_type="model",
        target_key="gpt-4o-mini",
        enabled=enabled,
        holdback_percent=Decimal("0.05"),
        params={"candidate_model": "gpt-3.5-turbo"},
    )
    db_session.add(policy)
    db_session.flush()
    return policy


def _make_compression_policy(db_session, p, *, enabled=False) -> ProxyPolicy:
    policy = ProxyPolicy(
        organization_id=uuid.UUID(p["org_id"]),
        project_id=uuid.UUID(p["project_id"]),
        lever="prompt_compression",
        target_type="model",
        target_key="gpt-4o-mini",
        enabled=enabled,
        holdback_percent=Decimal("0.05"),
        params={"artifact_id": str(uuid.uuid4())},
    )
    db_session.add(policy)
    db_session.flush()
    return policy


def test_free_cannot_enable_route(client, provision, db_session):
    p = provision()
    policy = _make_route_policy(db_session, p, enabled=False)
    resp = client.patch(
        f"/v1/engine/routes/{policy.id}{_q(p['project_id'])}",
        headers=auth_headers(p["token"]),
        json={"enabled": True},
    )
    assert resp.status_code == 403
    db_session.refresh(policy)
    assert policy.enabled is False


def test_free_can_pause_route(client, provision, db_session):
    p = provision()
    policy = _make_route_policy(db_session, p, enabled=True)
    resp = client.patch(
        f"/v1/engine/routes/{policy.id}{_q(p['project_id'])}",
        headers=auth_headers(p["token"]),
        json={"enabled": False},
    )
    assert resp.status_code == 200
    db_session.refresh(policy)
    assert policy.enabled is False


def test_performance_can_enable_route(client, provision, db_session):
    p = provision()
    _set_performance(db_session, p["org_id"])
    policy = _make_route_policy(db_session, p, enabled=False)
    resp = client.patch(
        f"/v1/engine/routes/{policy.id}{_q(p['project_id'])}",
        headers=auth_headers(p["token"]),
        json={"enabled": True},
    )
    assert resp.status_code == 200
    db_session.refresh(policy)
    assert policy.enabled is True


def test_free_cannot_enable_compression_policy(client, provision, db_session):
    p = provision()
    policy = _make_compression_policy(db_session, p, enabled=False)
    resp = client.patch(
        f"/v1/engine/compressions/{policy.id}{_q(p['project_id'])}",
        headers=auth_headers(p["token"]),
        json={"enabled": True},
    )
    assert resp.status_code == 403
    db_session.refresh(policy)
    assert policy.enabled is False


def test_free_can_pause_compression_policy(client, provision, db_session):
    p = provision()
    policy = _make_compression_policy(db_session, p, enabled=True)
    resp = client.patch(
        f"/v1/engine/compressions/{policy.id}{_q(p['project_id'])}",
        headers=auth_headers(p["token"]),
        json={"enabled": False},
    )
    assert resp.status_code == 200
    db_session.refresh(policy)
    assert policy.enabled is False


def test_free_cannot_enable_lever(client, provision, db_session):
    p = provision()
    resp = client.patch(
        f"/v1/engine/levers/semantic_cache{_q(p['project_id'])}",
        headers=auth_headers(p["token"]),
        json={"enabled": True},
    )
    # The behaviour-changing toggle is gated. (lever_configs.enabled is a display
    # intent flag; actual production behaviour requires a proxy_policy, which a free
    # workspace still cannot create.)
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "feature_requires_performance"


def test_free_cannot_enable_automation(client, provision, db_session):
    p = provision()
    resp = client.patch(
        f"/v1/engine/levers/semantic_cache{_q(p['project_id'])}",
        headers=auth_headers(p["token"]),
        json={"automation_mode": "auto"},
    )
    assert resp.status_code == 403


def test_entitlements_free(client, provision, db_session):
    p = provision()
    resp = client.get(f"/v1/entitlements{_q(p['project_id'])}", headers=auth_headers(p["token"]))
    assert resp.status_code == 200
    body = resp.json()
    assert body["plan_tier"] == "free"
    assert body["observe_only"] is True
    assert body["features"]["apply_recommendations"] is False
    assert body["features"]["submit_batches"] is False


def test_entitlements_performance(client, provision, db_session):
    p = provision()
    _set_performance(db_session, p["org_id"])
    resp = client.get(f"/v1/entitlements{_q(p['project_id'])}", headers=auth_headers(p["token"]))
    assert resp.status_code == 200
    body = resp.json()
    assert body["plan_tier"] == "performance"
    assert body["observe_only"] is False
    assert body["features"]["apply_recommendations"] is True
    assert body["features"]["guardrail_automation"] is True
    assert body["features"]["advanced_reports"] is True


# --- behaviour-changing guardrail / report gates -----------------------------


def test_free_can_create_soft_budget_but_not_hard_cap(client, provision, db_session):
    p = provision()
    base = {"owner_type": "team", "owner_key": "support", "monthly_budget_usd": "100"}
    ok = client.post(
        f"/v1/guardrails/budgets{_q(p['project_id'])}",
        headers=auth_headers(p["token"]),
        json={**base, "hard_cap_enabled": False},
    )
    assert ok.status_code == 201
    blocked = client.post(
        f"/v1/guardrails/budgets{_q(p['project_id'])}",
        headers=auth_headers(p["token"]),
        json={"owner_type": "team", "owner_key": "eng", "monthly_budget_usd": "100", "hard_cap_enabled": True},
    )
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["code"] == "feature_requires_performance"


def test_free_can_create_quality_floor_but_not_auto_rollback(client, provision, db_session):
    p = provision()
    ok = client.post(
        f"/v1/guardrails/quality{_q(p['project_id'])}",
        headers=auth_headers(p["token"]),
        json={"route": "gpt-4o-mini", "auto_rollback_enabled": False},
    )
    assert ok.status_code == 201
    blocked = client.post(
        f"/v1/guardrails/quality{_q(p['project_id'])}",
        headers=auth_headers(p["token"]),
        json={"route": "gpt-4o", "auto_rollback_enabled": True},
    )
    assert blocked.status_code == 403


def test_free_cannot_generate_report_performance_can(client, provision, db_session):
    p = provision()
    blocked = client.post(f"/v1/reports{_q(p['project_id'])}", headers=auth_headers(p["token"]))
    assert blocked.status_code == 403
    _set_performance(db_session, p["org_id"])
    ok = client.post(f"/v1/reports{_q(p['project_id'])}", headers=auth_headers(p["token"]))
    assert ok.status_code == 201
