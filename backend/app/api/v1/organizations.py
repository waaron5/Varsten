from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_org_member, require_user
from app.db.session import get_db
from app.models import Organization, OrgMembership, User
from app.schemas import OrganizationCreate, OrganizationOut

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.post("", response_model=OrganizationOut, status_code=status.HTTP_201_CREATED)
def create_organization(
    payload: OrganizationCreate,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> Organization:
    # The creator becomes the owner. Without this an org would have no members and
    # be unreachable through every membership-scoped read.
    org = Organization(
        name=payload.name,
        monthly_spend_budget_usd=payload.monthly_spend_budget_usd,
    )
    db.add(org)
    db.flush()
    db.add(OrgMembership(organization_id=org.id, user_id=user.id, role="owner"))
    db.commit()
    db.refresh(org)
    return org


@router.get("", response_model=list[OrganizationOut])
def list_organizations(
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> list[Organization]:
    """Only the organizations the signed-in user belongs to."""
    stmt = (
        select(Organization)
        .join(OrgMembership, OrgMembership.organization_id == Organization.id)
        .where(OrgMembership.user_id == user.id)
        .order_by(Organization.created_at.desc())
    )
    return list(db.scalars(stmt))


@router.get("/{organization_id}", response_model=OrganizationOut)
def get_organization(org: Organization = Depends(require_org_member)) -> Organization:
    return org
