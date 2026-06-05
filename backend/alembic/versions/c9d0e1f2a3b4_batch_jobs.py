"""batch jobs (batching lever async data plane)

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-06-05 12:00:00.000000

Tracks each client batch through its lifecycle: staged input in object storage,
through OpenAI's Batch API, to a staged output and the measured savings. Content
never lands in this table; only metadata and provider file/batch ids.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, Sequence[str], None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "batch_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("api_key_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=False, server_default=sa.text("'openai'")),
        sa.Column("endpoint", sa.String(length=64), nullable=False, server_default=sa.text("'/v1/chat/completions'")),
        sa.Column("completion_window", sa.String(length=16), nullable=False, server_default=sa.text("'24h'")),
        sa.Column("status", sa.String(length=24), nullable=False, server_default=sa.text("'created'")),
        sa.Column("input_storage_key", sa.String(length=512), nullable=False),
        sa.Column("output_storage_key", sa.String(length=512), nullable=True),
        sa.Column("provider_input_file_id", sa.String(length=128), nullable=True),
        sa.Column("provider_batch_id", sa.String(length=128), nullable=True),
        sa.Column("provider_output_file_id", sa.String(length=128), nullable=True),
        sa.Column("provider_error_file_id", sa.String(length=128), nullable=True),
        sa.Column("request_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("input_tokens", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("output_tokens", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("actual_cost_usd", sa.Numeric(20, 12), nullable=True),
        sa.Column("naive_cost_usd", sa.Numeric(20, 12), nullable=True),
        sa.Column("saved_usd", sa.Numeric(20, 12), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["api_key_id"], ["api_keys.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_batch_jobs_project_created", "batch_jobs", ["project_id", "created_at"])
    op.create_index("ix_batch_jobs_status", "batch_jobs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_batch_jobs_status", table_name="batch_jobs")
    op.drop_index("ix_batch_jobs_project_created", table_name="batch_jobs")
    op.drop_table("batch_jobs")
