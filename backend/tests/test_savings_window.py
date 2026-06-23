"""Window-savings reconciliation -- the dashboard's integrity spine.

These pin the invariants the consolidated dashboard relies on: the gross KPI
equals the sum of the per-lever rows, the counterfactual equals paid + avoided,
and the savings chart series sums to the gross. They also pin the coherence rule
(measured first, else labelled estimate, else spend-only) and prove holdback
saved_usd never inflates the reconciling per-day savings.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.models import Organization, Project, ProxyPolicy, Recommendation, SavingsAttribution, UsageEvent
from app.periods import resolve_period
from app.savings import compute_savings_for_window, compute_savings_with_deltas, measured_savings_series


def _project(db_session, workspace: dict) -> Project:
    return db_session.get(Project, uuid.UUID(workspace["project_id"]))


def _event(
    project: Project,
    received_at: datetime,
    *,
    cost: str = "0",
    saved: str | None = None,
    kind: str | None = None,
    holdback: bool = False,
) -> UsageEvent:
    """A ledger event. ``kind`` selects the lever metadata (cache/batch/route) that
    direct measurement keys off; ``holdback`` tags a treatment arm."""
    meta: dict = {"proxy": True}
    if kind == "cache":
        meta["cache"] = "hit"
    elif kind == "batch":
        meta["batch"] = True
    elif kind == "route":
        meta["cache"] = "miss"
        meta["routed"] = True
    if saved is not None:
        meta["saved_usd"] = saved
    if holdback:
        meta["holdback"] = True
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
        event_metadata=meta,
        received_at=received_at,
        occurred_at=received_at,
    )


def _midwindow(window) -> datetime:
    """A timestamp guaranteed inside [start, end) for the resolved window."""
    return window.start + window.elapsed / 2


def test_empty_window_is_all_null(client, db_session, provision):
    ws = provision(sub="auth0|win-empty", email="win-empty@example.com")
    project = _project(db_session, ws)
    window = resolve_period(datetime.now(UTC), "month")

    s = compute_savings_for_window(db_session, project, window)
    assert s["mode"] == "empty"
    assert s["actual_spend_usd"] is None
    assert s["gross_savings_usd"] is None
    assert s["net_savings_usd"] is None
    assert s["counterfactual_spend_usd"] is None
    assert s["by_lever"] == {}


def test_spend_only_window_reports_actual_but_null_savings(client, db_session, provision):
    ws = provision(sub="auth0|win-spend", email="win-spend@example.com")
    project = _project(db_session, ws)
    window = resolve_period(datetime.now(UTC), "month")
    db_session.add(_event(project, _midwindow(window), cost="9.00"))  # no saved_usd, no attribution
    db_session.commit()

    s = compute_savings_for_window(db_session, project, window)
    assert s["mode"] == "spend_only"
    assert s["actual_spend_usd"] == Decimal("9.00")
    assert s["gross_savings_usd"] is None
    # Counterfactual collapses to actual when there is no measured/estimated saving.
    assert s["counterfactual_spend_usd"] == Decimal("9.00")
    assert s["by_lever"] == {}


def test_measured_window_reconciles_gross_levers_counterfactual_and_chart(client, db_session, provision):
    ws = provision(sub="auth0|win-measured", email="win-measured@example.com")
    project = _project(db_session, ws)
    org = db_session.get(Organization, project.organization_id)
    org.gain_share_percent = Decimal("0.2500")
    window = resolve_period(datetime.now(UTC), "month")
    at = _midwindow(window)
    db_session.add_all(
        [
            _event(project, at, cost="0", saved="6.00", kind="cache"),  # semantic_cache
            _event(project, at, cost="4.00", saved="2.50", kind="route"),  # smart_routing
            _event(project, at, cost="1.00", saved="1.50", kind="batch"),  # batching
        ]
    )
    db_session.commit()

    s = compute_savings_for_window(db_session, project, window)
    assert s["mode"] == "measured"
    assert s["by_lever_source"] == "measured"

    gross = s["gross_savings_usd"]
    assert gross == Decimal("10.00")  # 6.00 + 2.50 + 1.50
    # Invariant 1: gross == sum of the lever rows.
    assert sum(s["by_lever"].values(), Decimal("0")) == gross
    assert s["by_lever"] == {
        "semantic_cache": Decimal("6.00"),
        "batching": Decimal("1.50"),
        "smart_routing": Decimal("2.50"),
    }
    # Invariant 2: counterfactual == actual paid + avoided.
    actual = s["actual_spend_usd"]
    assert actual == Decimal("5.00")  # 0 + 4 + 1
    assert s["counterfactual_spend_usd"] == actual + gross
    # Fee/net from the org rate, net >= 0.
    assert s["varsten_fee_usd"] == Decimal("2.50")
    assert s["net_savings_usd"] == Decimal("7.50")

    # Invariant 3: the chart series sums to the gross and the actual.
    series = measured_savings_series(db_session, project, window)
    assert sum((row["saved_usd"] for row in series), Decimal("0")) == gross
    assert sum((row["optimized_usd"] for row in series), Decimal("0")) == actual


def test_routed_savings_credit_the_enabled_routing_lever(client, db_session, provision):
    """When a model_downshift routing policy is active, routed ledger savings are
    credited to model_downshift (the lever that drove the route), not the hard-coded
    smart_routing default."""
    ws = provision(sub="auth0|win-routing-lever", email="win-routing-lever@example.com")
    project = _project(db_session, ws)
    window = resolve_period(datetime.now(UTC), "month")
    db_session.add(
        ProxyPolicy(
            organization_id=project.organization_id,
            project_id=project.id,
            lever="model_downshift",
            target_type="model",
            target_key="gpt-4o",
            enabled=True,
            activated_at=datetime.now(UTC),
        )
    )
    db_session.add_all(
        [
            _event(project, _midwindow(window), cost="0", saved="6.00", kind="cache"),
            _event(project, _midwindow(window), cost="4.00", saved="2.50", kind="route"),
        ]
    )
    db_session.commit()

    s = compute_savings_for_window(db_session, project, window)
    assert s["by_lever"] == {"semantic_cache": Decimal("6.00"), "model_downshift": Decimal("2.50")}
    assert "smart_routing" not in s["by_lever"]


def test_holdback_treatment_savings_count_under_the_routing_lever(client, db_session, provision):
    """A routed holdback-experiment treatment event carries a real per-event
    saved_usd (avoided cost), so it counts toward the routing lever and the gross.
    The chart includes it too, so chart/lever/gross still reconcile exactly."""
    ws = provision(sub="auth0|win-holdback", email="win-holdback@example.com")
    project = _project(db_session, ws)
    window = resolve_period(datetime.now(UTC), "month")
    at = _midwindow(window)
    db_session.add_all(
        [
            _event(project, at, cost="0", saved="6.00", kind="cache"),  # semantic_cache
            _event(project, at, cost="4.00", saved="2.50", kind="route", holdback=True),  # treatment
        ]
    )
    db_session.commit()

    s = compute_savings_for_window(db_session, project, window)
    # No routing ProxyPolicy in this test, so routed savings fall back to smart_routing.
    assert s["gross_savings_usd"] == Decimal("8.50")
    assert s["by_lever"] == {"semantic_cache": Decimal("6.00"), "smart_routing": Decimal("2.50")}
    series = measured_savings_series(db_session, project, window)
    assert sum((row["saved_usd"] for row in series), Decimal("0")) == Decimal("8.50")


def test_estimated_fallback_when_no_measured_savings(client, db_session, provision):
    ws = provision(sub="auth0|win-estimated", email="win-estimated@example.com")
    project = _project(db_session, ws)
    window = resolve_period(datetime.now(UTC), "month")
    at = _midwindow(window)
    db_session.add_all(
        [
            _event(project, at, cost="20.00"),  # spend, but no ledger saved_usd
            SavingsAttribution(
                organization_id=project.organization_id,
                project_id=project.id,
                lever="model_downshift",
                measurement_method="estimated",
                status="estimated",
                period_start=at,
                period_end=window.end,
                gross_savings_usd=Decimal("30.00"),
                varsten_fee_usd=Decimal("6.00"),
                net_savings_usd=Decimal("24.00"),
            ),
        ]
    )
    db_session.commit()

    s = compute_savings_for_window(db_session, project, window)
    assert s["mode"] == "estimated"
    assert s["by_lever_source"] == "estimated"
    assert s["gross_savings_usd"] == Decimal("30.00")
    assert s["by_lever"] == {"model_downshift": Decimal("30.00")}
    assert sum(s["by_lever"].values(), Decimal("0")) == s["gross_savings_usd"]


def test_open_opportunity_surfaced_separately_from_gross(client, db_session, provision):
    ws = provision(sub="auth0|win-opp", email="win-opp@example.com")
    project = _project(db_session, ws)
    window = resolve_period(datetime.now(UTC), "month")
    at = _midwindow(window)
    db_session.add_all(
        [
            _event(project, at, cost="0", saved="6.00", kind="cache"),
            Recommendation(
                organization_id=project.organization_id,
                project_id=project.id,
                dedupe_key="win-opp:1",
                type="semantic_cache",
                lever="semantic_cache",
                target_type="route",
                target_key="proxy:chat_completion",
                title="More reuse available",
                description="x",
                rationale="x",
                estimated_monthly_savings_usd=Decimal("40.00"),
                monthly_request_volume=100,
                risk_level="low",
                confidence="high",
                measurement_method="estimated",
                status="open",
            ),
        ]
    )
    db_session.commit()

    s = compute_savings_for_window(db_session, project, window)
    # Open opportunity is an estimate of remaining savings, never summed into gross.
    assert s["gross_savings_usd"] == Decimal("6.00")
    assert s["estimated_opportunity_usd"] == Decimal("40.00")


# --- deltas vs the same-elapsed prior window ----------------------------------


def test_deltas_compare_against_same_elapsed_prior_window(client, db_session, provision):
    ws = provision(sub="auth0|delta-measured", email="delta-measured@example.com")
    project = _project(db_session, ws)
    org = db_session.get(Organization, project.organization_id)
    org.gain_share_percent = Decimal("0.2500")
    window = resolve_period(datetime.now(UTC), "month")
    cur = _midwindow(window)
    prior = _midwindow(window.prior())
    db_session.add_all(
        [
            # Current window: gross 10.00, actual 5.00.
            _event(project, cur, cost="0", saved="6.00", kind="cache"),
            _event(project, cur, cost="4.00", saved="2.50", kind="route"),
            _event(project, cur, cost="1.00", saved="1.50", kind="batch"),
            # Prior window: gross 5.00, actual 0.00.
            _event(project, prior, cost="0", saved="5.00", kind="cache"),
        ]
    )
    db_session.commit()

    result = compute_savings_with_deltas(db_session, project, window)
    kpis = result["kpis"]

    assert result["current"]["gross_savings_usd"] == Decimal("10.00")
    # gross 10 vs 5 -> +100%; net 7.50 vs 3.75 -> +100%.
    assert kpis["gross_saved"]["delta_pct"] == Decimal("1.0000")
    assert kpis["net_saved"]["previous"] == Decimal("3.75")
    assert kpis["net_saved"]["delta_pct"] == Decimal("1.0000")
    # counterfactual 15 vs 5 -> +200%.
    assert kpis["without_varsten"]["delta_pct"] == Decimal("2.0000")
    # actual 5 vs prior 0 -> not comparable (division by zero) -> None.
    assert kpis["actual_spend"]["previous"] == Decimal("0.00")
    assert kpis["actual_spend"]["delta_pct"] is None


def test_deltas_are_null_when_no_prior_data(client, db_session, provision):
    ws = provision(sub="auth0|delta-noprior", email="delta-noprior@example.com")
    project = _project(db_session, ws)
    window = resolve_period(datetime.now(UTC), "month")
    db_session.add(_event(project, _midwindow(window), cost="0", saved="6.00", kind="cache"))
    db_session.commit()

    result = compute_savings_with_deltas(db_session, project, window)
    assert result["current"]["gross_savings_usd"] == Decimal("6.00")
    for kpi in result["kpis"].values():
        assert kpi["delta_pct"] is None  # empty prior window -> nothing to compare


def test_deltas_report_a_decline_as_negative(client, db_session, provision):
    ws = provision(sub="auth0|delta-decline", email="delta-decline@example.com")
    project = _project(db_session, ws)
    window = resolve_period(datetime.now(UTC), "month")
    db_session.add_all(
        [
            _event(project, _midwindow(window), cost="0", saved="3.00", kind="cache"),
            _event(project, _midwindow(window.prior()), cost="0", saved="6.00", kind="cache"),
        ]
    )
    db_session.commit()

    kpis = compute_savings_with_deltas(db_session, project, window)["kpis"]
    # gross 3 vs 6 -> -50%.
    assert kpis["gross_saved"]["delta_pct"] == Decimal("-0.5000")


# --- chart gap-fill -----------------------------------------------------------


def test_series_is_gap_filled_from_period_start_to_today(client, db_session, provision):
    ws = provision(sub="auth0|series-gap", email="series-gap@example.com")
    project = _project(db_session, ws)
    now = datetime.now(UTC)
    window = resolve_period(now, "month")
    # One event today only; the rest of the month has no traffic.
    db_session.add(_event(project, now - timedelta(hours=1), cost="2.00", saved="3.00", kind="cache"))
    db_session.commit()

    series = measured_savings_series(db_session, project, window)
    # A bucket for every day from the 1st through today, not just the day with data.
    assert len(series) == now.day
    assert series[0]["date"].day == 1
    assert series[-1]["date"] == now.date()
    # Days with no traffic are real zeros, and the gap-fill never changes the totals.
    assert sum((row["saved_usd"] for row in series), Decimal("0")) == Decimal("3.00")
    assert sum((row["optimized_usd"] for row in series), Decimal("0")) == Decimal("2.00")
    zero_days = [row for row in series if row["saved_usd"] == 0 and row["optimized_usd"] == 0]
    assert len(zero_days) == now.day - 1


def test_series_is_empty_on_zero_traffic_window(client, db_session, provision):
    ws = provision(sub="auth0|series-empty", email="series-empty@example.com")
    project = _project(db_session, ws)
    window = resolve_period(datetime.now(UTC), "month")
    # No events at all -> no fabricated chart.
    assert measured_savings_series(db_session, project, window) == []
