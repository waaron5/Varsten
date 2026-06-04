"""Inline model routing: the execution side of the cheaper-model lever.

`resolve_effective_model` runs on the proxy hot path. It is a single indexed
lookup and fails open: any error returns the requested model unchanged, so a
routing problem can never break a request, only stop a saving. (The in-VPC
north-star caches this policy in memory; a query is fine at this stage and
mirrors the existing cache lookup.)

`activate_rule` / `deactivate_rules` run on the control plane when a recommendation
is applied or dismissed.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models import Project, ProxyRoutingRule, Recommendation

logger = get_logger("varsten.proxy.routing")


def resolve_effective_model(db: Session, project_id: uuid.UUID, requested_model: str) -> str | None:
    """The candidate model an enabled rule routes this request to, or None when no
    rule applies. Fail-open: on any error, return None (forward the original)."""
    if not requested_model:
        return None
    try:
        candidate = db.scalar(
            select(ProxyRoutingRule.candidate_model).where(
                ProxyRoutingRule.project_id == project_id,
                ProxyRoutingRule.incumbent_model == requested_model,
                ProxyRoutingRule.enabled.is_(True),
            )
        )
        return candidate
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
) -> ProxyRoutingRule | None:
    """Activate (or refresh) the routing rule for an applied cheaper-model
    recommendation. Returns None when the recommendation lacks an incumbent model
    or a candidate to route to."""
    incumbent = recommendation.related_model
    if not incumbent or not candidate_model or incumbent == candidate_model:
        return None
    at = now or datetime.now(timezone.utc)
    rule = db.scalar(
        select(ProxyRoutingRule).where(
            ProxyRoutingRule.project_id == project.id,
            ProxyRoutingRule.incumbent_model == incumbent,
        )
    )
    if rule is None:
        rule = ProxyRoutingRule(
            organization_id=project.organization_id,
            project_id=project.id,
            incumbent_model=incumbent,
        )
        db.add(rule)
    rule.candidate_model = candidate_model
    rule.enabled = True
    rule.source_recommendation_id = recommendation.id
    rule.activated_at = at
    return rule


def deactivate_rules_for_recommendation(db: Session, recommendation: Recommendation) -> None:
    """Turn off any rule sourced from this recommendation (e.g. on dismiss or
    rollback), returning that route to the incumbent model."""
    db.execute(
        update(ProxyRoutingRule)
        .where(ProxyRoutingRule.source_recommendation_id == recommendation.id)
        .values(enabled=False)
    )
