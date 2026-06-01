import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_user
from app.db.session import get_db
from app.models import Organization, OrgMembership, Project, User
from app.schemas import ProjectCreate, ProjectOut

router = APIRouter(tags=["projects"])


@router.get("/projects", response_model=list[ProjectOut])
def list_my_projects(
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> list[Project]:
    """Projects across every organization the signed-in user belongs to."""
    stmt = (
        select(Project)
        .join(OrgMembership, OrgMembership.organization_id == Project.organization_id)
        .where(OrgMembership.user_id == user.id)
        .order_by(Project.created_at.desc())
    )
    return list(db.scalars(stmt))


@router.post(
    "/organizations/{organization_id}/projects",
    response_model=ProjectOut,
    status_code=status.HTTP_201_CREATED,
)
def create_project(
    organization_id: uuid.UUID,
    payload: ProjectCreate,
    db: Session = Depends(get_db),
) -> Project:
    if db.get(Organization, organization_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="organization not found")
    project = Project(organization_id=organization_id, name=payload.name)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get(
    "/organizations/{organization_id}/projects",
    response_model=list[ProjectOut],
)
def list_projects(
    organization_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> list[Project]:
    if db.get(Organization, organization_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="organization not found")
    stmt = (
        select(Project)
        .where(Project.organization_id == organization_id)
        .order_by(Project.created_at.desc())
    )
    return list(db.scalars(stmt))


@router.get("/projects/{project_id}", response_model=ProjectOut)
def get_project(project_id: uuid.UUID, db: Session = Depends(get_db)) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project not found")
    return project
