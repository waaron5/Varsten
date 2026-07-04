import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.project import Project

# Entitlement tiers. Free is observe-only: Varsten meters and recommends but may
# never activate a behaviour-changing lever. Performance unlocks the savings
# levers. Enterprise is deferred (no extra capabilities modeled yet).
PLAN_FREE = "free"
PLAN_PERFORMANCE = "performance"
PLAN_TIERS = (PLAN_FREE, PLAN_PERFORMANCE)

# Subscription lifecycle, independent of the entitlement tier. A new self-serve
# workspace starts `trialing` on Performance; Stripe activation drives it to
# `active`; an unpaid trial that runs out is swept to `expired`. Operator config
# can still set these directly.
SUBSCRIPTION_TRIALING = "trialing"
SUBSCRIPTION_ACTIVE = "active"
SUBSCRIPTION_PAST_DUE = "past_due"
SUBSCRIPTION_CANCELED = "canceled"
# Trial window elapsed without a payment method; the org has been downgraded to
# Free observe-only. Distinct from `canceled` (a paid plan the customer ended).
SUBSCRIPTION_EXPIRED = "expired"
SUBSCRIPTION_STATUSES = (
    SUBSCRIPTION_TRIALING,
    SUBSCRIPTION_ACTIVE,
    SUBSCRIPTION_PAST_DUE,
    SUBSCRIPTION_CANCELED,
    SUBSCRIPTION_EXPIRED,
)

# Varsten's default share of verified savings (gain-share). Per-org overridable.
DEFAULT_GAIN_SHARE_PERCENT = Decimal("0.25")


class Organization(Base, TimestampMixin):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    monthly_spend_budget_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    # Marks a seeded demo tenant. The demo seeder asserts this before any wipe, so
    # it can never touch a real customer org (is_demo=False is the default).
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    # Entitlement tier. Free (default) is observe-only; behaviour-changing levers
    # are gated to performance. The single source of truth for feature gating.
    plan_tier: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text(f"'{PLAN_FREE}'"))
    # When the self-serve onboarding funnel was completed, so it is not re-shown.
    # Null means onboarding is unfinished. All other setup state (has key, has
    # provider, first request) is derived from existing tables, not stored here.
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Subscription lifecycle (manual today; Stripe later). Independent of plan_tier.
    subscription_status: Mapped[str] = mapped_column(
        String(24), nullable=False, server_default=text(f"'{SUBSCRIPTION_ACTIVE}'")
    )
    # Per-org governance enforcement: when true, gated levers require an approved
    # ChangeRequest before apply, regardless of the global default. The enterprise
    # "default-on approvals" option; toggling it is owner/admin-only and audited.
    governance_enforced: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    plan_effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Self-serve trial window. Set when the workspace is provisioned; trial_ends_at
    # is the hard stop after which an unpaid org falls back to Free observe-only.
    trial_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Stripe linkage for self-serve upgrade. The customer is created on first
    # checkout; the subscription id is set once a payment method activates
    # Performance. Their presence is what tells the trial sweep an org has paid.
    stripe_customer_id: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Onboarding funnel events that are NOT derivable from other tables. Everything
    # else (api key, provider connection, first request) is derived live. First
    # write wins; these only mark that the step happened, never un-happen.
    integration_snippet_viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dashboard_entered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Gain-share billing config. The fee is this fraction of VERIFIED savings, with
    # a monthly floor; the floor is always capped at the savings so net stays >= 0.
    gain_share_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 4),
        nullable=False,
        default=DEFAULT_GAIN_SHARE_PERCENT,
        server_default=text("0.2500"),
    )
    monthly_fee_floor_usd: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, server_default=text("0"))

    memberships: Mapped[list["OrgMembership"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    projects: Mapped[list["Project"]] = relationship(back_populates="organization", cascade="all, delete-orphan")


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    auth_provider_subject: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)

    memberships: Mapped[list["OrgMembership"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class OrgMembership(Base, TimestampMixin):
    __tablename__ = "org_memberships"
    __table_args__ = (UniqueConstraint("organization_id", "user_id", name="uq_org_memberships_org_user"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="owner")

    organization: Mapped["Organization"] = relationship(back_populates="memberships")
    user: Mapped["User"] = relationship(back_populates="memberships")
