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
from app.engine import bandit
from app.engine.priors import candidate_stats_for_request
from app.engine.route_identity import DEFAULT_ROUTE, route_key_from_recommendation
from app.levers import LEVER_MODEL_DOWNSHIFT, LEVER_SMART_ROUTING
from app.models import (
    CR_ACTIVE,
    CR_APPROVED,
    ROUTING_LEVERS,
    ChangeRequest,
    EvalRun,
    Project,
    ProxyPolicy,
    Recommendation,
)
from app.models.eval import RUN_COMPLETED, VERDICT_NEEDS_HUMAN, VERDICT_SAFE
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
    # Content-free record of the bandit's selection (or shadow would-be
    # selection) for the runtime trace; None when the bandit did not run.
    bandit_trace: dict | None = None


def bandit_candidate_entries(policy: ProxyPolicy) -> list[dict]:
    """The policy's eval-cleared additional candidates: [{"model", "provider"}].
    Only ``add_bandit_candidate`` may grow this list (it enforces clearance)."""
    entries = (policy.params or {}).get("bandit_candidates")
    if not isinstance(entries, list):
        return []
    return [e for e in entries if isinstance(e, dict) and e.get("model")]


async def _routing_policy_for_model(
    db: AsyncSession,
    project_id: uuid.UUID,
    requested_model: str,
    *,
    route_key: str | None = None,
) -> ProxyPolicy | None:
    """The enabled routing-lever policy that applies to this incumbent model, if
    any. At most one is expected; the most recently activated wins if not."""
    base = (
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
    if route_key:
        exact = (await db.scalars(base.where(ProxyPolicy.route_key == route_key))).first()
        if exact is not None:
            return exact
        return (await db.scalars(base.where(ProxyPolicy.route_key == DEFAULT_ROUTE))).first()
    return (await db.scalars(base)).first()


async def resolve_route(
    db: AsyncSession,
    project_id: uuid.UUID,
    requested_model: str,
    body: dict | None = None,
    *,
    requested_provider: str = "openai",
    route_key: str | None = None,
) -> RouteDecision | None:
    """The candidate model and holdback fraction for an enabled routing policy on
    this model, or None when none applies. For smart_routing the per-request
    predicate decides eligibility: a request that fails it stays on the incumbent
    (returns None) and never enters the holdback experiment. Fail-open: any error
    returns None (forward the original model)."""
    if not requested_model:
        return None
    try:
        policy = await _routing_policy_for_model(db, project_id, requested_model, route_key=route_key)
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
        chosen_model = policy.candidate_model
        chosen_provider = policy.candidate_provider or requested_provider
        chosen_model, chosen_provider, bandit_trace = await _maybe_bandit_select(
            db, project_id, requested_model, policy, chosen_model, chosen_provider
        )
        return RouteDecision(
            chosen_model,
            chosen_provider,
            policy.holdback_percent or Decimal("0"),
            lever=policy.lever,
            policy_id=policy.id,
            source_recommendation_id=policy.source_recommendation_id,
            bandit_trace=bandit_trace,
        )
    except Exception:
        logger.exception("routing lookup failed; forwarding original model", extra={"project_id": str(project_id)})
        return None


async def _maybe_bandit_select(
    db: AsyncSession,
    project_id: uuid.UUID,
    requested_model: str,
    policy: ProxyPolicy,
    primary_model: str,
    primary_provider: str,
) -> tuple[str, str, dict | None]:
    """Bandit selection among the policy's eval-cleared candidates, when enabled.

    Off (default): a pure no-op. Shadow: the sampler runs and its would-be choice
    is returned in the trace, but the primary still gets the traffic. Active: the
    sampled candidate is routed. Fail-open on its own: any error keeps the
    primary, so the bandit can only ever change *which cleared candidate* serves,
    never whether the request is served."""
    mode = bandit.mode()
    if mode == bandit.MODE_OFF:
        return primary_model, primary_provider, None
    extra_entries = bandit_candidate_entries(policy)
    if not extra_entries:
        return primary_model, primary_provider, None
    try:
        stats_by_model = {
            s.model: s for s in await candidate_stats_for_request(db, project_id, requested_model, policy.route_key)
        }
        allowed: list[bandit.CandidateStats] = []
        for entry in ({"model": primary_model, "provider": primary_provider}, *extra_entries):
            known = stats_by_model.get(entry["model"])
            if known is not None:
                allowed.append(known)
            else:
                # Cold candidate: no ledger evidence yet. It can only win via the
                # budgeted exploration path.
                allowed.append(
                    bandit.CandidateStats(
                        model=entry["model"],
                        provider=entry.get("provider") or primary_provider,
                        sample_count=0,
                        quality_pass_rate=None,
                        average_savings_usd=None,
                    )
                )
        choice = bandit.select_candidate(primary_model, primary_provider, allowed)
        trace = {"mode": mode, **choice.trace_detail()}
        if mode == bandit.MODE_ACTIVE:
            return choice.model, choice.provider, trace
        return primary_model, primary_provider, trace  # shadow: telemetry only
    except Exception:
        logger.exception("bandit selection failed; routing to primary candidate")
        return primary_model, primary_provider, None


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
    route_key = route_key_from_recommendation(recommendation)
    policy_route_key = route_key or DEFAULT_ROUTE
    stmt = select(ProxyPolicy).where(
        ProxyPolicy.project_id == project.id,
        ProxyPolicy.lever == lever,
        ProxyPolicy.target_key == incumbent,
        ProxyPolicy.route_key == policy_route_key,
    )
    policy = db.scalar(stmt)
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
    policy.route_key = policy_route_key
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


# --- bandit candidate management (control plane) --------------------------------


class BanditCandidateError(Exception):
    """Adding/removing a bandit candidate failed a precondition (not eval-cleared,
    duplicate, wrong lever, ...). Message is safe to surface to the operator."""


def _latest_completed_run(db: Session, project_id, incumbent: str, candidate: str) -> EvalRun | None:
    return db.scalar(
        select(EvalRun)
        .where(
            EvalRun.project_id == project_id,
            EvalRun.incumbent_model == incumbent,
            EvalRun.candidate_model == candidate,
            EvalRun.status == RUN_COMPLETED,
        )
        .order_by(EvalRun.created_at.desc())
        .limit(1)
    )


def _assert_candidate_cleared(db: Session, policy: ProxyPolicy, candidate_model: str) -> EvalRun:
    """The eval/governance clearance gate for adding a bandit candidate.

    ``safe`` clears on the eval alone; ``needs_human`` (subjective route) clears
    only with an approved/active ChangeRequest behind the run's recommendation —
    the same bar a single-candidate apply has to meet. Anything else is blocked."""
    run = _latest_completed_run(db, policy.project_id, policy.incumbent_model, candidate_model)
    if run is None:
        raise BanditCandidateError(
            f"{candidate_model} has no completed shadow eval against {policy.incumbent_model}; "
            "run one before it can join the bandit candidate set."
        )
    if run.verdict == VERDICT_SAFE:
        return run
    if run.verdict == VERDICT_NEEDS_HUMAN:
        if run.recommendation_id is not None:
            approved = db.scalar(
                select(ChangeRequest).where(
                    ChangeRequest.recommendation_id == run.recommendation_id,
                    ChangeRequest.status.in_([CR_APPROVED, CR_ACTIVE]),
                )
            )
            if approved is not None:
                return run
        raise BanditCandidateError(
            f"{candidate_model} cleared its eval for human approval only; approve its "
            "ChangeRequest before it can join the bandit candidate set."
        )
    raise BanditCandidateError(
        f"{candidate_model} did not clear its shadow eval (verdict: {run.verdict}); it cannot join the candidate set."
    )


def add_bandit_candidate(
    db: Session,
    policy: ProxyPolicy,
    candidate_model: str,
    *,
    candidate_provider: str | None = None,
) -> ProxyPolicy:
    """Add an eval-cleared candidate to a routing policy's bandit set.

    This is the only writer of ``params["bandit_candidates"]``; every entry in
    that list has passed the clearance gate above. The bandit itself never widens
    the set — it only chooses within it."""
    if policy.lever not in ROUTING_LEVERS:
        raise BanditCandidateError("bandit candidates only apply to routing-lever policies")
    if not candidate_model or candidate_model == policy.incumbent_model:
        raise BanditCandidateError("candidate must be a real model different from the incumbent")
    if candidate_model == policy.candidate_model:
        raise BanditCandidateError(f"{candidate_model} is already the policy's primary candidate")
    entries = bandit_candidate_entries(policy)
    if any(entry["model"] == candidate_model for entry in entries):
        raise BanditCandidateError(f"{candidate_model} is already in the bandit candidate set")

    run = _assert_candidate_cleared(db, policy, candidate_model)
    entries = [
        *entries,
        {
            "model": candidate_model,
            "provider": candidate_provider or "openai",
            "eval_run_id": str(run.id),
        },
    ]
    policy.params = {**(policy.params or {}), "bandit_candidates": entries}
    logger.info(
        "bandit candidate added",
        extra={"project_id": str(policy.project_id), "policy_id": str(policy.id), "candidate": candidate_model},
    )
    return policy


def remove_bandit_candidate(db: Session, policy: ProxyPolicy, candidate_model: str) -> bool:
    """Remove a candidate from the bandit set (operator action or drift guard).
    Returns whether it was present. The primary candidate is not removable here —
    rolling back the primary is the whole-policy rollback path."""
    del db  # symmetry with add; the caller owns flush/commit
    entries = bandit_candidate_entries(policy)
    remaining = [entry for entry in entries if entry["model"] != candidate_model]
    if len(remaining) == len(entries):
        return False
    policy.params = {**(policy.params or {}), "bandit_candidates": remaining}
    logger.info(
        "bandit candidate removed",
        extra={"project_id": str(policy.project_id), "policy_id": str(policy.id), "candidate": candidate_model},
    )
    return True
