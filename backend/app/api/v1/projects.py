from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_org_member, require_project_member, require_user
from app.db.session import get_db
from app.models import Organization, OrgMembership, Project, User
from app.schemas import ProjectCreate, ProjectOut, ProjectProxyConfigUpdate

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
    payload: ProjectCreate,
    org: Organization = Depends(require_org_member),
    db: Session = Depends(get_db),
) -> Project:
    project = Project(organization_id=org.id, name=payload.name)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get(
    "/organizations/{organization_id}/projects",
    response_model=list[ProjectOut],
)
def list_projects(
    org: Organization = Depends(require_org_member),
    db: Session = Depends(get_db),
) -> list[Project]:
    stmt = (
        select(Project)
        .where(Project.organization_id == org.id)
        .order_by(Project.created_at.desc())
    )
    return list(db.scalars(stmt))


@router.get("/projects/{project_id}", response_model=ProjectOut)
def get_project(project: Project = Depends(require_project_member)) -> Project:
    return project


@router.patch("/projects/{project_id}/proxy-config", response_model=ProjectOut)
def update_proxy_config(
    payload: ProjectProxyConfigUpdate,
    project: Project = Depends(require_project_member),
    db: Session = Depends(get_db),
) -> Project:
    """Flip the per-project proxy kill switch. bypass_enabled=true forwards the
    project's traffic straight to OpenAI with no Varsten optimization."""
    project.proxy_bypass_enabled = payload.bypass_enabled
    db.commit()
    db.refresh(project)
    return project
