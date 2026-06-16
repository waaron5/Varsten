import re
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import Numeric, cast, func, select
from sqlalchemy.orm import Session

from app.api.deps import require_user
from app.auth.entitlements import invalidate_plan_tier
from app.core.audit import client_ip, record_audit
from app.core.config import settings
from app.core.security import generate_api_key
from app.db.session import get_db
from app.models import ACTION_PLAN_CHANGED, PLAN_TIERS, ApiKey, Organization, OrgMembership, Project, UsageEvent, User
from app.schemas import OperatorProvisionRequest, OperatorProvisionResponse, OperatorValidationSummary

router = APIRouter(prefix="/operator", tags=["operator"])

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _operator_user(user: User = Depends(require_user)) -> User:
    allowed = {email.lower() for email in settings.operator_admin_emails}
    if not allowed or user.email.lower() not in allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="operator access required")
    return user


def _clean_email(email: str) -> str:
    cleaned = email.strip().lower()
    if not EMAIL_RE.match(cleaned):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid customer email")
    return cleaned


def _ensure_membership(db: Session, user: User, organization: Organization, role: str = "owner") -> None:
    existing = db.scalar(
        select(OrgMembership.id).where(
            OrgMembership.user_id == user.id,
            OrgMembership.organization_id == organization.id,
        )
    )
    if existing is None:
        db.add(OrgMembership(user_id=user.id, organization_id=organization.id, role=role))


@router.post("/provision", response_model=OperatorProvisionResponse, status_code=status.HTTP_201_CREATED)
def provision_customer(
    payload: OperatorProvisionRequest,
    _operator: User = Depends(_operator_user),
    db: Session = Depends(get_db),
) -> OperatorProvisionResponse:
    customer_email = _clean_email(payload.customer_email)
    user = db.scalar(select(User).where(User.email == customer_email))
    if user is None:
        user = User(email=customer_email, name=payload.full_name.strip(), auth_provider_subject=None)
        db.add(user)
        db.flush()
    else:
        user.name = payload.full_name.strip()

    org = Organization(name=payload.organization_name.strip())
    db.add(org)
    db.flush()
    _ensure_membership(db, user, org)

    project = Project(organization_id=org.id, name=payload.project_name.strip())
    db.add(project)
    db.flush()

    plaintext, prefix, key_hash = generate_api_key()
    api_key = ApiKey(
        project_id=project.id,
        name=payload.api_key_name.strip(),
        key_prefix=prefix,
        key_hash=key_hash,
    )
    db.add(api_key)
    db.commit()
    db.refresh(api_key)

    return OperatorProvisionResponse(
        user_id=user.id,
        organization_id=org.id,
        project_id=project.id,
        api_key_id=api_key.id,
        api_key_prefix=api_key.key_prefix,
        plaintext_api_key=plaintext,
    )


def _money(value: Decimal | None) -> str:
    if value is None:
        return "not available yet"
    return f"${value.quantize(Decimal('0.0001'))}"


def _validation_draft(
    project: Project,
    request_count: int,
    p95_latency_ms: int | None,
    saved_usd: Decimal | None,
    fail_open_status: str,
) -> str:
    if request_count == 0:
        return (
            f"Hey [Name], just checking the logs for {project.name}. I am not seeing routed traffic in "
            "the last 24 hours yet. Want me to help you push one staging request through so we can verify "
            "the integration before production?"
        )

    latency = f"{p95_latency_ms}ms" if p95_latency_ms is not None else "not captured yet"
    return (
        f"Hey [Name], just checking the logs. You successfully routed {request_count:,} requests through "
        f"the proxy in the last 24 hours. Your p95 latency added was {latency}, and you've already avoided "
        f"{_money(saved_usd)} in API costs. The fail-open status is {fail_open_status}. Let me know when "
        "you are ready to push this from staging to production."
    )


@router.get("/projects/{project_id}/validation-summary", response_model=OperatorValidationSummary)
def validation_summary(
    project_id: uuid.UUID,
    hours: int = Query(default=24, ge=1, le=168),
    _operator: User = Depends(_operator_user),
    db: Session = Depends(get_db),
) -> OperatorValidationSummary:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project not found")

    now = datetime.now(UTC)
    start = now - timedelta(hours=hours)
    saved = cast(UsageEvent.event_metadata["saved_usd"].astext, Numeric)
    row = db.execute(
        select(
            func.count(UsageEvent.id).label("request_count"),
            func.percentile_cont(0.95).within_group(UsageEvent.latency_ms).label("p95_latency_ms"),
            func.sum(saved).label("saved_usd"),
        ).where(
            UsageEvent.project_id == project.id,
            UsageEvent.received_at >= start,
            UsageEvent.received_at <= now,
        )
    ).one()

    request_count = int(row.request_count or 0)
    p95_latency_ms = int(row.p95_latency_ms) if row.p95_latency_ms is not None else None
    saved_usd = row.saved_usd
    fail_open_status = "bypass enabled" if project.proxy_bypass_enabled or settings.proxy_kill_switch else "not tripped"

    return OperatorValidationSummary(
        project_id=project.id,
        organization_id=project.organization_id,
        project_name=project.name,
        window_hours=hours,
        window_start=start,
        window_end=now,
        request_count=request_count,
        p95_latency_ms=p95_latency_ms,
        saved_usd=saved_usd,
        fail_open_status=fail_open_status,
        follow_up_draft=_validation_draft(project, request_count, p95_latency_ms, saved_usd, fail_open_status),
    )


class PlanUpdate(BaseModel):
    plan_tier: str


@router.post("/organizations/{organization_id}/plan")
def set_organization_plan(
    organization_id: uuid.UUID,
    payload: PlanUpdate,
    request: Request,
    operator: User = Depends(_operator_user),
    db: Session = Depends(get_db),
) -> dict:
    """Operator-only plan switch for testing Free vs Performance. Gated by
    operator_admin_emails; there is deliberately no public/self-serve plan switch."""
    tier = payload.plan_tier.strip().lower()
    if tier not in PLAN_TIERS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"plan_tier must be one of {list(PLAN_TIERS)}",
        )
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="organization not found")
    previous = org.plan_tier
    org.plan_tier = tier
    # A plan change moves money (gain-share) and unlocks behaviour-changing levers,
    # so it is audited: who changed which org from which tier to which, and from where.
    record_audit(
        db,
        action=ACTION_PLAN_CHANGED,
        actor=operator,
        organization_id=org.id,
        target_type="organization",
        target_id=str(org.id),
        source_ip=client_ip(request),
        before={"plan_tier": previous},
        after={"plan_tier": tier},
    )
    db.commit()
    # Take effect immediately on the proxy's cached tier lookup.
    invalidate_plan_tier(organization_id)
    return {"organization_id": str(org.id), "plan_tier": org.plan_tier}
