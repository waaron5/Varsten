import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ProxyCacheEntry(Base):
    """A semantic-cache entry for the inline proxy.

    Phase 1 matches on cache_key, an exact hash of the normalized request
    (model + messages + sampling params). The column and lookup are the seam where
    real vector similarity slots in later. This table is the one documented
    exception to the metadata-only ledger: it must store the response to serve it,
    so treat it as opt-in cached content with its own retention controls.
    """

    __tablename__ = "proxy_cache_entries"
    __table_args__ = (
        UniqueConstraint("project_id", "cache_key", name="uq_proxy_cache_project_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    cache_key: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    # The assembled OpenAI response, served verbatim on a hit.
    response_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # Token counts of the cached completion, so a hit can record the avoided cost.
    input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    output_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    last_hit_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
