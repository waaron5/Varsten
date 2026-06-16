"""What a workspace is allowed to do, by plan tier.

A single read the dashboard uses to drive locked states and upgrade prompts. The
backend is the source of truth (the activation endpoints enforce the same tier);
this endpoint just lets the UI reflect it without guessing.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import resolve_project
from app.auth.entitlements import is_performance
from app.db.session import get_db
from app.models import Project

router = APIRouter(tags=["entitlements"])


@router.get("/entitlements")
def entitlements(
    project: Project = Depends(resolve_project),
    db: Session = Depends(get_db),
) -> dict:
    performance = is_performance(db, project)
    return {
        "plan_tier": "performance" if performance else "free",
        "observe_only": not performance,
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
