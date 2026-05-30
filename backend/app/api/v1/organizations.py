import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Organization
from app.schemas import OrganizationCreate, OrganizationOut

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.post("", response_model=OrganizationOut, status_code=status.HTTP_201_CREATED)
def create_organization(payload: OrganizationCreate, db: Session = Depends(get_db)) -> Organization:
    org = Organization(
        name=payload.name,
        monthly_spend_budget_usd=payload.monthly_spend_budget_usd,
    )
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


@router.get("", response_model=list[OrganizationOut])
def list_organizations(db: Session = Depends(get_db)) -> list[Organization]:
    return list(db.scalars(select(Organization).order_by(Organization.created_at.desc())))


@router.get("/{organization_id}", response_model=OrganizationOut)
def get_organization(organization_id: uuid.UUID, db: Session = Depends(get_db)) -> Organization:
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="organization not found")
    return org
