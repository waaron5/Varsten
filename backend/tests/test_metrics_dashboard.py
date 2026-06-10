"""Command Center aggregation endpoints: savings-trend and proxy-traffic.

These are sync control-plane reads over the ledger, so they use the sync client +
db_session and seed UsageEvents directly. They back the Margin and Proxy-Traffic
visual narratives.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from app.models import Project, UsageEvent


def _b(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _proxy_event(project, *, cache: str, cost: str, saved: str | None, latency: int) -> UsageEvent:
    meta: dict = {"proxy": True, "cache": cache}
    if saved is not None:
        meta["saved_usd"] = saved
    return UsageEvent(
        project_id=project.id,
        organization_id=project.organization_id,
        api_key_id=None,
        provider="openai",
        model="gpt-4o-mini",
        operation="chat_completion",
        request_type="chat_completion",
        feature="proxy",
        environment="production",
        input_tokens=10,
        output_tokens=5,
        cached_input_tokens=0,
        total_tokens=15,
        cost_usd=Decimal(cost),
        cost_source="catalog",
        pricing_status="priced",
        currency="USD",
        status="success",
        success=True,
        latency_ms=latency,
        event_metadata=meta,
        occurred_at=datetime.now(UTC),
    )


def test_savings_trend_reports_baseline_and_cumulative(client, db_session, provision):
    ws = provision(sub="auth0|dash", email="dash@example.com")
    project = db_session.get(Project, uuid.UUID(ws["project_id"]))
    db_session.add_all(
        [
            _proxy_event(project, cache="hit", cost="0", saved="0.01", latency=5),
            _proxy_event(project, cache="hit", cost="0", saved="0.01", latency=8),
            _proxy_event(project, cache="miss", cost="0.02", saved=None, latency=800),
        ]
    )
    db_session.commit()

    body = client.get("/v1/metrics/savings-trend", headers=_b(ws["api_key"])).json()
    # optimized = SUM(cost) = 0.02; saved = SUM(saved_usd) = 0.02; baseline = 0.04.
    assert Decimal(body["total_saved_usd"]) == Decimal("0.02")
    assert Decimal(body["total_baseline_usd"]) == Decimal("0.04")
    last = body["points"][-1]
    assert Decimal(last["saved_usd"]) == Decimal("0.02")
    assert Decimal(last["baseline_usd"]) == Decimal("0.04")
    assert Decimal(last["cumulative_saved_usd"]) == Decimal("0.02")


def test_proxy_traffic_reports_hit_rate_saved_and_latency(client, db_session, provision):
    ws = provision(sub="auth0|dash", email="dash@example.com")
    project = db_session.get(Project, uuid.UUID(ws["project_id"]))
    db_session.add_all(
        [
            _proxy_event(project, cache="hit", cost="0", saved="0.01", latency=5),
            _proxy_event(project, cache="hit", cost="0", saved="0.01", latency=8),
            _proxy_event(project, cache="miss", cost="0.02", saved=None, latency=800),
        ]
    )
    db_session.commit()

    body = client.get("/v1/metrics/proxy-traffic", headers=_b(ws["api_key"])).json()
    assert body["requests"] == 3 and body["hit"] == 2 and body["miss"] == 1
    assert abs(float(body["hit_rate"]) - 2 / 3) < 1e-6
    assert Decimal(body["cache_saved_usd"]) == Decimal("0.02")
    # percentile_cont(0.5) over [5, 8, 800] = 8; latency is captured, not null.
    assert body["latency_p50_ms"] == 8
    assert body["latency_p95_ms"] is not None
    # No batch jobs seeded: the batch query still resolves to zeroes.
    assert body["batch_jobs"] == 0 and body["batch_requests"] == 0


def test_proxy_traffic_latency_null_without_traffic(client, db_session, provision):
    ws = provision(sub="auth0|empty", email="empty@example.com")
    body = client.get("/v1/metrics/proxy-traffic", headers=_b(ws["api_key"])).json()
    assert body["requests"] == 0
    assert body["hit_rate"] is None
    assert body["latency_p50_ms"] is None  # honest null, not a fabricated number
