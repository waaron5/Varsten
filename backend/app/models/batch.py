"""Batch jobs: the state of the batching lever's async data plane.

Each row tracks one client batch through its lifecycle, from a staged input file
in object storage, through OpenAI's Batch API, to a staged output file and the
measured savings (batch pricing vs the synchronous price for the same tokens).

Content (the .jsonl) never lands here; it lives in object storage and is TTL'd.
This table holds metadata and the provider's file/batch ids only.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

# Internal lifecycle. "created" = job row exists, awaiting the client's upload.
# "submitted" onward mirrors OpenAI's batch status; "finalized" is our terminal
# state once the output is staged and savings are measured.
STATUS_CREATED = "created"
STATUS_SUBMITTED = "submitted"
STATUS_IN_PROGRESS = "in_progress"
STATUS_COMPLETED = "completed"
STATUS_FINALIZED = "finalized"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"
STATUS_EXPIRED = "expired"

# Non-terminal states the poller still needs to sync.
ACTIVE_STATUSES = (STATUS_SUBMITTED, STATUS_IN_PROGRESS, STATUS_COMPLETED)


class BatchJob(Base, TimestampMixin):
    __tablename__ = "batch_jobs"
    __table_args__ = (
        Index("ix_batch_jobs_project_created", "project_id", "created_at"),
        Index("ix_batch_jobs_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    api_key_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True
    )

    provider: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'openai'"))
    endpoint: Mapped[str] = mapped_column(String(64), nullable=False, server_default=text("'/v1/chat/completions'"))
    completion_window: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'24h'"))
    status: Mapped[str] = mapped_column(String(24), nullable=False, server_default=text("'created'"))

    # Object-storage keys (tenant-scoped). Content lives here, not in the row.
    input_storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    output_storage_key: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Provider identifiers.
    provider_input_file_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    provider_batch_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    provider_output_file_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    provider_error_file_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Accounting (filled in at finalize, from the output file's usage).
    request_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    output_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    # Actual batch-priced spend, the synchronous price that was avoided, and the
    # measured difference. Direct method: no holdback needed (batch price is a
    # contractual discount on the same tokens).
    actual_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(20, 12), nullable=True)
    naive_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(20, 12), nullable=True)
    saved_usd: Mapped[Decimal | None] = mapped_column(Numeric(20, 12), nullable=True)

    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
