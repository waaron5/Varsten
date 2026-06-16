"""Helper for writing append-only audit events.

Call ``record_audit`` from a sensitive mutation point with the actor and the
resource touched. It adds the row to the caller's session; the caller's existing
commit persists it atomically with the action it records. Never pass secret values
(a provider-key event records that a key changed, not the key).
"""

import uuid
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.models import AuditEvent, User


def client_ip(request: Request | None) -> str | None:
    """Best-effort source IP. Honors a single X-Forwarded-For hop (the managed
    container host sits behind a proxy); falls back to the socket peer."""
    if request is None:
        return None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def record_audit(
    db: Session,
    *,
    action: str,
    actor: User | None = None,
    organization_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    source_ip: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    event = AuditEvent(
        organization_id=organization_id,
        project_id=project_id,
        actor_user_id=actor.id if actor is not None else None,
        actor_email=actor.email if actor is not None else None,
        action=action,
        target_type=target_type,
        target_id=target_id,
        source_ip=source_ip,
        before=before,
        after=after,
        details=details or {},
    )
    db.add(event)
    return event
