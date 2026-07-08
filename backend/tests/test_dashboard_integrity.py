"""Dashboard data-integrity gate.

A value may appear only when there is data behind it. A zero-traffic project must
render "—"/empty everywhere — never a fabricated $0/0% that implies a measurement
that never happened. This pins the contract for every endpoint the Dashboard
reads, so no future change can paint a number onto an empty dashboard.

These are sync control-plane reads, so they use the sync client + an API key.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from app.auth.entitlements import invalidate_plan_tier
from app.models import PLAN_PERFORMANCE, Organization, Project, Recommendation, SavingsAttribution, UsageEvent
from app.savings import month_end, month_start


def _b(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _project(db_session, workspace: dict) -> Project:
    return db_session.get(Project, uuid.UUID(workspace["project_id"]))


def _traffic_event(project: Project, *, cost: str = "1.00", saved: str | None = None) -> UsageEvent:
    metadata: dict = {"proxy": True}
    if saved is not None:
        metadata["cache"] = "hit"
        metadata["saved_usd"] = saved
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
        input_tokens=100,
        output_tokens=50,
        cached_input_tokens=0,
        total_tokens=150,
        cost_usd=Decimal(cost),
        cost_source="catalog",
        pricing_status="priced",
        currency="USD",
        status="success",
        success=True,
        event_metadata=metadata,
        received_at=datetime.now(UTC),
        occurred_at=datetime.now(UTC),
    )


def _open_recommendation(project: Project, amount: str) -> Recommendation:
    return Recommendation(
        organization_id=project.organization_id,
        project_id=project.id,
        dedupe_key=f"test-opportunity:{amount}",
        type="semantic_cache",
        lever="semantic_cache",
        target_type="route",
        target_key="proxy:chat_completion",
        title="Enable safe response reuse",
        description="Repeated prompts can be served from cache on Optimize.",
        rationale="Seeded recommendation for Dashboard projection integrity.",
        estimated_monthly_savings_usd=Decimal(amount),
        monthly_request_volume=100,
        risk_level="low",
        confidence="high",
        measurement_method="estimated",
        status="open",
    )


def test_dashboard_summary_is_all_null_on_empty_project(client, provision):
    ws = provision(sub="auth0|empty-cc", email="empty-cc@example.com")
    body = client.get("/v1/dashboard", headers=_b(ws["api_key"])).json()

    live = body["live_savings"]
    # The KPI tiles: every displayed money/percent value is null (renders "—").
    assert live["spend_month"] is None
    assert live["saved_month"] is None
    assert live["net_saved_month"] is None
    assert live["estimated_impact_month"] is None
    assert live["verified_saved_month"] is None
    assert live["verified_net_saved_month"] is None
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


def test_proof_savings_zero_traffic_has_no_projected_or_verified_money(client, provision):
    ws = provision(sub="auth0|empty-proof", email="empty-proof@example.com")
    body = client.get("/v1/proof/savings", headers=_b(ws["api_key"])).json()

    assert body["plan_tier"] == "free"
    assert Decimal(body["observed_spend_usd"]) == 0
    assert Decimal(body["estimated"]["gross_savings_usd"]) == 0
    assert Decimal(body["estimated"]["open_opportunity_gross_usd"]) == 0
    assert Decimal(body["estimated"]["open_opportunity_fee_usd"]) == 0
    assert Decimal(body["estimated"]["open_opportunity_net_usd"]) == 0
    assert "verified" not in body


def test_free_proof_savings_reports_projected_open_opportunity_net(client, db_session, provision):
    ws = provision(sub="auth0|free-projection", email="free-projection@example.com")
    project = _project(db_session, ws)
    db_session.add_all([_traffic_event(project, cost="12.00"), _open_recommendation(project, "100.00")])
    db_session.commit()

    org = db_session.get(Organization, project.organization_id)
    body = client.get("/v1/proof/savings", headers=_b(ws["api_key"])).json()
    expected_fee = Decimal("100.00") * Decimal(org.gain_share_percent)

    assert body["plan_tier"] == "free"
    assert Decimal(body["estimated"]["open_opportunity_gross_usd"]) == Decimal("100.00")
    assert Decimal(body["estimated"]["open_opportunity_fee_usd"]) == expected_fee
    assert Decimal(body["estimated"]["open_opportunity_net_usd"]) == Decimal("100.00") - expected_fee
    assert "verified" not in body


def test_fee_percent_is_configurable_per_org_below_cap(client, db_session, provision):
    """The gain-share fee flows from organizations.gain_share_percent, so changing
    it changes both the proof opportunity fee and the billing-security display."""
    ws = provision(sub="auth0|fee-config", email="fee-config@example.com")
    project = _project(db_session, ws)
    org = db_session.get(Organization, project.organization_id)
    org.gain_share_percent = Decimal("0.2000")
    db_session.add_all([_traffic_event(project, cost="12.00"), _open_recommendation(project, "100.00")])
    db_session.commit()

    proof = client.get("/v1/proof/savings", headers=_b(ws["api_key"])).json()
    assert Decimal(proof["estimated"]["open_opportunity_fee_usd"]) == Decimal("20.00")
    assert Decimal(proof["estimated"]["open_opportunity_net_usd"]) == Decimal("80.00")

    billing = client.get("/v1/admin/billing-security", headers=_b(ws["api_key"])).json()
    assert Decimal(billing["verified_savings_fee_percent"]) == Decimal("20.00")


def test_performance_proof_savings_keeps_verified_separate_from_estimate(client, db_session, provision):
    ws = provision(sub="auth0|perf-proof", email="perf-proof@example.com")
    project = _project(db_session, ws)
    org = db_session.get(Organization, project.organization_id)
    org.plan_tier = PLAN_PERFORMANCE
    now = datetime.now(UTC)
    db_session.add_all(
        [
            _traffic_event(project, cost="0", saved="4.25"),
            SavingsAttribution(
                organization_id=project.organization_id,
                project_id=project.id,
                lever="semantic_cache",
                measurement_method="estimated",
                status="estimated",
                period_start=month_start(now),
                period_end=month_end(now),
                counterfactual_spend_usd=Decimal("250.00"),
                actual_spend_usd=Decimal("200.00"),
                gross_savings_usd=Decimal("50.00"),
                varsten_fee_usd=Decimal("10.00"),
                net_savings_usd=Decimal("40.00"),
            ),
        ]
    )
    db_session.commit()
    invalidate_plan_tier()

    body = client.get("/v1/proof/savings", headers=_b(ws["api_key"])).json()

    assert body["plan_tier"] == "performance"
    assert Decimal(body["estimated"]["gross_savings_usd"]) == Decimal("50.00000000")
    assert Decimal(body["estimated"]["net_savings_usd"]) == Decimal("40.00000000")
    assert Decimal(body["verified"]["verified_savings_usd"]) == Decimal("4.25")
    assert Decimal(body["verified"]["verified_net_usd"]) != Decimal(body["estimated"]["net_savings_usd"])


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
