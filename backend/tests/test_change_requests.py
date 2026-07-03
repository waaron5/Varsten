"""ChangeRequest governance (slice F).

One governance object per proposed model swap: proposed by the system from
completed eval evidence, decided by a named human with rationale + audit event,
activated when the recommendation applies, rolled back with the route.
Enforcement (an approved request required to apply) is opt-in and off by default.
"""

import uuid

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.engine import governance
from app.models import (
    CR_ACTIVE,
    CR_APPROVED,
    CR_PROPOSED,
    CR_REJECTED,
    CR_ROLLED_BACK,
    AuditEvent,
    ChangeRequest,
    EvalRun,
    Project,
    Recommendation,
    User,
)
from app.models.eval import RUN_COMPLETED, VERDICT_NEEDS_HUMAN, VERDICT_UNSAFE

INCUMBENT = "gpt-4o"
CANDIDATE = "gpt-4o-mini"


def _project(db_session, provision) -> tuple[Project, User]:
    p = provision()
    project = db_session.get(Project, uuid.UUID(p["project_id"]))
    user = db_session.scalar(select(User).where(User.auth_provider_subject == p["sub"]))
    return project, user


def _recommendation(db_session, project, *, lever="model_downshift") -> Recommendation:
    rec = Recommendation(
        organization_id=project.organization_id,
        project_id=project.id,
        dedupe_key=f"rec-{uuid.uuid4()}",
        type=lever,
        lever=lever,
        title=f"Route {INCUMBENT} -> {CANDIDATE}",
        description="x",
        risk_level="medium",
        confidence="medium",
        related_model=INCUMBENT,
        related_feature="support_agent",
    )
    db_session.add(rec)
    db_session.flush()
    return rec


def _completed_run(db_session, project, rec, *, verdict=VERDICT_NEEDS_HUMAN) -> EvalRun:
    run = EvalRun(
        organization_id=project.organization_id,
        project_id=project.id,
        recommendation_id=rec.id,
        lever=rec.lever,
        route_key=INCUMBENT,
        incumbent_model=INCUMBENT,
        candidate_model=CANDIDATE,
        status=RUN_COMPLETED,
        verdict=verdict,
        sample_count=25,
        win_count=10,
        tie_count=12,
        loss_count=3,
        notes="test run",
    )
    db_session.add(run)
    db_session.flush()
    return run


# --- proposal -------------------------------------------------------------------


def test_actionable_eval_proposes_change_request(db_session, provision):
    project, _ = _project(db_session, provision)
    rec = _recommendation(db_session, project)
    run = _completed_run(db_session, project, rec)

    change_request = governance.ensure_change_request(db_session, run)

    assert change_request is not None
    assert change_request.status == CR_PROPOSED
    assert change_request.incumbent_model == INCUMBENT
    assert change_request.candidate_model == CANDIDATE
    assert change_request.route_key == "support_agent"
    assert change_request.evidence["eval"]["verdict"] == VERDICT_NEEDS_HUMAN
    assert change_request.evidence["eval"]["sample_count"] == 25
    assert change_request.evidence["risk_level"] == "medium"


def test_proposal_is_idempotent(db_session, provision):
    project, _ = _project(db_session, provision)
    rec = _recommendation(db_session, project)
    run = _completed_run(db_session, project, rec)

    first = governance.ensure_change_request(db_session, run)
    second = governance.ensure_change_request(db_session, run)

    assert first is not None
    assert second is not None
    assert first.id == second.id
    count = db_session.scalar(select(ChangeRequest).where(ChangeRequest.recommendation_id == rec.id))
    assert count is not None


def test_unsafe_verdict_proposes_nothing(db_session, provision):
    project, _ = _project(db_session, provision)
    rec = _recommendation(db_session, project)
    run = _completed_run(db_session, project, rec, verdict=VERDICT_UNSAFE)

    assert governance.ensure_change_request(db_session, run) is None


def test_non_routing_lever_proposes_nothing(db_session, provision):
    project, _ = _project(db_session, provision)
    rec = _recommendation(db_session, project, lever="token_trim")
    run = _completed_run(db_session, project, rec)

    assert governance.ensure_change_request(db_session, run) is None


# --- decision -------------------------------------------------------------------


def test_approval_records_actor_rationale_and_audit(db_session, provision):
    project, user = _project(db_session, provision)
    rec = _recommendation(db_session, project)
    run = _completed_run(db_session, project, rec)
    change_request = governance.ensure_change_request(db_session, run)

    assert change_request is not None
    governance.decide_change_request(
        db_session, change_request, user=user, approve=True, rationale="Eval cleared; ship it."
    )
    db_session.flush()

    assert change_request.status == CR_APPROVED
    assert change_request.decided_by_user_id == user.id
    assert change_request.decision_rationale == "Eval cleared; ship it."
    assert change_request.decided_at is not None

    audit = db_session.scalar(
        select(AuditEvent).where(
            AuditEvent.action == "change_request.approved",
            AuditEvent.target_id == str(change_request.id),
        )
    )
    assert audit is not None
    assert audit.actor_user_id == user.id
    assert audit.details["rationale"] == "Eval cleared; ship it."


def test_only_proposed_can_be_decided(db_session, provision):
    project, user = _project(db_session, provision)
    rec = _recommendation(db_session, project)
    run = _completed_run(db_session, project, rec)
    change_request = governance.ensure_change_request(db_session, run)
    assert change_request is not None
    governance.decide_change_request(db_session, change_request, user=user, approve=False, rationale="no")

    assert change_request.status == CR_REJECTED
    with pytest.raises(governance.GovernanceError):
        governance.decide_change_request(db_session, change_request, user=user, approve=True, rationale="flip")


# --- enforcement gate ------------------------------------------------------------


def test_enforcement_off_never_blocks(db_session, provision, monkeypatch):
    monkeypatch.setattr(settings, "governance_change_requests_enabled", False)
    project, _ = _project(db_session, provision)
    rec = _recommendation(db_session, project)
    # No change request exists at all: with enforcement off this must not raise.
    governance.assert_change_request_approved(db_session, rec)


def test_enforcement_blocks_without_approval(db_session, provision, monkeypatch):
    monkeypatch.setattr(settings, "governance_change_requests_enabled", True)
    project, user = _project(db_session, provision)
    rec = _recommendation(db_session, project)

    # Missing entirely -> blocked.
    with pytest.raises(governance.GovernanceError):
        governance.assert_change_request_approved(db_session, rec)

    # Proposed but undecided -> blocked.
    run = _completed_run(db_session, project, rec)
    change_request = governance.ensure_change_request(db_session, run)
    assert change_request is not None
    with pytest.raises(governance.GovernanceError):
        governance.assert_change_request_approved(db_session, rec)

    # Approved -> allowed.
    governance.decide_change_request(db_session, change_request, user=user, approve=True, rationale="ok")
    governance.assert_change_request_approved(db_session, rec)


def test_enforcement_ignores_ungated_levers(db_session, provision, monkeypatch):
    monkeypatch.setattr(settings, "governance_change_requests_enabled", True)
    project, _ = _project(db_session, provision)
    rec = _recommendation(db_session, project, lever="token_trim")
    governance.assert_change_request_approved(db_session, rec)  # no raise


# --- lifecycle sync --------------------------------------------------------------


def test_apply_and_rollback_lifecycle(db_session, provision):
    project, user = _project(db_session, provision)
    rec = _recommendation(db_session, project)
    run = _completed_run(db_session, project, rec)
    change_request = governance.ensure_change_request(db_session, run)
    assert change_request is not None
    governance.decide_change_request(db_session, change_request, user=user, approve=True, rationale="ok")

    governance.mark_change_request_active(db_session, rec)
    assert change_request.status == CR_ACTIVE

    governance.mark_change_request_rolled_back(db_session, rec)
    assert change_request.status == CR_ROLLED_BACK


# --- endpoints -------------------------------------------------------------------


def test_endpoints_list_and_decide(client, provision, db_session):
    p = provision()
    project = db_session.get(Project, uuid.UUID(p["project_id"]))
    user = db_session.scalar(select(User).where(User.auth_provider_subject == p["sub"]))
    rec = _recommendation(db_session, project)
    run = _completed_run(db_session, project, rec)
    governance.ensure_change_request(db_session, run)
    db_session.flush()

    headers = {"Authorization": f"Bearer {p['sub']}"}
    listed = client.get(
        "/v1/engine/change-requests",
        headers=headers,
        params={"project_id": str(project.id), "status": "proposed"},
    )
    assert listed.status_code == 200
    rows = listed.json()
    assert len(rows) == 1
    assert rows[0]["status"] == "proposed"
    assert rows[0]["evidence"]["eval"]["verdict"] == VERDICT_NEEDS_HUMAN

    decided = client.post(
        f"/v1/engine/change-requests/{rows[0]['id']}/decision",
        headers=headers,
        params={"project_id": str(project.id)},
        json={"action": "approve", "rationale": "LGTM"},
    )
    assert decided.status_code == 200
    body = decided.json()
    assert body["status"] == "approved"
    assert body["decision_rationale"] == "LGTM"
    assert body["decided_by_user_id"] == str(user.id)

    # Deciding twice conflicts.
    again = client.post(
        f"/v1/engine/change-requests/{rows[0]['id']}/decision",
        headers=headers,
        params={"project_id": str(project.id)},
        json={"action": "reject", "rationale": "flip"},
    )
    assert again.status_code == 409


def test_decision_is_tenant_scoped(client, provision, db_session):
    p1 = provision(sub="auth0|cr1", email="cr1@example.com")
    p2 = provision(sub="auth0|cr2", email="cr2@example.com", project_name="other")
    project1 = db_session.get(Project, uuid.UUID(p1["project_id"]))
    rec = _recommendation(db_session, project1)
    run = _completed_run(db_session, project1, rec)
    change_request = governance.ensure_change_request(db_session, run)
    assert change_request is not None
    db_session.flush()

    # A user in another org, resolving their own project, cannot see or decide it.
    res = client.post(
        f"/v1/engine/change-requests/{change_request.id}/decision",
        headers={"Authorization": "Bearer auth0|cr2"},
        params={"project_id": p2["project_id"]},
        json={"action": "approve", "rationale": "x"},
    )
    assert res.status_code == 404
