"""Self-serve onboarding state.

A single read endpoint the funnel and the dashboard empty-state poll. Setup
progress is *derived* from existing records (API keys, provider connections, the
usage ledger, decision evidence) rather than stored, so it can never drift out of
sync with reality. The only persisted bit is when onboarding was completed, so it
is not re-shown.

Everything here is metadata only and tenant-scoped through resolve_project.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import resolve_project
from app.db.session import get_db
from app.models import (
    PLAN_PERFORMANCE,
    ApiKey,
    Organization,
    Project,
    ProviderConnection,
    RequestDecisionEvent,
    UsageEvent,
)

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


def _metadata_quality(task_type: str | None, feature: str | None, workflow: str | None) -> dict:
    """A friendly nudge that rewards good metadata without making it mandatory."""
    if task_type:
        return {"level": "great", "message": "Great: task_type was included. Workflow-level savings analysis is unlocked."}
    if feature or workflow:
        return {"level": "good", "message": "Add task_type metadata to unlock better savings recommendations."}
    return {"level": "none", "message": "Optional: add X-Varsten-Metadata (feature, workflow, task_type) to break spend down by workload."}


def _first_request(db: Session, project: Project) -> dict:
    count = db.scalar(
        select(func.count()).select_from(UsageEvent).where(UsageEvent.project_id == project.id)
    ) or 0
    event = db.scalar(
        select(UsageEvent).where(UsageEvent.project_id == project.id).order_by(UsageEvent.received_at.desc()).limit(1)
    )
    if event is None:
        return {"seen": False, "request_count": 0, "metadata_quality": _metadata_quality(None, None, None)}

    decision = db.scalar(
        select(RequestDecisionEvent)
        .where(RequestDecisionEvent.usage_event_id == event.id)
        .limit(1)
    )
    meta = event.event_metadata or {}
    task_type = meta.get("task_type") or (decision.task_type if decision else None)
    return {
        "seen": True,
        "request_count": int(count),
        "request_id": decision.request_id if decision else None,
        "provider": event.provider,
        "model": event.model,
        "cost_usd": str(event.cost_usd) if event.cost_usd is not None else None,
        "cost_source": event.cost_source,
        "pricing_status": event.pricing_status,
        "input_tokens": event.input_tokens,
        "output_tokens": event.output_tokens,
        "latency_ms": event.latency_ms,
        "environment": event.environment,
        "feature": event.feature,
        "workflow": event.workflow,
        "task_type": task_type,
        "occurred_at": event.received_at,
        "metadata_quality": _metadata_quality(task_type, event.feature, event.workflow),
    }


@router.get("/status")
def onboarding_status(
    project: Project = Depends(resolve_project),
    db: Session = Depends(get_db),
) -> dict:
    org = db.get(Organization, project.organization_id)
    plan_tier = org.plan_tier if org else "free"

    active_keys = db.scalar(
        select(func.count())
        .select_from(ApiKey)
        .where(ApiKey.project_id == project.id, ApiKey.revoked_at.is_(None))
    ) or 0

    connections = list(
        db.scalars(
            select(ProviderConnection)
            .where(ProviderConnection.project_id == project.id)
            .order_by(ProviderConnection.provider.asc())
        )
    )
    provider_connections = [
        {
            "provider": c.provider,
            "status": c.status,
            "last_verified_at": c.last_verified_at,
            "last_error": c.last_error,
        }
        for c in connections
    ]
    has_provider = any(c.status == "connected" for c in connections)

    first_request = _first_request(db, project)

    return {
        "project_id": str(project.id),
        "project_name": project.name,
        "plan_tier": plan_tier,
        "observe_only": plan_tier != PLAN_PERFORMANCE,
        "onboarding_completed_at": org.onboarding_completed_at if org else None,
        "has_project": True,
        "has_api_key": active_keys > 0,
        "has_provider_connection": has_provider,
        "provider_connections": provider_connections,
        "first_request": first_request,
    }


@router.post("/complete")
def onboarding_complete(
    project: Project = Depends(resolve_project),
    db: Session = Depends(get_db),
) -> dict:
    org = db.get(Organization, project.organization_id)
    if org is not None and org.onboarding_completed_at is None:
        org.onboarding_completed_at = datetime.now(UTC)
        db.commit()
    return {"onboarding_completed_at": org.onboarding_completed_at if org else None}
