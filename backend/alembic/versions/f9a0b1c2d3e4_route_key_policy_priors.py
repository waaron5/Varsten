"""route-key linkage for policies and outcome priors

Revision ID: f9a0b1c2d3e4
Revises: d5e6f7a8b9c2
Create Date: 2026-07-05 14:00:00.000000

Policies and persisted learning priors used to be keyed only by requested model.
That was safe but coarse: a support route and a summarization route on the same
model could share guardrail and prior evidence. This additive migration stores
the canonical route key beside the existing model keys, backfilling old policies
to the default route so the database uniqueness guarantee remains real.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f9a0b1c2d3e4"
down_revision: str | Sequence[str] | None = "d5e6f7a8b9c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "proxy_policies",
        sa.Column("route_key", sa.String(length=128), nullable=False, server_default=sa.text("'default'")),
    )
    op.drop_constraint("uq_policies_project_lever_target", "proxy_policies", type_="unique")
    op.create_unique_constraint(
        "uq_policies_project_lever_target_route",
        "proxy_policies",
        ["project_id", "lever", "target_key", "route_key"],
    )
    op.create_index("ix_policies_project_route_key", "proxy_policies", ["project_id", "route_key"])

    op.add_column(
        "engine_outcome_priors",
        sa.Column("route_key", sa.String(length=128), nullable=False, server_default=sa.text("'default'")),
    )
    op.drop_constraint("uq_engine_outcome_priors_segment", "engine_outcome_priors", type_="unique")
    op.create_unique_constraint(
        "uq_engine_outcome_priors_segment",
        "engine_outcome_priors",
        [
            "project_id",
            "route_key",
            "lever",
            "task_type",
            "risk_level",
            "provider_requested",
            "model_requested",
            "provider_chosen",
            "model_chosen",
        ],
    )
    op.create_index(
        "ix_engine_outcome_priors_project_route_model_lever",
        "engine_outcome_priors",
        ["project_id", "route_key", "model_requested", "lever"],
    )


def downgrade() -> None:
    op.drop_index("ix_engine_outcome_priors_project_route_model_lever", table_name="engine_outcome_priors")
    op.drop_constraint("uq_engine_outcome_priors_segment", "engine_outcome_priors", type_="unique")
    op.create_unique_constraint(
        "uq_engine_outcome_priors_segment",
        "engine_outcome_priors",
        [
            "project_id",
            "lever",
            "task_type",
            "risk_level",
            "provider_requested",
            "model_requested",
            "provider_chosen",
            "model_chosen",
        ],
    )
    op.drop_column("engine_outcome_priors", "route_key")

    op.drop_index("ix_policies_project_route_key", table_name="proxy_policies")
    op.drop_constraint("uq_policies_project_lever_target_route", "proxy_policies", type_="unique")
    op.create_unique_constraint(
        "uq_policies_project_lever_target",
        "proxy_policies",
        ["project_id", "lever", "target_key"],
    )
    op.drop_column("proxy_policies", "route_key")
