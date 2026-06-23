"""rename model-swap lever to model_downshift

Revision ID: f0a1b2c3d4e5
Revises: e3f4a5b6c7d8
Create Date: 2026-06-22 00:00:00.000000
"""

from typing import Sequence

from alembic import op

revision: str = "f0a1b2c3d4e5"
down_revision: str | Sequence[str] | None = "e3f4a5b6c7d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _rename_lever("'cheaper' || '_model'", "'model_downshift'")
    _rename_recommendation_type("'cheaper' || '_model'", "'model_downshift'")
    _rename_recommendation_dedupe("'cheaper' || '\\_model:%'", "'model_downshift:'")


def downgrade() -> None:
    _rename_lever("'model_downshift'", "'cheaper' || '_model'")
    _rename_recommendation_type("'model_downshift'", "'cheaper' || '_model'")
    _rename_recommendation_dedupe("'model\\_downshift:%'", "'cheaper' || '_model:'")


def _rename_lever(old_sql: str, new_sql: str) -> None:
    op.execute(
        f"""
        UPDATE lever_configs lc
        SET lever = {new_sql}, updated_at = now()
        WHERE lc.lever = {old_sql}
          AND NOT EXISTS (
              SELECT 1
              FROM lever_configs existing
              WHERE existing.project_id = lc.project_id
                AND existing.lever = {new_sql}
          )
        """
    )
    op.execute(f"DELETE FROM lever_configs WHERE lever = {old_sql}")

    op.execute(
        f"""
        UPDATE proxy_policies pp
        SET lever = {new_sql}, updated_at = now()
        WHERE pp.lever = {old_sql}
          AND NOT EXISTS (
              SELECT 1
              FROM proxy_policies existing
              WHERE existing.project_id = pp.project_id
                AND existing.target_key = pp.target_key
                AND existing.lever = {new_sql}
          )
        """
    )
    op.execute(f"DELETE FROM proxy_policies WHERE lever = {old_sql}")

    for table in (
        "recommendations",
        "recommendation_actions",
        "savings_attributions",
        "eval_runs",
        "request_decision_events",
    ):
        op.execute(f"UPDATE {table} SET lever = {new_sql} WHERE lever = {old_sql}")


def _rename_recommendation_type(old_sql: str, new_sql: str) -> None:
    op.execute(f"UPDATE recommendations SET type = {new_sql} WHERE type = {old_sql}")


def _rename_recommendation_dedupe(old_like_sql: str, new_prefix_sql: str) -> None:
    # dedupe_key carries a (project_id, dedupe_key) unique constraint, so a blind
    # rename collides when an org already holds the renamed key for the same route
    # (e.g. a legacy cheaper_model rec and a new model_downshift rec for the same
    # route/month). Mirror the NOT EXISTS + DELETE guard this migration already uses
    # for lever_configs/proxy_policies: drop the legacy rows that would collide with
    # an existing target row, then rename the survivors.
    renamed_key = f"{new_prefix_sql} || substring(dedupe_key from position(':' in dedupe_key) + 1)"
    op.execute(
        f"""
        DELETE FROM recommendations r
        WHERE r.dedupe_key LIKE ({old_like_sql}) ESCAPE '\\'
          AND EXISTS (
              SELECT 1
              FROM recommendations existing
              WHERE existing.project_id = r.project_id
                AND existing.dedupe_key =
                    {new_prefix_sql} || substring(r.dedupe_key from position(':' in r.dedupe_key) + 1)
          )
        """
    )
    op.execute(
        f"""
        UPDATE recommendations
        SET dedupe_key = {renamed_key}
        WHERE dedupe_key LIKE ({old_like_sql}) ESCAPE '\\'
        """
    )
