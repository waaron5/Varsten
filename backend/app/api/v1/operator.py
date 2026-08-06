import re
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import Numeric, cast, func, select
from sqlalchemy.orm import Session

from app import billing
from app.api.deps import require_user
from app.auth.entitlements import invalidate_plan_tier
from app.core.audit import client_ip, record_audit
from app.core.config import settings
from app.core.security import generate_api_key
from app.db.session import get_db
from app.models import (
    ACTION_BILLING_UPDATED,
    ACTION_INVOICE_GENERATED,
    ACTION_PLAN_CHANGED,
    MAX_GAIN_SHARE_PERCENT,
    PLAN_TIERS,
    SUBSCRIPTION_STATUSES,
    ApiKey,
    Organization,
    OrgMembership,
    Project,
    UsageEvent,
    User,
)
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
    """Operator-only plan switch for testing Free vs Pro. Gated by
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
    org.plan_effective_at = datetime.now(UTC)
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


class BillingConfigUpdate(BaseModel):
    gain_share_percent: Decimal | None = Field(default=None, ge=0, le=MAX_GAIN_SHARE_PERCENT)
    monthly_fee_floor_usd: Decimal | None = Field(default=None, ge=0)
    subscription_status: str | None = None
    trial_ends_at: datetime | None = None


@router.post("/organizations/{organization_id}/billing")
def set_billing_config(
    organization_id: uuid.UUID,
    payload: BillingConfigUpdate,
    request: Request,
    operator: User = Depends(_operator_user),
    db: Session = Depends(get_db),
) -> dict:
    """Operator-only gain-share + subscription config. Manual today; a Stripe
    webhook drives subscription_status later. Audited."""
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="organization not found")
    if payload.subscription_status is not None and payload.subscription_status not in SUBSCRIPTION_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"subscription_status must be one of {list(SUBSCRIPTION_STATUSES)}",
        )
    before = {
        "gain_share_percent": str(org.gain_share_percent),
        "monthly_fee_floor_usd": str(org.monthly_fee_floor_usd),
        "subscription_status": org.subscription_status,
    }
    if payload.gain_share_percent is not None:
        org.gain_share_percent = payload.gain_share_percent
    if payload.monthly_fee_floor_usd is not None:
        org.monthly_fee_floor_usd = payload.monthly_fee_floor_usd
    if payload.subscription_status is not None:
        org.subscription_status = payload.subscription_status
    if payload.trial_ends_at is not None:
        org.trial_ends_at = payload.trial_ends_at
    record_audit(
        db,
        action=ACTION_BILLING_UPDATED,
        actor=operator,
        organization_id=org.id,
        target_type="organization",
        target_id=str(org.id),
        source_ip=client_ip(request),
        before=before,
        after={
            "gain_share_percent": str(org.gain_share_percent),
            "monthly_fee_floor_usd": str(org.monthly_fee_floor_usd),
            "subscription_status": org.subscription_status,
        },
    )
    db.commit()
    return {
        "organization_id": str(org.id),
        "gain_share_percent": org.gain_share_percent,
        "monthly_fee_floor_usd": org.monthly_fee_floor_usd,
        "subscription_status": org.subscription_status,
        "trial_ends_at": org.trial_ends_at,
    }


class InvoiceGenerateRequest(BaseModel):
    # Default: the last fully-elapsed month. Override for backfills.
    period_start: datetime | None = None
    period_end: datetime | None = None


@router.post("/organizations/{organization_id}/invoices", status_code=status.HTTP_201_CREATED)
def generate_org_invoice(
    organization_id: uuid.UUID,
    payload: InvoiceGenerateRequest,
    request: Request,
    operator: User = Depends(_operator_user),
    db: Session = Depends(get_db),
) -> dict:
    """Operator-only: generate (or refresh) the draft gain-share invoice for a
    period from VERIFIED savings. No charge is made; this is the manual-invoicing
    record a human sends. Audited."""
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="organization not found")
    if (payload.period_start is None) != (payload.period_end is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="provide both period_start and period_end, or neither",
        )
    if payload.period_start is not None and payload.period_end is not None:
        start, end = payload.period_start, payload.period_end
    else:
        start, end = billing.previous_month_period()
    invoice = billing.generate_invoice(db, org, start, end)
    record_audit(
        db,
        action=ACTION_INVOICE_GENERATED,
        actor=operator,
        organization_id=org.id,
        target_type="invoice",
        target_id=str(invoice.id),
        source_ip=client_ip(request),
        after={
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "verified_savings_usd": str(invoice.verified_savings_usd),
            "fee_usd": str(invoice.fee_usd),
        },
    )
    db.commit()
    return _invoice_payload(invoice)


def _invoice_payload(invoice) -> dict:
    return {
        "id": str(invoice.id),
        "organization_id": str(invoice.organization_id),
        "period_start": invoice.period_start,
        "period_end": invoice.period_end,
        "verified_savings_usd": invoice.verified_savings_usd,
        "gain_share_percent": invoice.gain_share_percent,
        "monthly_fee_floor_usd": invoice.monthly_fee_floor_usd,
        "fee_usd": invoice.fee_usd,
        "net_savings_usd": invoice.net_savings_usd,
        "currency": invoice.currency,
        "status": invoice.status,
        "notes": invoice.notes,
        "created_at": invoice.created_at,
    }
