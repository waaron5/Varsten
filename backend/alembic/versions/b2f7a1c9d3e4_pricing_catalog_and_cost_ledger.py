"""pricing catalog and cost ledger

Revision ID: b2f7a1c9d3e4
Revises: e8cdae50e45d
Create Date: 2026-06-02 10:00:00.000000

Adds the model catalog, versioned price tables, and per-org overrides, and
extends usage_events so cost is derived and auditable rather than client-trusted.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2f7a1c9d3e4"
down_revision: Union[str, Sequence[str], None] = "e8cdae50e45d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Per-token rates are tiny (e.g. 5e-7); keep twelve fractional digits.
TOKEN_COST = sa.Numeric(precision=20, scale=12)


def upgrade() -> None:
    op.create_table(
        "model_catalog",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("model_key", sa.String(length=128), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=True),
        sa.Column("tier", sa.String(length=16), nullable=True),
        sa.Column(
            "supports_vision", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "supports_function_calling",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "supports_reasoning",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("cheaper_substitute_key", sa.String(length=128), nullable=True),
        sa.Column("source", sa.String(length=32), server_default=sa.text("'litellm'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("model_key", "provider", name="uq_model_catalog_key_provider"),
    )

    op.create_table(
        "model_prices",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("model_key", sa.String(length=128), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("currency", sa.String(length=8), server_default=sa.text("'USD'"), nullable=False),
        sa.Column("input_cost_per_token", TOKEN_COST, server_default=sa.text("0"), nullable=False),
        sa.Column("output_cost_per_token", TOKEN_COST, server_default=sa.text("0"), nullable=False),
        sa.Column("cache_read_input_token_cost", TOKEN_COST, nullable=True),
        sa.Column("cache_write_input_token_cost", TOKEN_COST, nullable=True),
        sa.Column("input_cost_per_token_batch", TOKEN_COST, nullable=True),
        sa.Column("output_cost_per_token_batch", TOKEN_COST, nullable=True),
        sa.Column("source", sa.String(length=32), server_default=sa.text("'litellm'"), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_model_prices_key_provider_effective_at",
        "model_prices",
        ["model_key", "provider", sa.literal_column("effective_at DESC")],
        unique=False,
    )

    op.create_table(
        "org_model_price_overrides",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("model_key", sa.String(length=128), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=True),
        sa.Column("currency", sa.String(length=8), server_default=sa.text("'USD'"), nullable=False),
        sa.Column("input_cost_per_token", TOKEN_COST, server_default=sa.text("0"), nullable=False),
        sa.Column("output_cost_per_token", TOKEN_COST, server_default=sa.text("0"), nullable=False),
        sa.Column("cache_read_input_token_cost", TOKEN_COST, nullable=True),
        sa.Column("cache_write_input_token_cost", TOKEN_COST, nullable=True),
        sa.Column("effective_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_org_price_overrides_org_key_effective_at",
        "org_model_price_overrides",
        ["organization_id", "model_key", sa.literal_column("effective_at DESC")],
        unique=False,
    )

    # --- extend usage_events ---------------------------------------------------
    op.add_column(
        "usage_events",
        sa.Column("cached_input_tokens", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "usage_events",
        sa.Column("reasoning_tokens", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "usage_events",
        sa.Column("reported_cost_usd", sa.Numeric(precision=18, scale=8), nullable=True),
    )
    op.add_column(
        "usage_events",
        sa.Column("cost_source", sa.String(length=16), server_default=sa.text("'reported'"), nullable=False),
    )
    op.add_column("usage_events", sa.Column("price_version_id", sa.UUID(), nullable=True))
    op.add_column("usage_events", sa.Column("idempotency_key", sa.String(length=255), nullable=True))
    op.add_column(
        "usage_events",
        sa.Column("status", sa.String(length=16), server_default=sa.text("'success'"), nullable=False),
    )
    op.add_column("usage_events", sa.Column("event_timestamp", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        "fk_usage_events_price_version",
        "usage_events",
        "model_prices",
        ["price_version_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint(
        "uq_usage_events_project_idempotency",
        "usage_events",
        ["project_id", "idempotency_key"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_usage_events_project_idempotency", "usage_events", type_="unique")
    op.drop_constraint("fk_usage_events_price_version", "usage_events", type_="foreignkey")
    op.drop_column("usage_events", "event_timestamp")
    op.drop_column("usage_events", "status")
    op.drop_column("usage_events", "idempotency_key")
    op.drop_column("usage_events", "price_version_id")
    op.drop_column("usage_events", "cost_source")
    op.drop_column("usage_events", "reported_cost_usd")
    op.drop_column("usage_events", "reasoning_tokens")
    op.drop_column("usage_events", "cached_input_tokens")

    op.drop_index("ix_org_price_overrides_org_key_effective_at", table_name="org_model_price_overrides")
    op.drop_table("org_model_price_overrides")
    op.drop_index("ix_model_prices_key_provider_effective_at", table_name="model_prices")
    op.drop_table("model_prices")
    op.drop_table("model_catalog")
