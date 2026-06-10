"""eval / replay harness schema

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-06-04 12:00:00.000000

Adds the shadow-evaluation tables (replay corpus, eval runs, per-sample results)
and the per-project opt-in flag for traffic capture. The replay corpus is a
content store, the second documented exception to the metadata-only ledger, so
its TTL column and the opt-in flag are part of the consent/retention story.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "eval_capture_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    op.create_table(
        "replay_samples",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("route_key", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False, server_default=sa.text("'traffic'")),
        sa.Column("incumbent_model", sa.String(length=128), nullable=False),
        sa.Column("request_messages", postgresql.JSONB(), nullable=False),
        sa.Column("request_params", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("incumbent_response", postgresql.JSONB(), nullable=True),
        sa.Column("expected_output", sa.Text(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_replay_samples_project_route", "replay_samples", ["project_id", "route_key"])
    op.create_index("ix_replay_samples_project_source", "replay_samples", ["project_id", "source"])
    op.create_index("ix_replay_samples_expires_at", "replay_samples", ["expires_at"])

    op.create_table(
        "eval_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recommendation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("lever", sa.String(length=32), nullable=False),
        sa.Column("route_key", sa.String(length=255), nullable=False),
        sa.Column("incumbent_model", sa.String(length=128), nullable=False),
        sa.Column("candidate_model", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("scorer_type", sa.String(length=16), nullable=True),
        sa.Column("sample_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("win_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("tie_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("loss_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("objective_pass_count", sa.Integer(), nullable=True),
        sa.Column("objective_pass_rate", sa.Numeric(5, 4), nullable=True),
        sa.Column("score_delta", sa.Numeric(6, 4), nullable=True),
        sa.Column("score_delta_ci_low", sa.Numeric(6, 4), nullable=True),
        sa.Column("score_delta_ci_high", sa.Numeric(6, 4), nullable=True),
        sa.Column("cost_delta_usd", sa.Numeric(18, 8), nullable=True),
        sa.Column("verdict", sa.String(length=20), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recommendation_id"], ["recommendations.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_eval_runs_project_created", "eval_runs", ["project_id", "created_at"])
    op.create_index("ix_eval_runs_recommendation", "eval_runs", ["recommendation_id"])

    op.create_table(
        "eval_sample_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("eval_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("replay_sample_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("candidate_response", postgresql.JSONB(), nullable=True),
        sa.Column("scorer", sa.String(length=16), nullable=False),
        sa.Column("objective_pass", sa.Boolean(), nullable=True),
        sa.Column("judge_winner", sa.String(length=16), nullable=True),
        sa.Column("score", sa.Numeric(6, 4), nullable=True),
        sa.Column("candidate_cost_usd", sa.Numeric(18, 8), nullable=True),
        sa.Column("incumbent_cost_usd", sa.Numeric(18, 8), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["eval_run_id"], ["eval_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["replay_sample_id"], ["replay_samples.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_eval_sample_results_run", "eval_sample_results", ["eval_run_id"])


def downgrade() -> None:
    op.drop_index("ix_eval_sample_results_run", table_name="eval_sample_results")
    op.drop_table("eval_sample_results")
    op.drop_index("ix_eval_runs_recommendation", table_name="eval_runs")
    op.drop_index("ix_eval_runs_project_created", table_name="eval_runs")
    op.drop_table("eval_runs")
    op.drop_index("ix_replay_samples_expires_at", table_name="replay_samples")
    op.drop_index("ix_replay_samples_project_source", table_name="replay_samples")
    op.drop_index("ix_replay_samples_project_route", table_name="replay_samples")
    op.drop_table("replay_samples")
    op.drop_column("projects", "eval_capture_enabled")
