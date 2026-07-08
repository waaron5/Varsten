"""Self-serve onboarding state.

A single read endpoint the funnel and the dashboard empty-state poll. Setup
progress is *derived* from existing records (API keys, provider connections, the
usage ledger, decision evidence) rather than stored, so it can never drift out of
sync with reality. The only persisted bit is when onboarding was completed, so it
is not re-shown.

Everything here is metadata only and tenant-scoped through resolve_project.
"""

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import resolve_project
from app.auth.entitlements import entitlement_state_for_project
from app.db.session import get_db
from app.models import (
    ApiKey,
    Organization,
    Project,
    ProviderConnection,
    RequestDecisionEvent,
    UsageEvent,
)

router = APIRouter(prefix="/onboarding", tags=["onboarding"])

# Onboarding events that are not derivable from other tables, so they are stamped
# on the org. First write wins; re-firing is a no-op.
_EVENT_COLUMNS = {
    "snippet_viewed": "integration_snippet_viewed_at",
    "dashboard_entered": "dashboard_entered_at",
}


class OnboardingEvent(BaseModel):
    event: str


OnboardingPath = Literal["sdk", "base_url", "metadata"]
OnboardingProvider = Literal["openai", "anthropic", "gemini"]


class OnboardingSelection(BaseModel):
    path: OnboardingPath
    provider: OnboardingProvider | None = None


def _metadata_quality(task_type: str | None, feature: str | None, workflow: str | None) -> dict:
    """A friendly nudge that rewards good metadata without making it mandatory."""
    if task_type:
        return {
            "level": "great",
            "message": "Great: task_type was included. Workflow-level savings analysis is unlocked.",
        }
    if feature or workflow:
        return {"level": "good", "message": "Add task_type metadata to unlock better savings recommendations."}
    return {
        "level": "none",
        "message": "Optional: add X-Varsten-Metadata (feature, workflow, task_type) to break spend down by workload.",
    }


# The three integration methods, in order of production-safety. A provider that
# ever sent SDK-marked traffic is treated as SDK even if a stray base-URL request
# also landed, because the SDK is the fail-open path the customer should keep.
INTEGRATION_SDK = "sdk"  # fail-open SDK wrapper (X-Varsten-Client marker present)
INTEGRATION_BASE_URL = "base_url"  # inline base-URL proxy, no automatic fallback
INTEGRATION_METADATA = "metadata"  # async POST /usage-events, nothing inline
INTEGRATION_NONE = "none"

_INTEGRATION_PROVIDERS = ("openai", "anthropic", "gemini")
_INTEGRATION_PATHS = (INTEGRATION_SDK, INTEGRATION_BASE_URL, INTEGRATION_METADATA)


def _provider_label(provider: str) -> str:
    return {"openai": "OpenAI", "anthropic": "Anthropic", "gemini": "Gemini"}.get(provider, provider)


def _first_request(db: Session, project: Project) -> dict:
    count = db.scalar(select(func.count()).select_from(UsageEvent).where(UsageEvent.project_id == project.id)) or 0
    event = db.scalar(
        select(UsageEvent).where(UsageEvent.project_id == project.id).order_by(UsageEvent.received_at.desc()).limit(1)
    )
    if event is None:
        return {
            "seen": False,
            "request_count": 0,
            "source": None,
            "metadata_quality": _metadata_quality(None, None, None),
        }

    decision = db.scalar(select(RequestDecisionEvent).where(RequestDecisionEvent.usage_event_id == event.id).limit(1))
    meta = event.event_metadata or {}
    task_type = meta.get("task_type") or (decision.task_type if decision else None)
    return {
        "seen": True,
        "request_count": int(count),
        "source": event.source,
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


def _integration(db: Session, project: Project, connected_providers: set[str]) -> dict:
    """Detected integration method per provider, from real traffic — never stored.

    Mirrors the dashboard's fallback-coverage detection: SDK traffic carries the
    ``X-Varsten-Client`` marker (recorded in event metadata), proxy traffic has
    ``source='proxy'``, async ingestion has ``source='ingest'``. This drives the
    onboarding nudge that moves base-URL traffic onto the fail-open SDK before it
    goes to production, and lets the funnel confirm the chosen path is live."""
    try:
        seen = {
            row.provider: row
            for row in db.execute(
                select(
                    UsageEvent.provider,
                    func.max(UsageEvent.event_metadata["sdk_client"].astext).label("sdk_client"),
                    func.bool_or(UsageEvent.source == "proxy").label("any_proxy"),
                    func.bool_or(UsageEvent.source == "ingest").label("any_ingest"),
                )
                .where(UsageEvent.project_id == project.id)
                .group_by(UsageEvent.provider)
            ).all()
        }
    except Exception:
        seen = {}

    providers: list[dict] = []
    for provider in _INTEGRATION_PROVIDERS:
        row = seen.get(provider)
        sdk_client = row.sdk_client if row else None
        if sdk_client is not None:
            method = INTEGRATION_SDK
        elif row and row.any_proxy:
            method = INTEGRATION_BASE_URL
        elif row and row.any_ingest:
            method = INTEGRATION_METADATA
        else:
            method = INTEGRATION_NONE
        providers.append(
            {
                "provider": provider,
                "method": method,
                "sdk_client": sdk_client,
                "key_configured": provider in connected_providers,
            }
        )

    any_sdk = any(p["method"] == INTEGRATION_SDK for p in providers)
    # The nudge: a provider running inline base-URL with no fail-open SDK anywhere.
    base_url_without_sdk = any(p["method"] == INTEGRATION_BASE_URL for p in providers) and not any_sdk
    return {
        "providers": providers,
        "any_sdk": any_sdk,
        "base_url_without_sdk": base_url_without_sdk,
    }


def _observed_path(integration: dict) -> str | None:
    methods = {p["method"] for p in integration["providers"]}
    if INTEGRATION_SDK in methods:
        return INTEGRATION_SDK
    if INTEGRATION_BASE_URL in methods:
        return INTEGRATION_BASE_URL
    if INTEGRATION_METADATA in methods:
        return INTEGRATION_METADATA
    return None


def _selected_path(org: Organization | None, integration: dict, observe_only: bool) -> tuple[str, bool]:
    saved = org.onboarding_selected_path if org else None
    if saved in _INTEGRATION_PATHS:
        return saved, True
    observed = _observed_path(integration)
    if observed is not None:
        return observed, False
    return (INTEGRATION_BASE_URL if observe_only else INTEGRATION_SDK), False


def _selected_provider(
    org: Organization | None,
    selected_path: str,
    integration: dict,
    connected_providers: set[str],
) -> str | None:
    if selected_path == INTEGRATION_METADATA:
        return None
    saved = org.onboarding_selected_provider if org else None
    if saved in _INTEGRATION_PROVIDERS:
        return saved
    for provider in integration["providers"]:
        if provider["method"] == selected_path:
            return provider["provider"]
    connected = sorted(p for p in connected_providers if p in _INTEGRATION_PROVIDERS)
    if connected:
        return connected[0]
    return "openai"


def _observed_method_for_selection(integration: dict, selected_path: str, selected_provider: str | None) -> str | None:
    if selected_path == INTEGRATION_METADATA:
        for provider in integration["providers"]:
            if provider["method"] == INTEGRATION_METADATA:
                return INTEGRATION_METADATA
        return None
    for provider in integration["providers"]:
        if provider["provider"] == selected_provider:
            method = provider["method"]
            return None if method == INTEGRATION_NONE else method
    return None


def _missing_steps(
    *,
    has_api_key: bool,
    selected_path: str,
    selected_provider: str | None,
    selected_provider_connected: bool,
    method_verified: bool,
    verified_method: str | None,
) -> list[dict]:
    missing: list[dict] = []
    if not has_api_key:
        missing.append({"key": "has_api_key", "label": "Create a Varsten API key"})
    if selected_path != INTEGRATION_METADATA:
        if selected_provider is None:
            missing.append({"key": "selected_provider", "label": "Choose a provider"})
        elif not selected_provider_connected:
            missing.append(
                {
                    "key": "has_provider_connection",
                    "label": f"Connect {_provider_label(selected_provider)} provider key",
                }
            )
    if not method_verified:
        if verified_method is not None:
            label = "Send traffic through the selected integration method"
        else:
            label = "Send a usage record" if selected_path == INTEGRATION_METADATA else "Send a verified first request"
        missing.append({"key": "first_request", "label": label})
    return missing


def _verification_status(verified_method: str | None, selected_path: str) -> str:
    if verified_method == selected_path:
        return "verified"
    if verified_method is not None:
        return "path_mismatch"
    return "waiting"


def _onboarding_state(project: Project, db: Session) -> dict:
    org = db.get(Organization, project.organization_id)
    entitlement = entitlement_state_for_project(db, project)

    active_keys = (
        db.scalar(
            select(func.count()).select_from(ApiKey).where(ApiKey.project_id == project.id, ApiKey.revoked_at.is_(None))
        )
        or 0
    )

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
    connected_providers = {c.provider for c in connections if c.status == "connected"}

    first_request = _first_request(db, project)
    integration = _integration(db, project, connected_providers)

    has_api_key = active_keys > 0
    snippet_viewed = bool(org and org.integration_snippet_viewed_at)
    dashboard_entered = bool(org and org.dashboard_entered_at)
    selected_path, selection_saved = _selected_path(org, integration, entitlement.observe_only)
    selected_provider = _selected_provider(org, selected_path, integration, connected_providers)
    selected_provider_connected = bool(selected_provider and selected_provider in connected_providers)
    verified_method = _observed_method_for_selection(integration, selected_path, selected_provider)
    method_verified = verified_method == selected_path
    missing_steps = _missing_steps(
        has_api_key=has_api_key,
        selected_path=selected_path,
        selected_provider=selected_provider,
        selected_provider_connected=selected_provider_connected,
        method_verified=method_verified,
        verified_method=verified_method,
    )
    can_complete = not missing_steps

    # The backend-record-driven checklist. Each item is a fact, not UI state, and
    # the provider step exists only for inline paths.
    checklist = [
        {"key": "selected_path", "complete": selection_saved},
        {"key": "has_api_key", "complete": has_api_key},
        {"key": "integration_snippet_viewed", "complete": snippet_viewed},
    ]
    if selected_path != INTEGRATION_METADATA:
        checklist.insert(2, {"key": "has_provider_connection", "complete": selected_provider_connected})
    checklist.extend(
        [
            {"key": "first_request", "complete": method_verified},
            {"key": "dashboard_entered", "complete": dashboard_entered},
        ]
    )

    return {
        "project_id": str(project.id),
        "project_name": project.name,
        "plan_tier": entitlement.plan_tier,
        "observe_only": entitlement.observe_only,
        "onboarding_completed_at": org.onboarding_completed_at if org else None,
        "has_project": True,
        "has_api_key": has_api_key,
        "has_provider_connection": has_provider,
        "integration_snippet_viewed": snippet_viewed,
        "dashboard_entered": dashboard_entered,
        "provider_connections": provider_connections,
        "first_request": first_request,
        "integration": integration,
        "selected_path": selected_path,
        "selection_saved": selection_saved,
        "selected_provider": selected_provider,
        "verified_method": verified_method,
        "verification_status": _verification_status(verified_method, selected_path),
        "can_complete": can_complete,
        "missing_steps": missing_steps,
        "checklist": checklist,
    }


@router.get("/status")
def onboarding_status(
    project: Project = Depends(resolve_project),
    db: Session = Depends(get_db),
) -> dict:
    return _onboarding_state(project, db)


@router.post("/selection")
def onboarding_selection(
    payload: OnboardingSelection,
    project: Project = Depends(resolve_project),
    db: Session = Depends(get_db),
) -> dict:
    org = db.get(Organization, project.organization_id)
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="organization not found")

    provider = None if payload.path == INTEGRATION_METADATA else payload.provider
    if (
        provider is None
        and payload.path != INTEGRATION_METADATA
        and org.onboarding_selected_provider in _INTEGRATION_PROVIDERS
    ):
        provider = org.onboarding_selected_provider

    changed = org.onboarding_selected_path != payload.path or org.onboarding_selected_provider != provider
    org.onboarding_selected_path = payload.path
    org.onboarding_selected_provider = provider
    if changed:
        org.integration_snippet_viewed_at = None
        org.onboarding_completed_at = None
    db.commit()
    return {
        "selected_path": org.onboarding_selected_path,
        "selected_provider": org.onboarding_selected_provider,
    }


@router.post("/event")
def onboarding_event(
    payload: OnboardingEvent,
    project: Project = Depends(resolve_project),
    db: Session = Depends(get_db),
) -> dict:
    """Stamp a non-derivable onboarding event (snippet viewed, dashboard entered).
    First write wins so the timestamp reflects when the step first happened."""
    column = _EVENT_COLUMNS.get(payload.event)
    if column is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"event must be one of {sorted(_EVENT_COLUMNS)}",
        )
    org = db.get(Organization, project.organization_id)
    if org is not None and getattr(org, column) is None:
        setattr(org, column, datetime.now(UTC))
        db.commit()
    return {"event": payload.event, "recorded_at": getattr(org, column) if org else None}


@router.post("/complete")
def onboarding_complete(
    project: Project = Depends(resolve_project),
    db: Session = Depends(get_db),
) -> dict:
    state = _onboarding_state(project, db)
    if not state["can_complete"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "onboarding_incomplete",
                "message": "Onboarding cannot be completed until setup is verified.",
                "missing_steps": state["missing_steps"],
            },
        )
    org = db.get(Organization, project.organization_id)
    if org is not None and org.onboarding_completed_at is None:
        org.onboarding_completed_at = datetime.now(UTC)
        db.commit()
    return {"onboarding_completed_at": org.onboarding_completed_at if org else None}
