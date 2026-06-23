"""Dimension -> column mapping is correct and shared.

Regression guard for the miswiring where `workflow` resolved to the `feature`
column and `external_user_id` resolved to the `user_id` column. These columns are
distinct on UsageEvent, so a query grouping/filtering on one must never read the
other. Both the /metrics/breakdown endpoint and the /usage-events list filters
resolve through the single canonical DIMENSION_TO_COLUMN map.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from app.models import Project, UsageEvent
from app.usage_dimensions import DIMENSION_TO_COLUMN


def _b(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _event(project: Project, **overrides) -> UsageEvent:
    base = {
        "project_id": project.id,
        "organization_id": project.organization_id,
        "api_key_id": None,
        "source": "proxy",
        "provider": "openai",
        "model": "gpt-4o-mini",
        "operation": "chat_completion",
        "request_type": "chat_completion",
        "environment": "production",
        "input_tokens": 10,
        "output_tokens": 5,
        "total_tokens": 15,
        "cost_usd": Decimal("1.00"),
        "cost_source": "catalog",
        "pricing_status": "priced",
        "currency": "USD",
        "status": "success",
        "success": True,
        "event_metadata": {},
        "received_at": datetime.now(UTC),
        "occurred_at": datetime.now(UTC),
    }
    base.update(overrides)
    return UsageEvent(**base)


def test_dimension_map_points_each_name_at_its_own_column():
    # The exact mapping the bug got wrong: distinct columns, distinct names.
    assert DIMENSION_TO_COLUMN["workflow"] is UsageEvent.workflow
    assert DIMENSION_TO_COLUMN["feature"] is UsageEvent.feature
    assert DIMENSION_TO_COLUMN["external_user_id"] is UsageEvent.external_user_id
    assert DIMENSION_TO_COLUMN["user_id"] is UsageEvent.user_id


def test_breakdown_by_workflow_groups_on_workflow_not_feature(client, db_session, provision):
    ws = provision(sub="auth0|dim-workflow", email="dim-workflow@example.com")
    project = db_session.get(Project, uuid.UUID(ws["project_id"]))
    # Same feature on every row; distinct workflows. If the dimension resolved to
    # `feature` (the old bug) the breakdown would collapse to one "shared" row.
    db_session.add_all(
        [
            _event(project, feature="shared", workflow="ingest_pipeline", cost_usd=Decimal("7.00")),
            _event(project, feature="shared", workflow="ingest_pipeline", cost_usd=Decimal("1.00")),
            _event(project, feature="shared", workflow="nightly_batch", cost_usd=Decimal("3.00")),
        ]
    )
    db_session.commit()

    body = client.get("/v1/metrics/breakdown?dimension=workflow&limit=10", headers=_b(ws["api_key"])).json()
    rows = {row["key"]: Decimal(row["spend"]) for row in body["rows"]}
    assert rows == {"ingest_pipeline": Decimal("8.00"), "nightly_batch": Decimal("3.00")}
    assert "shared" not in rows  # never leaks the feature column


def test_breakdown_by_external_user_id_groups_on_external_user_id(client, db_session, provision):
    ws = provision(sub="auth0|dim-extuser", email="dim-extuser@example.com")
    project = db_session.get(Project, uuid.UUID(ws["project_id"]))
    # Distinct external_user_id, identical user_id. The old bug grouped on user_id.
    db_session.add_all(
        [
            _event(project, external_user_id="ext_a", user_id="internal_1", cost_usd=Decimal("2.00")),
            _event(project, external_user_id="ext_b", user_id="internal_1", cost_usd=Decimal("5.00")),
        ]
    )
    db_session.commit()

    body = client.get("/v1/metrics/breakdown?dimension=external_user_id&limit=10", headers=_b(ws["api_key"])).json()
    rows = {row["key"]: Decimal(row["spend"]) for row in body["rows"]}
    assert rows == {"ext_a": Decimal("2.00"), "ext_b": Decimal("5.00")}


def test_list_filter_workflow_filters_on_workflow_column(client, db_session, provision):
    ws = provision(sub="auth0|filter-workflow", email="filter-workflow@example.com")
    project = db_session.get(Project, uuid.UUID(ws["project_id"]))
    db_session.add_all(
        [
            _event(project, feature="shared", workflow="target_flow"),
            _event(project, feature="shared", workflow="other_flow"),
        ]
    )
    db_session.commit()

    body = client.get("/v1/usage-events?workflow=target_flow", headers=_b(ws["api_key"])).json()
    assert len(body["items"]) == 1
    assert body["items"][0]["workflow"] == "target_flow"


def test_list_filter_external_user_id_filters_on_external_user_id_column(client, db_session, provision):
    ws = provision(sub="auth0|filter-extuser", email="filter-extuser@example.com")
    project = db_session.get(Project, uuid.UUID(ws["project_id"]))
    db_session.add_all(
        [
            _event(project, external_user_id="ext_target", user_id="internal_shared"),
            _event(project, external_user_id="ext_other", user_id="internal_shared"),
        ]
    )
    db_session.commit()

    # Filtering by external_user_id must not match on the user_id column.
    body = client.get("/v1/usage-events?external_user_id=ext_target", headers=_b(ws["api_key"])).json()
    assert len(body["items"]) == 1
    assert body["items"][0]["external_user_id"] == "ext_target"
