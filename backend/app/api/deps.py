import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Depends, HTTPException, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.auth.auth0 import Auth0NotConfigured, verify_access_token
from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import hash_api_key
from app.db.session import get_async_db, get_db
from app.models import ApiKey, Organization, OrgMembership, Project, User

logger = get_logger("varsten.auth")

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


def _proxy_api_key_token(
    credentials: HTTPAuthorizationCredentials | None,
    request: Request,
) -> str:
    """Resolve the Varsten API key from common SDK auth locations.

    OpenAI-compatible SDKs send Authorization: Bearer. Anthropic's SDK sends
    x-api-key. Gemini's native SDK sends x-goog-api-key. All must contain the
    Varsten vk_ key when targeting the proxy.
    """
    if credentials is not None and credentials.credentials:
        return credentials.credentials
    for header_name in ("x-api-key", "x-goog-api-key"):
        value = request.headers.get(header_name)
        if value:
            return value
    query_key = request.query_params.get("key")
    if query_key:
        return query_key
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="missing credentials",
        headers=_UNAUTHENTICATED,
    )


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

    now = datetime.now(UTC)
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


# --- async API key auth (the hot-path proxy; control-plane uses the sync ones) ---


# Process-global cache of resolved proxy keys: vk_ hash -> (monotonic stored_at,
# context). Read only when the database lookup raises, so a known active key keeps
# serving through a brief DB blip instead of 500ing. Bounded by
# settings.api_key_cache_ttl_seconds; see _api_key_context_async.
_api_key_cache: dict[str, tuple[float, ApiKeyContext]] = {}


def clear_api_key_cache() -> None:
    """Drop all cached proxy-key contexts (used by tests)."""
    _api_key_cache.clear()


def _cached_api_key_context(key_hash: str, ttl: float) -> ApiKeyContext | None:
    if ttl <= 0:
        return None
    cached = _api_key_cache.get(key_hash)
    if cached is None:
        return None
    stored_at, ctx = cached
    if time.monotonic() - stored_at <= ttl:
        return ctx
    _api_key_cache.pop(key_hash, None)
    return None


async def _resolve_api_key_context_async(key_hash: str, db: AsyncSession) -> ApiKeyContext:
    """Resolve the project + API key from the database. Raises HTTPException for an
    auth rejection (unknown/revoked key, missing project); lets a database error
    propagate so the caller can decide whether to serve a cached context."""
    api_key = await db.scalar(select(ApiKey).where(ApiKey.key_hash == key_hash))
    if api_key is None or api_key.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid api key",
            headers=_UNAUTHENTICATED,
        )

    now = datetime.now(UTC)
    if api_key.last_used_at is None or now - api_key.last_used_at > LAST_USED_REFRESH:
        api_key.last_used_at = now
        await db.commit()

    project = await db.get(Project, api_key.project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid api key",
            headers=_UNAUTHENTICATED,
        )
    return ApiKeyContext(project=project, api_key=api_key)


async def _api_key_context_async(token: str, db: AsyncSession) -> ApiKeyContext:
    """Resolve the proxy key, with a small fail-open cache around the database.

    Happy path always re-resolves fresh from the database and refreshes the cache.
    Only when the database itself errors do we serve a recently resolved context for
    a *known* key, so a brief Postgres blip degrades to "stop optimizing" rather
    than "drop the customer's traffic". An auth rejection always fails closed: an
    unknown or revoked key is never served from cache.
    """
    key_hash = hash_api_key(token)
    ttl = settings.api_key_cache_ttl_seconds
    if settings.api_key_positive_cache_enabled:
        cached = _cached_api_key_context(key_hash, ttl)
        if cached is not None:
            return cached
    try:
        ctx = await _resolve_api_key_context_async(key_hash, db)
    except HTTPException:
        # Authentication decision (unknown/revoked key, missing project). Fail closed;
        # never let a cached context paper over a rejection.
        raise
    except Exception:
        # The database failed, not the credential. Serve a known key's cached context
        # if it is fresh enough. Unknown keys never have a cache entry, so they still
        # fail (the error propagates) and never get forwarded.
        cached = _cached_api_key_context(key_hash, ttl)
        if cached is not None:
            logger.warning("api-key database lookup failed; serving cached context (degraded)")
            return cached
        raise

    if ttl > 0:
        _api_key_cache[key_hash] = (time.monotonic(), ctx)
    return ctx


async def require_api_key_context_async(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_async_db),
) -> ApiKeyContext:
    """Async resolver of the project + API key for a Bearer API key, for endpoints
    on the async DB stack (the inline proxy)."""
    token = _proxy_api_key_token(credentials, request)
    if not token.startswith(API_KEY_PREFIX):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="expected an api key",
            headers=_UNAUTHENTICATED,
        )
    return await _api_key_context_async(token, db)


# --- Auth0 session auth (dashboard) -------------------------------------------


def _claims_from_token(token: str) -> dict:
    try:
        return verify_access_token(token)
    except Auth0NotConfigured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="auth is not configured",
        ) from None
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid token",
            headers=_UNAUTHENTICATED,
        ) from None


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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project not found")
    _assert_member(user, project.organization_id, db)
    return project


# --- Management-endpoint authorization (session-only, org-scoped) -------------
# These gate the org/project/api-key management routes. Each resolves the
# resource named in the path and asserts the signed-in user belongs to its
# organization, so no tenant can touch another tenant's resources.


def require_org_member(
    organization_id: uuid.UUID,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> Organization:
    """The organization in the path, authorized by membership."""
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="organization not found")
    _assert_member(user, organization_id, db)
    return org


def require_project_member(
    project_id: uuid.UUID,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> Project:
    """The project in the path, authorized through its organization."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project not found")
    _assert_member(user, project.organization_id, db)
    return project


def require_api_key_member(
    api_key_id: uuid.UUID,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> ApiKey:
    """The API key in the path, authorized through its project's organization."""
    api_key = db.get(ApiKey, api_key_id)
    if api_key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="api key not found")
    project = db.get(Project, api_key.project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="api key not found")
    _assert_member(user, project.organization_id, db)
    return api_key
