"""Dashboard aggregation endpoints: savings-trend and proxy-traffic.

These are sync control-plane reads over the ledger, so they use the sync client +
db_session and seed UsageEvents directly. They back the Margin and Proxy-Traffic
visual narratives.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.models import Project, UsageEvent


def _b(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _proxy_event(
    project,
    *,
    cache: str,
    cost: str,
    saved: str | None,
    latency: int,
    at: datetime | None = None,
    team: str | None = None,
    feature: str | None = None,
    source: str = "proxy",
) -> UsageEvent:
    # Real proxy traffic carries no `feature` unless the client supplies it; proxy
    # rows are identified by source="proxy", not by an overloaded feature value.
    meta: dict = {"proxy": True, "cache": cache}
    if saved is not None:
        meta["saved_usd"] = saved
    ts = at or datetime.now(UTC)
    return UsageEvent(
        project_id=project.id,
        organization_id=project.organization_id,
        api_key_id=None,
        source=source,
        provider="openai",
        model="gpt-4o-mini",
        operation="chat_completion",
        request_type="chat_completion",
        feature=feature,
        team=team,
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
        received_at=ts,
        occurred_at=ts,
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
    assert Decimal(body["total_optimized_usd"]) == Decimal("0.02")
    assert Decimal(body["effective_savings_rate"]) == Decimal("0.5")


def test_savings_trend_mtd_gapfills_and_rates_from_mtd_totals(client, db_session, provision):
    ws = provision(sub="auth0|dash-mtd", email="dash-mtd@example.com")
    project = db_session.get(Project, uuid.UUID(ws["project_id"]))
    now = datetime.now(UTC)
    month_start = now.replace(day=1, hour=9, minute=0, second=0, microsecond=0)
    today = now.replace(hour=12, minute=0, second=0, microsecond=0)
    prior_month = month_start - timedelta(days=1)
    db_session.add_all(
        [
            _proxy_event(project, cache="hit", cost="3.00", saved="1.00", latency=5, at=month_start),
            _proxy_event(project, cache="hit", cost="2.00", saved="2.00", latency=8, at=today),
            _proxy_event(project, cache="hit", cost="100.00", saved="100.00", latency=8, at=prior_month),
        ]
    )
    db_session.commit()

    body = client.get("/v1/metrics/savings-trend?period=mtd", headers=_b(ws["api_key"])).json()
    points = body["points"]

    assert body["period"] == "mtd"
    assert body["period_start"] == month_start.date().isoformat()
    assert body["period_end"] == today.date().isoformat()
    assert len(points) == now.day
    assert points[0]["date"] == month_start.date().isoformat()
    assert points[-1]["date"] == today.date().isoformat()
    assert Decimal(body["total_optimized_usd"]) == Decimal("5.00")
    assert Decimal(body["total_saved_usd"]) == Decimal("3.00")
    assert Decimal(body["total_baseline_usd"]) == Decimal("8.00")
    assert Decimal(body["effective_savings_rate"]) == Decimal("0.375")
    assert sum((Decimal(p["optimized_usd"]) for p in points), Decimal("0")) == Decimal(body["total_optimized_usd"])
    assert sum((Decimal(p["saved_usd"]) for p in points), Decimal("0")) == Decimal(body["total_saved_usd"])
    assert sum((Decimal(p["baseline_usd"]) for p in points), Decimal("0")) == Decimal(body["total_baseline_usd"])
    if now.day > 2:
        gap = points[1]
        assert Decimal(gap["optimized_usd"]) == 0
        assert Decimal(gap["saved_usd"]) == 0
        assert Decimal(gap["baseline_usd"]) == 0


def test_savings_trend_mtd_empty_project_has_no_fake_rate(client, provision):
    ws = provision(sub="auth0|dash-empty-mtd", email="dash-empty-mtd@example.com")

    body = client.get("/v1/metrics/savings-trend?period=mtd", headers=_b(ws["api_key"])).json()

    assert body["period"] == "mtd"
    assert body["points"] == []
    assert Decimal(body["total_optimized_usd"]) == 0
    assert Decimal(body["total_saved_usd"]) == 0
    assert Decimal(body["total_baseline_usd"]) == 0
    assert body["effective_savings_rate"] is None


def test_breakdown_mtd_uses_current_month_not_rolling_30_days(client, db_session, provision):
    ws = provision(sub="auth0|breakdown-mtd", email="breakdown-mtd@example.com")
    project = db_session.get(Project, uuid.UUID(ws["project_id"]))
    now = datetime.now(UTC)
    this_month = now.replace(day=1, hour=10, minute=0, second=0, microsecond=0)
    prior_month = this_month - timedelta(days=1)
    db_session.add_all(
        [
            _proxy_event(project, cache="miss", cost="7.00", saved=None, latency=50, at=this_month, team="Finance"),
            _proxy_event(project, cache="miss", cost="99.00", saved=None, latency=50, at=prior_month, team="Finance"),
            _proxy_event(project, cache="miss", cost="3.00", saved=None, latency=50, at=this_month, team="Support"),
        ]
    )
    db_session.commit()

    body = client.get("/v1/metrics/breakdown?dimension=team&period=mtd&limit=5", headers=_b(ws["api_key"])).json()
    rows = {row["key"]: row for row in body["rows"]}

    assert Decimal(rows["Finance"]["spend"]) == Decimal("7.00")
    assert Decimal(rows["Support"]["spend"]) == Decimal("3.00")
    assert sum(Decimal(row["spend"]) for row in body["rows"]) == Decimal("10.00")


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


def test_proxy_traffic_counts_events_with_custom_feature(client, db_session, provision):
    """Regression: proxy traffic is identified by source, not by feature == 'proxy'.
    A well-instrumented client that tags its own feature must still be counted."""
    ws = provision(sub="auth0|custom-feature", email="custom-feature@example.com")
    project = db_session.get(Project, uuid.UUID(ws["project_id"]))
    db_session.add_all(
        [
            _proxy_event(project, cache="hit", cost="0", saved="0.01", latency=5, feature="support_agent"),
            _proxy_event(project, cache="miss", cost="0.02", saved=None, latency=400, feature="billing_copilot"),
        ]
    )
    db_session.commit()

    body = client.get("/v1/metrics/proxy-traffic", headers=_b(ws["api_key"])).json()
    # Both rows count despite carrying real client feature tags (not "proxy").
    assert body["requests"] == 2 and body["hit"] == 1 and body["miss"] == 1


def test_proxy_traffic_excludes_ingest_source(client, db_session, provision):
    """Metadata-ingested events (source='ingest') are not proxy traffic, even if a
    client happened to tag feature='proxy'."""
    ws = provision(sub="auth0|ingest-src", email="ingest-src@example.com")
    project = db_session.get(Project, uuid.UUID(ws["project_id"]))
    db_session.add_all(
        [
            _proxy_event(project, cache="hit", cost="0", saved="0.01", latency=5),  # source="proxy"
            _proxy_event(project, cache="miss", cost="0.02", saved=None, latency=9, source="ingest", feature="proxy"),
        ]
    )
    db_session.commit()

    body = client.get("/v1/metrics/proxy-traffic", headers=_b(ws["api_key"])).json()
    assert body["requests"] == 1 and body["hit"] == 1 and body["miss"] == 0
