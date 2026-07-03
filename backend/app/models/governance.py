"""Governance objects: the ChangeRequest decision spine.

Before this table, "approving" a routing change was implicit and smeared across
four places: a Recommendation status flip, an EvalRun verdict, a ProxyPolicy
activation, and a RecommendationAction log row. No single object said *this
specific change is awaiting a named human's decision, here is the evidence
bundle, here is who approved it and why*. The ChangeRequest is that object
(designed in docs/design/PALANTIR_ONTOLOGY_DESIGN.md, implemented natively).

One ChangeRequest = one proposed model-swap change (incumbent -> candidate on a
route) awaiting disposition. State machine:

    proposed --approve--> approved --(apply activates the policy)--> active
       |                                                                |
       +--reject--> rejected                        (drift rollback) rolled_back

The system creates it when a routing-lever recommendation's shadow eval
completes with an actionable verdict; a human decides it; every decision writes
an immutable audit event. The evidence bundle is a content-free snapshot of the
eval and savings facts the decision rested on, frozen at proposal time so the
audit trail shows what the approver actually saw.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

CR_PROPOSED = "proposed"
CR_APPROVED = "approved"
CR_REJECTED = "rejected"
CR_ACTIVE = "active"
CR_ROLLED_BACK = "rolled_back"

# Statuses a human decision may move a change request from / to.
DECIDABLE_STATUSES = (CR_PROPOSED,)
CR_STATUSES = (CR_PROPOSED, CR_APPROVED, CR_REJECTED, CR_ACTIVE, CR_ROLLED_BACK)


class ChangeRequest(Base, TimestampMixin):
    __tablename__ = "change_requests"
    __table_args__ = (
        UniqueConstraint("project_id", "recommendation_id", name="uq_change_requests_project_recommendation"),
        Index("ix_change_requests_project_status", "project_id", "status"),
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
    # Provenance: the proposed change and the safety evidence it rests on.
    recommendation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recommendations.id", ondelete="CASCADE"),
        nullable=False,
    )
    eval_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("eval_runs.id", ondelete="SET NULL"),
        nullable=True,
    )

    # What changes, in route vocabulary.
    lever: Mapped[str] = mapped_column(String(32), nullable=False)
    route_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    incumbent_model: Mapped[str] = mapped_column(String(128), nullable=False)
    candidate_model: Mapped[str] = mapped_column(String(128), nullable=False)

    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'proposed'"))
    # Content-free snapshot of the evidence the decision rested on (eval verdict,
    # scores, sample counts, estimated savings), frozen at proposal time.
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))

    # The human decision.
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
