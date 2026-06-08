"""Command Center data-integrity gate.

A value may appear only when there is data behind it. A zero-traffic project must
render "—"/empty everywhere — never a fabricated $0/0% that implies a measurement
that never happened. This pins the contract for every endpoint the Command Center
reads, so no future change can paint a number onto an empty dashboard.

These are sync control-plane reads, so they use the sync client + an API key.
"""

from decimal import Decimal


def _b(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_command_center_summary_is_all_null_on_empty_project(client, provision):
    ws = provision(sub="auth0|empty-cc", email="empty-cc@example.com")
    body = client.get("/v1/command-center", headers=_b(ws["api_key"])).json()

    live = body["live_savings"]
    # The KPI tiles: every displayed money/percent value is null (renders "—").
    assert live["spend_month"] is None
    assert live["saved_month"] is None
    assert live["net_saved_month"] is None
    assert live["annual_run_rate"] is None
    assert live["trust_score"] is None

    # The operational lists are empty, not stubbed.
    assert body["decision_queue"] == []
    assert body["recent_actions"] == []
    assert body["top_waste_now"] is None
    assert body["requests_month"] == 0


def test_savings_trend_is_empty_on_empty_project(client, provision):
    ws = provision(sub="auth0|empty-cc", email="empty-cc@example.com")
    body = client.get("/v1/metrics/savings-trend", headers=_b(ws["api_key"])).json()

    assert body["points"] == []
    assert Decimal(body["total_saved_usd"]) == 0
    assert Decimal(body["total_baseline_usd"]) == 0


def test_proxy_traffic_is_empty_and_null_on_empty_project(client, provision):
    ws = provision(sub="auth0|empty-cc", email="empty-cc@example.com")
    body = client.get("/v1/metrics/proxy-traffic", headers=_b(ws["api_key"])).json()

    assert body["requests"] == 0
    assert body["hit"] == 0 and body["miss"] == 0
    # Rates/latency are null (no data), not a fabricated 0% / 0ms.
    assert body["hit_rate"] is None
    assert body["latency_p50_ms"] is None
    assert body["latency_p95_ms"] is None
    assert body["latency_p99_ms"] is None
    assert body["cache_series"] == []
    assert body["latency_series"] == []
    assert body["batch_jobs"] == 0


def test_quality_routes_are_empty_on_empty_project(client, provision):
    ws = provision(sub="auth0|empty-cc", email="empty-cc@example.com")
    body = client.get("/v1/engine/routes", headers=_b(ws["api_key"])).json()
    assert body == []
