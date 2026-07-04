"""ChangeRequest lifecycle: propose from evidence, decide by a human, activate on
apply, roll back with the route.

The ChangeRequest (app/models/governance.py) is the single governance object
wrapping a proposed model-swap change. This module owns its transitions:

- ``ensure_change_request`` — the system proposes one when a routing-lever
  recommendation's shadow eval completes with an actionable verdict, freezing
  the evidence bundle the decision will rest on. Idempotent per recommendation.
- ``decide_change_request`` — a named human approves or rejects, with rationale;
  every decision writes an immutable audit event.
- ``assert_change_request_approved`` — when governance enforcement is on
  (``governance_change_requests_enabled``, off by default), applying a gated
  recommendation requires an approved ChangeRequest. Off means propose/decide
  still work but never block, so the object can be adopted incrementally.
- ``mark_change_request_active`` / ``mark_change_request_rolled_back`` — applying
  the recommendation activates the request; a drift rollback closes the loop.

Everything here is control-plane and best-effort where it hooks into other
flows (eval completion, drift rollback): a governance bookkeeping failure must
never break the flow that triggered it.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.config import settings
from app.core.logging import get_logger
from app.engine.route_identity import canonical_route_key
from app.levers import LEVER_PROMPT_COMPRESSION
from app.models import (
    CR_ACTIVE,
    CR_APPROVED,
    CR_PROPOSED,
    CR_REJECTED,
    CR_ROLLED_BACK,
    ROUTING_LEVERS,
    ChangeRequest,
    EvalRun,
    Recommendation,
    User,
)
from app.models.eval import RUN_COMPLETED, VERDICT_NEEDS_HUMAN, VERDICT_SAFE

logger = get_logger("varsten.engine.governance")

# Verdicts that put a change in front of a human (or make it auto-eligible).
_ACTIONABLE_VERDICTS = {VERDICT_SAFE, VERDICT_NEEDS_HUMAN}

# Levers whose changes get a ChangeRequest: the model swaps plus learned prompt
# compression (it changes what the model reads, so it carries the same
# named-approver bar as changing which model answers).
GOVERNED_LEVERS = (*ROUTING_LEVERS, LEVER_PROMPT_COMPRESSION)


class GovernanceError(Exception):
    """A change-request precondition failed (wrong state, missing approval)."""


def _evidence_bundle(run: EvalRun, recommendation: Recommendation) -> dict:
    """The content-free evidence snapshot frozen onto the change request."""
    return {
        "eval": {
            "run_id": str(run.id),
            "verdict": run.verdict,
            "scorer_type": run.scorer_type,
            "sample_count": run.sample_count,
            "win_count": run.win_count,
            "tie_count": run.tie_count,
            "loss_count": run.loss_count,
            "score_delta": str(run.score_delta) if run.score_delta is not None else None,
            "score_delta_ci_low": str(run.score_delta_ci_low) if run.score_delta_ci_low is not None else None,
            "score_delta_ci_high": str(run.score_delta_ci_high) if run.score_delta_ci_high is not None else None,
            "objective_pass_rate": str(run.objective_pass_rate) if run.objective_pass_rate is not None else None,
            "notes": run.notes,
        },
        "savings": {
            "estimated_monthly_savings_usd": (
                str(recommendation.estimated_monthly_savings_usd)
                if recommendation.estimated_monthly_savings_usd is not None
                else None
            ),
            "measurement_method": recommendation.measurement_method,
            "monthly_request_volume": recommendation.monthly_request_volume,
        },
        "risk_level": recommendation.risk_level,
    }


def change_request_for_recommendation(db: Session, recommendation_id) -> ChangeRequest | None:
    return db.scalar(select(ChangeRequest).where(ChangeRequest.recommendation_id == recommendation_id))


def ensure_change_request(db: Session, run: EvalRun) -> ChangeRequest | None:
    """Propose a ChangeRequest for a completed, actionable eval run.

    Called after eval completion. No-op (returns the existing row or None) when
    the run is not completed/actionable, has no recommendation, or the
    recommendation is not a routing lever. Never raises into the caller."""
    try:
        if run.status != RUN_COMPLETED or run.verdict not in _ACTIONABLE_VERDICTS or run.recommendation_id is None:
            return None
        recommendation = db.get(Recommendation, run.recommendation_id)
        if recommendation is None or recommendation.lever not in GOVERNED_LEVERS:
            return None
        existing = change_request_for_recommendation(db, recommendation.id)
        if existing is not None:
            # Refresh the evidence while the request is still undecided; a decided
            # request's bundle is frozen (it is what the approver saw).
            if existing.status == CR_PROPOSED:
                existing.eval_run_id = run.id
                existing.evidence = _evidence_bundle(run, recommendation)
            return existing

        change_request = ChangeRequest(
            organization_id=recommendation.organization_id,
            project_id=recommendation.project_id,
            recommendation_id=recommendation.id,
            eval_run_id=run.id,
            lever=recommendation.lever,
            route_key=canonical_route_key(
                feature=recommendation.related_feature,
                task_type=recommendation.target_key,
            ),
            incumbent_model=run.incumbent_model or recommendation.related_model or "",
            candidate_model=run.candidate_model or "",
            status=CR_PROPOSED,
            evidence=_evidence_bundle(run, recommendation),
        )
        db.add(change_request)
        db.flush()
        logger.info(
            "change request proposed",
            extra={"project_id": str(recommendation.project_id), "change_request_id": str(change_request.id)},
        )
        return change_request
    except Exception:
        logger.exception("change request proposal failed; eval flow unaffected")
        return None


def decide_change_request(
    db: Session,
    change_request: ChangeRequest,
    *,
    user: User,
    approve: bool,
    rationale: str | None,
    source_ip: str | None = None,
    now: datetime | None = None,
) -> ChangeRequest:
    """A named human approves or rejects a proposed change, with rationale.

    Raises GovernanceError when the request is not in a decidable state. Writes
    the immutable audit event in the caller's transaction."""
    if change_request.status != CR_PROPOSED:
        raise GovernanceError(f"change request is {change_request.status}; only a proposed request can be decided")
    at = now or datetime.now(UTC)
    before = {"status": change_request.status}
    change_request.status = CR_APPROVED if approve else CR_REJECTED
    change_request.decided_by_user_id = user.id
    change_request.decided_at = at
    change_request.decision_rationale = rationale
    record_audit(
        db,
        action="change_request.approved" if approve else "change_request.rejected",
        actor=user,
        organization_id=change_request.organization_id,
        project_id=change_request.project_id,
        target_type="change_request",
        target_id=str(change_request.id),
        source_ip=source_ip,
        before=before,
        after={"status": change_request.status},
        details={"rationale": rationale or "", "lever": change_request.lever},
    )
    return change_request


def assert_change_request_approved(db: Session, recommendation: Recommendation) -> None:
    """Enforcement gate for the apply path, active only when
    ``governance_change_requests_enabled`` is on and the lever is a gated
    (routing) lever. Raises GovernanceError when no approved request exists."""
    if not settings.governance_change_requests_enabled:
        return
    if recommendation.lever not in GOVERNED_LEVERS:
        return
    change_request = change_request_for_recommendation(db, recommendation.id)
    if change_request is None:
        raise GovernanceError(
            "Governance is enabled for this workspace: this change needs a ChangeRequest "
            "(created when its shadow eval completes) approved before it can be applied."
        )
    if change_request.status != CR_APPROVED:
        raise GovernanceError(
            f"Governance is enabled for this workspace: the change request is {change_request.status}; "
            "it must be approved before this recommendation can be applied."
        )


def mark_change_request_active(db: Session, recommendation: Recommendation, *, now: datetime | None = None) -> None:
    """Applying the recommendation activates its change request (best-effort;
    kept in sync even when enforcement is off, so the audit trail is continuous)."""
    try:
        change_request = change_request_for_recommendation(db, recommendation.id)
        if change_request is None or change_request.status not in {CR_PROPOSED, CR_APPROVED}:
            return
        change_request.status = CR_ACTIVE
        change_request.updated_at = now or datetime.now(UTC)
    except Exception:
        logger.exception("change request activation sync failed; apply unaffected")


def mark_change_request_rolled_back(
    db: Session, recommendation: Recommendation, *, now: datetime | None = None
) -> None:
    """A rollback (drift guard or human) closes the change request's loop."""
    try:
        change_request = change_request_for_recommendation(db, recommendation.id)
        if change_request is None or change_request.status != CR_ACTIVE:
            return
        change_request.status = CR_ROLLED_BACK
        change_request.updated_at = now or datetime.now(UTC)
    except Exception:
        logger.exception("change request rollback sync failed; rollback unaffected")
