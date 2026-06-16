"""Append-only audit log of sensitive control-plane actions.

This is the tamper-evident record a security review (and SOC 2 CC-series controls)
expects: who did what, to which tenant resource, and when. It is written from the
sensitive mutation points -- operator plan switches and provider-key custody
changes -- and is never updated or deleted by application code (append-only by
convention; revoking UPDATE/DELETE at the database role level is a follow-up).

Actor identity is denormalized onto the row (email) so the record stays readable
even if the user is later removed. No secret values are ever written here -- a
provider-key event records that a key was set, never the key.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# Canonical action names. Keep these stable; dashboards and exports key on them.
ACTION_PLAN_CHANGED = "plan.changed"
ACTION_PROVIDER_KEY_CONNECTED = "provider_key.connected"
ACTION_PROVIDER_KEY_DISCONNECTED = "provider_key.disconnected"


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_org_created_at", "organization_id", text("created_at DESC")),
        Index("ix_audit_events_action_created_at", "action", text("created_at DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Denormalized so the record survives the actor being deleted.
    actor_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Before/after snapshots and any non-secret context. Never holds key material.
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
