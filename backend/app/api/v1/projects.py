from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.api.deps import require_org_member, require_project_member, require_user
from app.core import ratelimit
from app.core.audit import client_ip, record_audit
from app.core.config import settings
from app.db.session import get_db
from app.models import (
    ACTION_PROVIDER_KEY_CONNECTED,
    Organization,
    OrgMembership,
    Project,
    ProviderConnection,
    User,
)
from app.proxy.keys import ProviderKeyStoreUnsupported, store_provider_key_for_project
from app.proxy.provider_validation import validate_provider_key
from app.schemas import ProjectCreate, ProjectOut, ProjectProxyConfigUpdate

router = APIRouter(tags=["projects"])

VALID_PROVIDER_CONNECTIONS = {"openai", "anthropic", "gemini"}


class ProjectProviderConnectionCreate(BaseModel):
    provider: str = Field(min_length=1, max_length=64)
    api_key: str = Field(min_length=1, max_length=4096)


def _provider_connection_payload(connection: ProviderConnection) -> dict:
    return {
        "id": connection.id,
        "provider": connection.provider,
        "connection_method": connection.connection_method,
        "status": connection.status,
        "key_vaulted": connection.secret_ref is not None,
        "last_sync_at": connection.last_sync_at,
        "last_verified_at": connection.last_verified_at,
        "last_error": connection.last_error,
        "created_at": connection.created_at,
        "updated_at": connection.updated_at,
    }


def _connection_method_for_secret(secret_ref: str) -> str:
    return "local_db_encrypted" if secret_ref.startswith("localdb:") else "secrets_manager"


def _provider_connection_record(db: Session, project: Project, provider: str) -> ProviderConnection:
    connection = db.scalar(
        select(ProviderConnection).where(
            ProviderConnection.project_id == project.id,
            ProviderConnection.provider == provider,
        )
    )
    if connection is None:
        connection = ProviderConnection(
            organization_id=project.organization_id,
            project_id=project.id,
            provider=provider,
            connection_method="secrets_manager",
            status="not_connected",
        )
        db.add(connection)
        db.flush()
    return connection


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
        .options(joinedload(Project.organization))  # is_demo reads org; avoid N+1
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
    stmt = select(Project).where(Project.organization_id == org.id).order_by(Project.created_at.desc())
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


@router.post("/projects/{project_id}/connections", response_model=None)
def create_project_provider_connection(
    payload: ProjectProviderConnectionCreate,
    request: Request,
    project: Project = Depends(require_project_member),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    """Self-serve provider-key connection used by onboarding.

    The endpoint validates the upstream key, stores it only through the configured
    key-vault resolver, and returns connection metadata. It never returns the key.
    """
    provider = payload.provider.strip().lower()
    if provider not in VALID_PROVIDER_CONNECTIONS:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="unsupported provider")

    if not ratelimit.allow(f"connect:{user.id}", settings.connect_rate_limit_per_minute):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="too many connection attempts; slow down and try again shortly",
            headers={"Retry-After": "60"},
        )

    validation = validate_provider_key(provider, payload.api_key)
    if not validation.ok:
        connection = _provider_connection_record(db, project, provider)
        connection.status = "error"
        connection.last_error = validation.message
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=validation.message or "provider key validation failed",
        )

    try:
        secret_ref = store_provider_key_for_project(project.id, provider, payload.api_key)
    except ProviderKeyStoreUnsupported as exc:
        connection = _provider_connection_record(db, project, provider)
        connection.status = "manual_setup_required"
        connection.last_error = str(exc)
        db.commit()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.detail()) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except Exception as exc:
        connection = _provider_connection_record(db, project, provider)
        connection.status = "error"
        connection.last_error = "provider key store failed"
        db.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="provider key store failed") from exc

    now = datetime.now(UTC)
    connection = _provider_connection_record(db, project, provider)
    connection.connection_method = _connection_method_for_secret(secret_ref)
    connection.status = "connected"
    connection.secret_ref = secret_ref
    connection.last_sync_at = now
    connection.last_verified_at = now
    connection.last_error = None
    record_audit(
        db,
        action=ACTION_PROVIDER_KEY_CONNECTED,
        actor=user,
        organization_id=project.organization_id,
        project_id=project.id,
        target_type="provider_connection",
        target_id=provider,
        source_ip=client_ip(request),
        details={"secret_ref": secret_ref, "connection_method": connection.connection_method},
    )
    db.commit()
    db.refresh(connection)
    return _provider_connection_payload(connection)
