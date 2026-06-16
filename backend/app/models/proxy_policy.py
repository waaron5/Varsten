"""Unified inline execution policies for the proxy.

One table backs the execution side of every lever the data plane runs on the hot
path. A policy is activated on the control plane when a recommendation is applied
(model-swap levers require a passing shadow eval first) and read by the proxy on
the request hot path.

The shape is deliberately generic so the four executable levers share one
abstraction instead of a table each:

- `cheaper_model` / `smart_routing` (ROUTING_LEVERS): rewrite the upstream model.
  `target_key` is the incumbent model. `params["candidate_model"]` is the model
  to route to, with optional `params["candidate_provider"]` for cross-provider
  swaps. `smart_routing` later adds a deterministic per-request predicate in
  `params`; until then it behaves like a single-candidate swap.
- `token_trim`: transform the request body before forwarding. `target_key` is the
  route. `params` holds the trim strategy config.
- `batching` runs on its own async data plane (the /v1/batches mirror), not this
  hot-path table.

One enabled policy per (project, lever, target_key). Disabling it (or the kill
switch / per-project bypass) returns traffic to the original behaviour on the
next request.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

# Levers whose execution rewrites which model answers the request. These are the
# gated, holdback-measured levers the hot-path router resolves.
ROUTING_LEVERS = ("cheaper_model", "smart_routing")


class ProxyPolicy(Base, TimestampMixin):
    __tablename__ = "proxy_policies"
    __table_args__ = (
        UniqueConstraint("project_id", "lever", "target_key", name="uq_policies_project_lever_target"),
        Index("ix_policies_project_lever_enabled", "project_id", "lever", "enabled"),
        Index("ix_policies_project_enabled", "project_id", "enabled"),
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
    lever: Mapped[str] = mapped_column(String(32), nullable=False)
    # What the policy targets: 'model' for routing levers (target_key = incumbent
    # model), 'route' for body transforms (target_key = route key).
    target_type: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'model'"))
    target_key: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    # Fraction of this policy's traffic held back on the original behaviour as the
    # control arm of the live A/B. The rest is treatment. Small by default: the
    # holdback costs money, but it buys a concurrently-measured savings number
    # rather than a modelled one.
    holdback_percent: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, server_default=text("0.05"))
    # Lever-specific config. Routing: {"candidate_model": "..."}. Trim: strategy
    # knobs. Kept as JSONB so a new lever does not need a schema change.
    params: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    # The applied recommendation whose eval cleared this policy, for provenance.
    source_recommendation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recommendations.id", ondelete="SET NULL"),
        nullable=True,
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # --- convenience accessors for the routing levers, so read-side code keeps the
    # incumbent/candidate vocabulary instead of reaching into params everywhere ---
    @property
    def incumbent_model(self) -> str:
        return self.target_key

    @property
    def candidate_model(self) -> str | None:
        return (self.params or {}).get("candidate_model")

    @property
    def candidate_provider(self) -> str | None:
        return (self.params or {}).get("candidate_provider")
