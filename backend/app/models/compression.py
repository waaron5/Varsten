"""Prompt-compression artifacts: the evidence and payload of the learned lever.

One row per generated compressed rewrite of a route's stable system prompt. The
compressed text itself is stored — this is a **documented content-store
exception** in the same class as the semantic cache and the replay corpus: the
lever cannot substitute a prompt it does not hold. The *original* prompt is
never stored here; only its exact hash, which is both the runtime match key
(substitute only when the request's system prompt hashes to exactly what was
evaluated) and the privacy boundary (the original lives solely in the replay
corpus under its own consent settings).

Lifecycle state lives on the linked machinery, not here: the artifact points at
its Recommendation (whose eval run, ChangeRequest, and ProxyPolicy carry
gating, approval, and activation), so the full evidence chain for an active
compression is artifact -> recommendation -> eval run -> change request ->
policy, every link persisted.
"""

import uuid

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class PromptCompression(Base, TimestampMixin):
    __tablename__ = "prompt_compressions"
    __table_args__ = (
        Index("ix_prompt_compressions_project_route", "project_id", "route_key"),
        Index("ix_prompt_compressions_recommendation", "recommendation_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    recommendation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recommendations.id", ondelete="SET NULL"),
        nullable=True,
    )

    route_key: Mapped[str] = mapped_column(String(128), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)

    # Exact match key: full sha256 hex of the original system prompt text. The
    # runtime substitutes ONLY when a request's system prompt hashes to this.
    original_system_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    original_chars: Mapped[int] = mapped_column(Integer, nullable=False)
    # The compressed rewrite (content; documented exception, see module docstring).
    compressed_system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    compressed_chars: Mapped[int] = mapped_column(Integer, nullable=False)
    # Provenance of the rewrite (e.g. "llm:gpt-4o-mini", "injected:test").
    generator: Mapped[str] = mapped_column(String(64), nullable=False)
