from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_api_key
from app.db.session import get_db
from app.models import ApiKey, Project

bearer_scheme = HTTPBearer(auto_error=False)

# Avoid an UPDATE on the api_keys row for every ingested event. Under load that
# row-level write contention would cap throughput. Refresh last_used_at at most
# once per interval instead.
LAST_USED_REFRESH = timedelta(seconds=60)


def require_api_key(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> Project:
    """Resolve the project for a Bearer API key, or 401.

    Looks the key up by sha256 hash, rejects missing/revoked keys, and returns
    the owning project. Plaintext keys are never stored, so lookup is by hash.
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing api key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    key_hash = hash_api_key(credentials.credentials)
    api_key = db.scalar(select(ApiKey).where(ApiKey.key_hash == key_hash))
    if api_key is None or api_key.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid api key",
            headers={"WWW-Authenticate": "Bearer"},
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
            headers={"WWW-Authenticate": "Bearer"},
        )
    return project
