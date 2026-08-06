"""What a workspace is allowed to do, by plan tier.

A single read the dashboard uses to drive locked states and upgrade prompts. The
backend is the source of truth (the activation endpoints enforce the same tier);
this endpoint just lets the UI reflect it without guessing.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import resolve_project
from app.auth.entitlements import entitlement_state_for_project
from app.db.session import get_db
from app.models import Organization, Project, ProxyPolicy, UsageEvent
from app.proxy.routing import ARM_CONTROL, ARM_TREATMENT

router = APIRouter(tags=["entitlements"])

DIRECTIONAL_PRICED_REQUEST_THRESHOLD = 60
HOLDBACK_ARM_REQUEST_THRESHOLD = 30


def _trial_progress(db: Session, project: Project) -> dict:
    total_requests = (
        db.scalar(select(func.count()).select_from(UsageEvent).where(UsageEvent.project_id == project.id)) or 0
    )
    priced_requests = (
        db.scalar(
            select(func.count())
            .select_from(UsageEvent)
            .where(UsageEvent.project_id == project.id, UsageEvent.pricing_status == "priced")
        )
        or 0
    )
    holdback_policy_active = bool(
        db.scalar(
            select(func.count())
            .select_from(ProxyPolicy)
            .where(
                ProxyPolicy.project_id == project.id,
                ProxyPolicy.enabled.is_(True),
                ProxyPolicy.holdback_percent > 0,
            )
        )
    )
    try:
        meta = UsageEvent.event_metadata
        rows = db.execute(
            select(meta["arm"].astext.label("arm"), func.count().label("n"))
            .where(
                UsageEvent.project_id == project.id,
                UsageEvent.pricing_status == "priced",
                meta["holdback"].astext == "true",
            )
            .group_by("arm")
        ).all()
        arm_counts = {row.arm: int(row.n) for row in rows}
    except Exception:
        arm_counts = {}
    control_count = arm_counts.get(ARM_CONTROL, 0)
    treatment_count = arm_counts.get(ARM_TREATMENT, 0)
    return {
        "first_request_received": bool(total_requests),
        "priced_request_count": int(priced_requests),
        "directional_request_threshold": DIRECTIONAL_PRICED_REQUEST_THRESHOLD,
        "directional_spend_ready": int(priced_requests) >= DIRECTIONAL_PRICED_REQUEST_THRESHOLD,
        "holdback_policy_active": holdback_policy_active,
        "holdback_control_count": control_count,
        "holdback_treatment_count": treatment_count,
        "holdback_arm_threshold": HOLDBACK_ARM_REQUEST_THRESHOLD,
        "holdback_proof_ready": holdback_policy_active
        and control_count >= HOLDBACK_ARM_REQUEST_THRESHOLD
        and treatment_count >= HOLDBACK_ARM_REQUEST_THRESHOLD,
    }


@router.get("/entitlements")
def entitlements(
    project: Project = Depends(resolve_project),
    db: Session = Depends(get_db),
) -> dict:
    entitlement = entitlement_state_for_project(db, project)
    org = db.get(Organization, project.organization_id)
    performance = entitlement.plan_tier == "performance" and not entitlement.observe_only
    return {
        "plan_tier": entitlement.plan_tier,
        "subscription_status": org.subscription_status if org else None,
        "observe_only": entitlement.observe_only,
        "observe_only_reason": entitlement.reason,
        "quota": {
            "monthly_requests": entitlement.monthly_requests,
            "monthly_request_limit": entitlement.monthly_request_limit,
            "requests_remaining": entitlement.requests_remaining,
        },
        "trial": {
            "trial_ends_at": entitlement.trial_ends_at,
            "trial_expired": entitlement.trial_expired,
            "payment_method_ready": bool(org and org.payment_method_ready_at),
            "payment_method_ready_at": org.payment_method_ready_at if org else None,
        },
        "trial_progress": _trial_progress(db, project),
        "features": {
            # Behaviour-changing levers, gated to Pro (matches the backend
            # enforcement points exactly).
            "apply_recommendations": performance,
            "enable_levers": performance,
            "enable_routing": performance,
            "enable_caching": performance,
            "enable_trimming": performance,
            "use_batching": performance,
            "guardrail_automation": performance,
            "submit_batches": performance,
            # Advanced read surfaces: Free can preview, Pro gets the full view.
            "advanced_proof": performance,
            "advanced_reports": performance,
            "extended_retention": performance,
        },
    }
