"""Inline model routing: the execution side of the model-swap levers.

`resolve_route` runs on the proxy hot path. It is a single indexed lookup and
fails open: any error returns None (forward the requested model unchanged), so a
routing problem can never break a request, only stop a saving. (The in-VPC
north-star caches this policy in memory; a query is fine at this stage and
mirrors the existing cache lookup.)

`activate_rule` / `deactivate_rules_for_recommendation` run on the control plane
when a recommendation is applied or dismissed. They read and write the unified
`proxy_policies` table; this module owns the routing-lever (model_downshift,
smart_routing) view of it.
"""

import random
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.levers import LEVER_MODEL_DOWNSHIFT, LEVER_SMART_ROUTING
from app.models import ROUTING_LEVERS, Project, ProxyPolicy, Recommendation
from app.proxy import canary
from app.proxy import predicate as predicate_mod

logger = get_logger("varsten.proxy.routing")

SMART_ROUTING = LEVER_SMART_ROUTING

# Ledger metadata arm tags for the live holdback A/B.
ARM_CONTROL = "control"
ARM_TREATMENT = "treatment"


class RouteDecision(NamedTuple):
    candidate_model: str
    candidate_provider: str
    holdback_percent: Decimal
    # Provenance for the moat decision-evidence record. Optional/defaulted so
    # existing constructors and tests are unaffected.
    lever: str | None = None
    policy_id: uuid.UUID | None = None
    source_recommendation_id: uuid.UUID | None = None


async def _routing_policy_for_model(
    db: AsyncSession, project_id: uuid.UUID, requested_model: str
) -> ProxyPolicy | None:
    """The enabled routing-lever policy that applies to this incumbent model, if
    any. At most one is expected; the most recently activated wins if not."""
    return (
        await db.scalars(
            select(ProxyPolicy)
            .where(
                ProxyPolicy.project_id == project_id,
                ProxyPolicy.lever.in_(ROUTING_LEVERS),
                ProxyPolicy.target_key == requested_model,
                ProxyPolicy.enabled.is_(True),
            )
            .order_by(ProxyPolicy.activated_at.desc().nullslast())
            .limit(1)
        )
    ).first()


async def resolve_route(
    db: AsyncSession,
    project_id: uuid.UUID,
    requested_model: str,
    body: dict | None = None,
    *,
    requested_provider: str = "openai",
) -> RouteDecision | None:
    """The candidate model and holdback fraction for an enabled routing policy on
    this model, or None when none applies. For smart_routing the per-request
    predicate decides eligibility: a request that fails it stays on the incumbent
    (returns None) and never enters the holdback experiment. Fail-open: any error
    returns None (forward the original model)."""
    if not requested_model:
        return None
    try:
        policy = await _routing_policy_for_model(db, project_id, requested_model)
        if policy is None or not policy.candidate_model:
            return None
        if policy.lever == SMART_ROUTING:
            pred = (policy.params or {}).get("predicate")
            if not predicate_mod.is_eligible(body or {}, pred):
                return None
        # Canary gate: a request outside the policy's current rollout stays on the
        # incumbent as plain passthrough (not an experiment arm). Independent of
        # the holdback arm draw the caller makes next.
        if not canary.in_rollout(policy.rollout_percent):
            return None
        return RouteDecision(
            policy.candidate_model,
            policy.candidate_provider or requested_provider,
            policy.holdback_percent or Decimal("0"),
            lever=policy.lever,
            policy_id=policy.id,
            source_recommendation_id=policy.source_recommendation_id,
        )
    except Exception:
        logger.exception("routing lookup failed; forwarding original model", extra={"project_id": str(project_id)})
        return None


def assign_arm(holdback_percent: Decimal) -> str:
    """Randomly assign this request to the control (held back on the incumbent) or
    treatment (routed to the candidate) arm. Concurrent and per-request, so any
    app-level or price change lands on both arms and cancels."""
    # Holdback assignment is statistical, not security-sensitive randomness.
    return ARM_CONTROL if random.random() < float(holdback_percent or 0) else ARM_TREATMENT  # nosec B311


def resolve_effective_model(db: Session, project_id: uuid.UUID, requested_model: str) -> str | None:
    """The candidate model an enabled routing policy routes this request to, or
    None when none applies. Sync (control-plane callers); uses its own query rather
    than the async hot-path helper. Fail-open: on any error, return None."""
    if not requested_model:
        return None
    try:
        policy = db.scalars(
            select(ProxyPolicy)
            .where(
                ProxyPolicy.project_id == project_id,
                ProxyPolicy.lever.in_(ROUTING_LEVERS),
                ProxyPolicy.target_key == requested_model,
                ProxyPolicy.enabled.is_(True),
            )
            .order_by(ProxyPolicy.activated_at.desc().nullslast())
            .limit(1)
        ).first()
        return policy.candidate_model if policy is not None else None
    except Exception:
        logger.exception("routing lookup failed; forwarding original model", extra={"project_id": str(project_id)})
        return None


def activate_rule(
    db: Session,
    project: Project,
    recommendation: Recommendation,
    candidate_model: str,
    *,
    now: datetime | None = None,
) -> ProxyPolicy | None:
    """Activate (or refresh) the routing policy for an applied model-swap
    recommendation. Returns None when the recommendation lacks an incumbent model
    or a candidate to route to."""
    incumbent = recommendation.related_model
    lever = recommendation.lever if recommendation.lever in ROUTING_LEVERS else LEVER_MODEL_DOWNSHIFT
    if not incumbent or not candidate_model or incumbent == candidate_model:
        return None
    at = now or datetime.now(UTC)
    policy = db.scalar(
        select(ProxyPolicy).where(
            ProxyPolicy.project_id == project.id,
            ProxyPolicy.lever == lever,
            ProxyPolicy.target_key == incumbent,
        )
    )
    # A brand-new policy, or one being re-enabled after a rollback/dismiss, starts
    # a fresh canary ramp; refreshing an already-live policy keeps its rollout.
    fresh = policy is None or not policy.enabled
    if policy is None:
        policy = ProxyPolicy(
            organization_id=project.organization_id,
            project_id=project.id,
            lever=lever,
            target_type="model",
            target_key=incumbent,
        )
        db.add(policy)
    params = {**(policy.params or {}), "candidate_model": candidate_model}
    # Smart routing gates each request on a deterministic predicate; seed a
    # conservative default the operator can tune. A plain model-downshift swap has
    # no predicate (every request on the model is routed).
    if lever == SMART_ROUTING and "predicate" not in params:
        params["predicate"] = dict(predicate_mod.DEFAULT_PREDICATE)
    policy.params = params
    if fresh:
        policy.rollout_percent = canary.initial_rollout_percent()
    policy.enabled = True
    policy.source_recommendation_id = recommendation.id
    policy.activated_at = at
    return policy


def deactivate_rules_for_recommendation(db: Session, recommendation: Recommendation) -> None:
    """Turn off any policy sourced from this recommendation (e.g. on dismiss or
    rollback), returning that route to the incumbent model."""
    db.execute(
        update(ProxyPolicy).where(ProxyPolicy.source_recommendation_id == recommendation.id).values(enabled=False)
    )
