import uuid
from importlib import import_module

import pytest

from app.models import Organization, Project


def _future_attr(module: str, name: str):
    return getattr(import_module(module), name)


@pytest.mark.parametrize(
    "reason_code,client_dialect,requested_provider,candidate_provider",
    [
        ("anthropic_cache_control", "anthropic", "anthropic", "openai"),
        ("anthropic_beta_unsupported", "anthropic", "anthropic", "gemini"),
        ("gemini_safety_settings", "gemini_native", "gemini", "anthropic"),
        ("server_side_tool", "anthropic", "anthropic", "gemini"),
        ("native_multimodal_unmapped", "gemini_native", "gemini", "openai"),
    ],
)
def test_cross_provider_routing_ineligibility_is_persisted_with_exact_reason(
    db_session,
    reason_code,
    client_dialect,
    requested_provider,
    candidate_provider,
):
    record_ineligible_decision = _future_attr("app.proxy.optimization_decisions", "record_ineligible_decision")
    OptimizationDecision = _future_attr("app.models", "OptimizationDecision")

    org = Organization(name="routing-audit-org")
    db_session.add(org)
    db_session.flush()
    project = Project(organization_id=org.id, name="routing-audit-project")
    db_session.add(project)
    db_session.flush()

    request_id = f"req_{uuid.uuid4().hex}"
    decision = record_ineligible_decision(
        db_session,
        organization_id=org.id,
        project_id=project.id,
        request_id=request_id,
        client_dialect=client_dialect,
        requested_provider=requested_provider,
        requested_model="claude-3-5-sonnet-20241022" if requested_provider == "anthropic" else "gemini-3.5-flash",
        candidate_provider=candidate_provider,
        candidate_model="gpt-4o-mini" if candidate_provider == "openai" else "gemini-3.5-flash",
        decision="ineligible",
        reason_code=reason_code,
        reason_detail={"fixture": True},
    )
    db_session.commit()

    row = db_session.get(OptimizationDecision, decision.id)
    assert row is not None
    assert row.request_id == request_id
    assert row.decision == "ineligible"
    assert row.reason_code == reason_code
    assert row.requested_provider == requested_provider
    assert row.candidate_provider == candidate_provider
    assert row.reason_detail["fixture"] is True


def test_routing_ineligibility_audit_is_durable_not_log_only(db_session):
    record_ineligible_decision = _future_attr("app.proxy.optimization_decisions", "record_ineligible_decision")
    OptimizationDecision = _future_attr("app.models", "OptimizationDecision")

    org = Organization(name="routing-audit-durable-org")
    db_session.add(org)
    db_session.flush()
    project = Project(organization_id=org.id, name="routing-audit-durable-project")
    db_session.add(project)
    db_session.flush()

    request_id = f"req_{uuid.uuid4().hex}"
    decision = record_ineligible_decision(
        db_session,
        organization_id=org.id,
        project_id=project.id,
        request_id=request_id,
        client_dialect="anthropic",
        requested_provider="anthropic",
        requested_model="claude-3-5-sonnet-20241022",
        candidate_provider="gemini",
        candidate_model="gemini-3.5-flash",
        decision="ineligible",
        reason_code="anthropic_cache_control",
        reason_detail={"path": "/v1/messages", "field": "cache_control"},
    )
    db_session.commit()
    db_session.expire_all()

    row = db_session.get(OptimizationDecision, decision.id)
    assert row is not None
    assert row.request_id == request_id
    assert row.reason_detail == {"path": "/v1/messages", "field": "cache_control"}
