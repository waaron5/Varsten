"""Integration tests for the ingestion endpoint's cost derivation and idempotency.

Uses the API-key path. A ModelPrice row is inserted via the same test session so
the endpoint can derive cost; the client and db_session share one transaction.
"""

from decimal import Decimal

import pytest

from app.db.session import SessionLocal
from app.models import ModelCatalog, ModelPrice, Organization

# The ingestion endpoint derives cost via an async pricing bridge that runs on a
# separate connection, so a price flushed into the test's savepoint transaction is
# invisible to it. Seed prices with a real commit (visible across connections under
# READ COMMITTED) and delete them after the test. Catalog rows are read by the sync
# control plane on the test's own connection, so they stay on the savepoint.
_seeded_price_ids: list = []


@pytest.fixture(autouse=True)
def _cleanup_committed_prices():
    yield
    if not _seeded_price_ids:
        return
    s = SessionLocal()
    try:
        for pid in _seeded_price_ids:
            row = s.get(ModelPrice, pid)
            if row is not None:
                s.delete(row)
        s.commit()
    finally:
        s.close()
        _seeded_price_ids.clear()


def _key(client) -> str:
    # Provision through the authenticated endpoints: sync a user (bootstrapping
    # their personal org), then create a project and an ingestion key in it.
    sub = "auth0|ingest"
    user = client.post("/v1/auth/sync", headers=_bearer(sub), json={"email": "ingest@example.com", "name": None}).json()
    org_id = user["organizations"][0]["id"]
    proj = client.post(f"/v1/organizations/{org_id}/projects", headers=_bearer(sub), json={"name": "p"}).json()
    key = client.post(f"/v1/projects/{proj['id']}/api-keys", headers=_bearer(sub), json={"name": "k"}).json()
    return key["plaintext_key"]


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _seed_price(
    db,
    model_key="gpt-4o-mini",
    provider="openai",
    input_cost="0.000001",
    output_cost="0.000002",
    batch_input_cost=None,
    batch_output_cost=None,
):
    # Commit on a real connection so the async pricing bridge sees it; tracked for
    # cleanup by the autouse fixture. (db param kept for call-site compatibility.)
    s = SessionLocal()
    try:
        row = ModelPrice(
            model_key=model_key,
            provider=provider,
            input_cost_per_token=Decimal(input_cost),
            output_cost_per_token=Decimal(output_cost),
            input_cost_per_token_batch=(Decimal(batch_input_cost) if batch_input_cost is not None else None),
            output_cost_per_token_batch=(Decimal(batch_output_cost) if batch_output_cost is not None else None),
        )
        s.add(row)
        s.commit()
        s.refresh(row)
        _seeded_price_ids.append(row.id)
    finally:
        s.close()


def _seed_catalog(
    db,
    model_key: str,
    provider: str = "openai",
    tier: str | None = None,
    cheaper_substitute_key: str | None = None,
):
    db.add(
        ModelCatalog(
            model_key=model_key,
            provider=provider,
            tier=tier,
            cheaper_substitute_key=cheaper_substitute_key,
        )
    )
    db.flush()


def _event(**overrides) -> dict:
    body = {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "operation": "chat_completion",
        "input_tokens": 1000,
        "output_tokens": 500,
    }
    body.update(overrides)
    return body


def test_derives_cost_for_known_model(client, db_session):
    _seed_price(db_session)
    token = _key(client)

    res = client.post("/v1/usage-events", headers=_bearer(token), json=_event())
    assert res.status_code == 201
    body = res.json()
    assert body["cost_source"] == "catalog"
    assert body["pricing_status"] == "priced"
    assert body["price_version_id"] is not None
    # 1000*1e-6 + 500*2e-6 = 0.002
    assert Decimal(body["cost_usd"]) == Decimal("0.002")
    assert body["reported_cost_usd"] is None


def test_falls_back_to_reported_cost_for_unknown_model(client, db_session):
    token = _key(client)
    res = client.post(
        "/v1/usage-events",
        headers=_bearer(token),
        json=_event(model="mystery-model", cost_usd="0.0042"),
    )
    assert res.status_code == 201
    body = res.json()
    assert body["cost_source"] == "reported"
    assert body["pricing_status"] == "model_not_in_catalog"
    assert body["price_version_id"] is None
    assert Decimal(body["cost_usd"]) == Decimal("0.0042")
    assert Decimal(body["reported_cost_usd"]) == Decimal("0.0042")


def test_unpriceable_event_is_stored_with_null_cost(client, db_session):
    token = _key(client)
    res = client.post(
        "/v1/usage-events",
        headers=_bearer(token),
        json=_event(model="mystery-model"),  # no price, no cost_usd
    )
    assert res.status_code == 201
    body = res.json()
    assert body["cost_usd"] is None
    assert body["cost_source"] == "unknown"
    assert body["pricing_status"] == "model_not_in_catalog"


def test_accepts_canonical_usage_fields(client, db_session):
    _seed_price(db_session)
    token = _key(client)
    res = client.post(
        "/v1/usage-events",
        headers=_bearer(token),
        json={
            "provider": "openai",
            "model": "gpt-4o-mini",
            "request_type": "summarize_ticket",
            "feature": "ticket_summarization",
            "customer_id": "cust_123",
            "user_id": "user_456",
            "team": "support",
            "department": "support",
            "environment": "production",
            "input_tokens": 100,
            "output_tokens": 50,
            "latency_ms": 1840,
            "success": True,
        },
    )
    assert res.status_code == 201
    body = res.json()
    assert body["request_type"] == "summarize_ticket"
    assert body["operation"] == "summarize_ticket"
    assert body["feature"] == "ticket_summarization"
    assert body["workflow"] == "ticket_summarization"
    assert body["customer_id"] == "cust_123"
    assert body["user_id"] == "user_456"
    assert body["external_user_id"] == "user_456"
    assert body["environment"] == "production"


def test_non_usd_is_rejected(client, db_session):
    _seed_price(db_session)
    token = _key(client)
    res = client.post(
        "/v1/usage-events",
        headers=_bearer(token),
        json=_event(currency="EUR"),
    )
    assert res.status_code == 422


def test_idempotency_key_dedupes_retries(client, db_session):
    _seed_price(db_session)
    token = _key(client)
    payload = _event(idempotency_key="abc-123")

    first = client.post("/v1/usage-events", headers=_bearer(token), json=payload)
    second = client.post("/v1/usage-events", headers=_bearer(token), json=payload)
    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]

    listed = client.get("/v1/usage-events", headers=_bearer(token)).json()
    assert len(listed["items"]) == 1


def test_overview_reports_cost_trust_share(client, db_session):
    _seed_price(db_session)
    token = _key(client)
    # One catalog-priced event (0.002) and one reported event (0.002).
    client.post("/v1/usage-events", headers=_bearer(token), json=_event())
    client.post(
        "/v1/usage-events",
        headers=_bearer(token),
        json=_event(model="mystery-model", cost_usd="0.002"),
    )

    overview = client.get("/v1/metrics/overview", headers=_bearer(token)).json()
    assert Decimal(overview["authoritative_spend_month"]) == Decimal("0.002")
    # Half of spend is authoritative (catalog), half reported.
    assert Decimal(overview["authoritative_spend_share_month"]) == Decimal("0.5")
    assert Decimal(overview["catalog_spend_month"]) == Decimal("0.002")
    assert Decimal(overview["reported_spend_month"]) == Decimal("0.002")


def test_overview_reports_forecast_and_unpriced_share(client, db_session):
    token = _key(client)
    client.post(
        "/v1/usage-events",
        headers=_bearer(token),
        json=_event(model="mystery-model"),
    )

    overview = client.get("/v1/metrics/overview", headers=_bearer(token)).json()
    assert Decimal(overview["spend_month"]) == Decimal("0")
    assert Decimal(overview["monthly_forecast_usd"]) == Decimal("0")
    assert overview["unpriced_event_count_month"] == 1
    assert overview["unpriced_token_count_month"] == 1500
    assert Decimal(overview["unpriced_event_share_month"]) == Decimal("1")


def test_recommendations_are_persisted_and_deduped(client, db_session):
    token = _key(client)
    client.post(
        "/v1/usage-events",
        headers=_bearer(token),
        json=_event(model="mystery-model"),
    )

    first = client.get("/v1/recommendations", headers=_bearer(token))
    second = client.get("/v1/recommendations", headers=_bearer(token))
    assert first.status_code == 200
    assert second.status_code == 200
    first_items = first.json()
    second_items = second.json()
    assert len(first_items) == len(second_items) == 1
    assert first_items[0]["type"] == "unpriced_usage"
    assert first_items[0]["id"] == second_items[0]["id"]


def _recommendations_by_lever(client, token: str, lever: str) -> list[dict]:
    res = client.get("/v1/recommendations", headers=_bearer(token))
    assert res.status_code == 200
    return [item for item in res.json() if item["lever"] == lever]


def test_token_trim_recommendation_is_lever_tagged(client, db_session):
    _seed_price(db_session)
    token = _key(client)
    client.post(
        "/v1/usage-events",
        headers=_bearer(token),
        json=_event(
            request_type="summarize",
            feature="research_agent",
            input_tokens=9000,
            output_tokens=1000,
        ),
    )

    recs = _recommendations_by_lever(client, token, "token_trim")
    assert len(recs) == 1
    assert recs[0]["type"] == "token_trim"
    assert recs[0]["target_type"] == "route"
    assert recs[0]["monthly_request_volume"] == 1


def test_semantic_cache_recommendation_uses_cache_key_metadata(client, db_session):
    _seed_price(db_session)
    token = _key(client)
    for _ in range(3):
        client.post(
            "/v1/usage-events",
            headers=_bearer(token),
            json=_event(
                request_type="answer_faq",
                feature="support_bot",
                input_tokens=1000,
                output_tokens=500,
                metadata={"semantic_cache_key": "faq:reset-password"},
            ),
        )

    recs = _recommendations_by_lever(client, token, "semantic_cache")
    assert len(recs) == 1
    assert recs[0]["type"] == "semantic_cache"
    assert recs[0]["confidence"] == "medium"


def test_batching_recommendation_requires_batch_pricing(client, db_session):
    _seed_price(
        db_session,
        batch_input_cost="0.0000005",
        batch_output_cost="0.000001",
    )
    token = _key(client)
    client.post(
        "/v1/usage-events",
        headers=_bearer(token),
        json=_event(
            request_type="nightly_export",
            feature="analytics_exports",
            input_tokens=1000,
            output_tokens=500,
            metadata={"batchable": "true"},
        ),
    )

    recs = _recommendations_by_lever(client, token, "batching")
    assert len(recs) == 1
    assert recs[0]["type"] == "batching"
    assert recs[0]["risk_level"] == "low"


def test_cheaper_model_recommendation_uses_catalog_substitute(client, db_session):
    _seed_price(
        db_session,
        model_key="gpt-expensive",
        input_cost="0.000004",
        output_cost="0.000008",
    )
    _seed_price(
        db_session,
        model_key="gpt-cheap",
        input_cost="0.000001",
        output_cost="0.000002",
    )
    _seed_catalog(
        db_session,
        model_key="gpt-expensive",
        tier="frontier",
        cheaper_substitute_key="gpt-cheap",
    )
    token = _key(client)
    client.post(
        "/v1/usage-events",
        headers=_bearer(token),
        json=_event(
            model="gpt-expensive",
            request_type="classify",
            feature="triage",
            input_tokens=1000,
            output_tokens=500,
        ),
    )

    recs = _recommendations_by_lever(client, token, "cheaper_model")
    assert len(recs) == 1
    assert recs[0]["type"] == "cheaper_model"
    assert recs[0]["related_model"] == "gpt-expensive"


def test_smart_routing_recommendation_compares_route_costs(client, db_session):
    _seed_price(
        db_session,
        model_key="gpt-expensive",
        input_cost="0.000004",
        output_cost="0.000008",
    )
    _seed_price(
        db_session,
        model_key="gpt-cheap",
        input_cost="0.000001",
        output_cost="0.000002",
    )
    token = _key(client)
    for model in ("gpt-expensive", "gpt-cheap"):
        client.post(
            "/v1/usage-events",
            headers=_bearer(token),
            json=_event(
                model=model,
                request_type="chat",
                feature="assistant",
                input_tokens=1000,
                output_tokens=500,
            ),
        )

    recs = _recommendations_by_lever(client, token, "smart_routing")
    assert len(recs) == 1
    assert recs[0]["type"] == "smart_routing"
    assert recs[0]["target_type"] == "route"


def test_product_section_read_apis_render_with_api_key(client, db_session):
    _seed_price(db_session)
    token = _key(client)
    client.post(
        "/v1/usage-events",
        headers=_bearer(token),
        json=_event(
            request_type="summarize",
            feature="research_agent",
            customer_id="cust_1",
            team="platform",
            environment="production",
            input_tokens=9000,
            output_tokens=1000,
        ),
    )

    for path in (
        "/v1/dashboard",
        "/v1/engine/recommendations",
        "/v1/engine/levers",
        "/v1/engine/automation",
        "/v1/proof/savings",
        "/v1/proof/attribution",
        "/v1/proof/data-quality",
        "/v1/guardrails/quality",
        "/v1/guardrails/budgets",
        "/v1/guardrails/alerts",
        "/v1/analysis/spend",
        "/v1/analysis/customers",
        "/v1/analysis/models",
        "/v1/admin/connections",
        "/v1/admin/team",
        "/v1/admin/billing-security",
    ):
        res = client.get(path, headers=_bearer(token))
        assert res.status_code == 200, path

    dashboard = client.get("/v1/dashboard", headers=_bearer(token)).json()
    assert "live_savings" in dashboard
    assert "decision_queue" in dashboard


def test_product_section_config_writes(client, db_session):
    token = _key(client)
    # This exercises behaviour-changing config (auto-rollback guardrail, hard cap),
    # which is Performance-only, so run it on a Performance org.
    import uuid as _uuid

    me = client.post(
        "/v1/auth/sync", headers=_bearer("auth0|ingest"), json={"email": "ingest@example.com", "name": None}
    ).json()
    org = db_session.get(Organization, _uuid.UUID(me["organizations"][0]["id"]))
    org.plan_tier = "performance"
    db_session.flush()

    lever = client.patch(
        "/v1/engine/levers/token_trim",
        headers=_bearer(token),
        json={"enabled": False, "automation_mode": "approve"},
    )
    assert lever.status_code == 200
    assert lever.json()["enabled"] is False
    assert lever.json()["automation_mode"] == "approve"

    quality = client.post(
        "/v1/guardrails/quality",
        headers=_bearer(token),
        json={
            "route": "support_bot",
            "min_model_tier": "mid",
            "eval_gate": "golden_set",
            "min_eval_score": "0.95",
        },
    )
    assert quality.status_code == 201
    assert quality.json()["route"] == "support_bot"

    budget = client.post(
        "/v1/guardrails/budgets",
        headers=_bearer(token),
        json={
            "owner_type": "feature",
            "owner_key": "support_bot",
            "monthly_budget_usd": "1000",
            "hard_cap_enabled": True,
        },
    )
    assert budget.status_code == 201
    assert budget.json()["owner_key"] == "support_bot"

    alert = client.post(
        "/v1/guardrails/alerts",
        headers=_bearer(token),
        json={
            "alert_type": "forecast_over_budget",
            "threshold_percent": "0.90",
            "destination_type": "email",
            "destination": "ops@example.com",
        },
    )
    assert alert.status_code == 201
    assert alert.json()["alert_type"] == "forecast_over_budget"
