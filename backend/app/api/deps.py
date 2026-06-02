import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.auth0 import Auth0NotConfigured, verify_access_token
from app.core.security import hash_api_key
from app.db.session import get_db
from app.models import ApiKey, OrgMembership, Project, User

bearer_scheme = HTTPBearer(auto_error=False)

# Avoid an UPDATE on the api_keys row for every ingested event. Under load that
# row-level write contention would cap throughput. Refresh last_used_at at most
# once per interval instead.
LAST_USED_REFRESH = timedelta(seconds=60)

# Plaintext API keys carry this prefix, which lets us tell an ingestion key from
# an Auth0 session JWT on the same Authorization header.
API_KEY_PREFIX = "vk_"

_UNAUTHENTICATED = {"WWW-Authenticate": "Bearer"}


@dataclass(frozen=True)
class ApiKeyContext:
    project: Project
    api_key: ApiKey


def _bearer_token(credentials: HTTPAuthorizationCredentials | None) -> str:
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing credentials",
            headers=_UNAUTHENTICATED,
        )
    return credentials.credentials


# --- API key auth (ingestion + backward-compatible reads) ---------------------


def _api_key_context(token: str, db: Session) -> ApiKeyContext:
    key_hash = hash_api_key(token)
    api_key = db.scalar(select(ApiKey).where(ApiKey.key_hash == key_hash))
    if api_key is None or api_key.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid api key",
            headers=_UNAUTHENTICATED,
        )

    now = datetime.now(timezone.utc)
    if api_key.last_used_at is None or now - api_key.last_used_at > LAST_USED_REFRESH:
        api_key.last_used_at = now
        db.commit()

    project = db.get(Project, api_key.project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid api key",
            headers=_UNAUTHENTICATED,
        )
    return ApiKeyContext(project=project, api_key=api_key)


def require_api_key(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> Project:
    """Resolve the project for a Bearer API key (ingestion path)."""
    token = _bearer_token(credentials)
    if not token.startswith(API_KEY_PREFIX):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="expected an api key",
            headers=_UNAUTHENTICATED,
        )
    return _api_key_context(token, db).project


def require_api_key_context(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> ApiKeyContext:
    """Resolve the project and API key for a Bearer API key."""
    token = _bearer_token(credentials)
    if not token.startswith(API_KEY_PREFIX):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="expected an api key",
            headers=_UNAUTHENTICATED,
        )
    return _api_key_context(token, db)


# --- Auth0 session auth (dashboard) -------------------------------------------


def _claims_from_token(token: str) -> dict:
    try:
        return verify_access_token(token)
    except Auth0NotConfigured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="auth is not configured",
        )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid token",
            headers=_UNAUTHENTICATED,
        )


def get_token_claims(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    """Validated Auth0 claims. Used by /auth/sync before a user row exists."""
    return _claims_from_token(_bearer_token(credentials))


def _user_from_claims(claims: dict, db: Session) -> User:
    sub = claims.get("sub")
    user = db.scalar(select(User).where(User.auth_provider_subject == sub))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="user not provisioned; call POST /v1/auth/sync first",
            headers=_UNAUTHENTICATED,
        )
    return user


def require_user(
    claims: dict = Depends(get_token_claims),
    db: Session = Depends(get_db),
) -> User:
    """The signed-in user, resolved from the Auth0 subject."""
    return _user_from_claims(claims, db)


def _assert_member(user: User, organization_id: uuid.UUID, db: Session) -> None:
    member = db.scalar(
        select(OrgMembership.id).where(
            OrgMembership.user_id == user.id,
            OrgMembership.organization_id == organization_id,
        )
    )
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="not a member of this project's organization",
        )


def resolve_project(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
    project_id: uuid.UUID | None = Query(
        default=None,
        description="Required when authenticating with an Auth0 user session.",
    ),
) -> Project:
    """Project for a read request, via either an API key or a user session.

    API key: the key's project (project_id ignored, backward compatible).
    User session: the given project_id, authorized through org membership.
    """
    token = _bearer_token(credentials)
    if token.startswith(API_KEY_PREFIX):
        return _api_key_context(token, db).project

    user = _user_from_claims(_claims_from_token(token), db)
    if project_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="project_id is required for session auth",
        )
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="project not found"
        )
    _assert_member(user, project.organization_id, db)
    return project
