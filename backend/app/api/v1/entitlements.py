"""What a workspace is allowed to do, by plan tier.

A single read the dashboard uses to drive locked states and upgrade prompts. The
backend is the source of truth (the activation endpoints enforce the same tier);
this endpoint just lets the UI reflect it without guessing.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import resolve_project
from app.auth.entitlements import entitlement_state_for_project
from app.db.session import get_db
from app.models import Project

router = APIRouter(tags=["entitlements"])


@router.get("/entitlements")
def entitlements(
    project: Project = Depends(resolve_project),
    db: Session = Depends(get_db),
) -> dict:
    entitlement = entitlement_state_for_project(db, project)
    performance = entitlement.plan_tier == "performance" and not entitlement.observe_only
    return {
        "plan_tier": entitlement.plan_tier,
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
        },
        "features": {
            # Behaviour-changing levers, gated to Performance (matches the backend
            # enforcement points exactly).
            "apply_recommendations": performance,
            "enable_levers": performance,
            "enable_routing": performance,
            "enable_caching": performance,
            "enable_trimming": performance,
            "use_batching": performance,
            "guardrail_automation": performance,
            "submit_batches": performance,
            # Advanced read surfaces: Free can preview, Performance gets the full view.
            "advanced_proof": performance,
            "advanced_reports": performance,
            "extended_retention": performance,
        },
    }
