from datetime import datetime, timezone

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_api_key_member, require_project_member
from app.core.security import generate_api_key
from app.db.session import get_db
from app.models import ApiKey, Project
from app.schemas import ApiKeyCreate, ApiKeyCreated, ApiKeyOut

router = APIRouter(tags=["api-keys"])


@router.post(
    "/projects/{project_id}/api-keys",
    response_model=ApiKeyCreated,
    status_code=status.HTTP_201_CREATED,
)
def create_api_key(
    payload: ApiKeyCreate,
    project: Project = Depends(require_project_member),
    db: Session = Depends(get_db),
) -> ApiKeyCreated:
    plaintext, prefix, key_hash = generate_api_key()
    api_key = ApiKey(
        project_id=project.id,
        name=payload.name,
        key_prefix=prefix,
        key_hash=key_hash,
    )
    db.add(api_key)
    db.commit()
    db.refresh(api_key)

    return ApiKeyCreated(
        id=api_key.id,
        project_id=api_key.project_id,
        name=api_key.name,
        key_prefix=api_key.key_prefix,
        last_used_at=api_key.last_used_at,
        revoked_at=api_key.revoked_at,
        created_at=api_key.created_at,
        plaintext_key=plaintext,
    )


@router.get(
    "/projects/{project_id}/api-keys",
    response_model=list[ApiKeyOut],
)
def list_api_keys(
    project: Project = Depends(require_project_member),
    db: Session = Depends(get_db),
) -> list[ApiKey]:
    stmt = (
        select(ApiKey)
        .where(ApiKey.project_id == project.id)
        .order_by(ApiKey.created_at.desc())
    )
    return list(db.scalars(stmt))


@router.delete(
    "/api-keys/{api_key_id}",
    response_model=ApiKeyOut,
)
def revoke_api_key(
    api_key: ApiKey = Depends(require_api_key_member),
    db: Session = Depends(get_db),
) -> ApiKey:
    if api_key.revoked_at is None:
        api_key.revoked_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(api_key)
    return api_key
