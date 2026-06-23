"""Consolidated dashboard snapshot endpoint.

Pins the contract the frontend renders directly: the panels reconcile (gross KPI
== lever footer == sum of lever rows == chart total), the empty project stays
all-null, the period param is validated, and one tenant never sees another's
numbers.
"""

import csv
import io
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.models import Project, UsageEvent


def _b(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _project(db_session, ws: dict) -> Project:
    return db_session.get(Project, uuid.UUID(ws["project_id"]))


def _event(project: Project, *, cost: str, saved: str | None, kind: str | None) -> UsageEvent:
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
    return UsageEvent(
        project_id=project.id,
        organization_id=project.organization_id,
        api_key_id=None,
        provider="openai",
        model="gpt-4o-mini",
        operation="chat_completion",
        request_type="chat_completion",
        feature="proxy",
        team="engineering",
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
        # An hour ago: inside the current month-to-date window the endpoint resolves.
        received_at=datetime.now(UTC) - timedelta(hours=1),
        occurred_at=datetime.now(UTC) - timedelta(hours=1),
    )


def _seed_measured(db_session, project: Project) -> None:
    db_session.add_all(
        [
            _event(project, cost="0", saved="6.00", kind="cache"),  # semantic_cache
            _event(project, cost="4.00", saved="2.50", kind="route"),  # smart_routing
            _event(project, cost="1.00", saved="1.50", kind="batch"),  # batching
        ]
    )
    db_session.commit()


def test_snapshot_is_all_null_on_empty_project(client, provision):
    ws = provision(sub="auth0|snap-empty", email="snap-empty@example.com")
    snap = client.get("/v1/dashboard/snapshot", headers=_b(ws["api_key"])).json()

    assert snap["mode"] == "empty"
    assert snap["gross_savings_usd"] is None
    # Verified-savings provenance is null/false on an empty project, never a fake 0.
    assert snap["verified_savings_usd"] is None
    assert snap["direct_measured_usd"] is None
    assert snap["holdback_measured_usd"] is None
    assert snap["holdback_has_signal"] is False
    assert all(kpi["value"] is None for kpi in snap["kpis"])
    assert all(kpi["delta"]["delta_pct"] is None for kpi in snap["kpis"])
    assert snap["savings_trend"] == []
    assert snap["proof_trust"]["score"] is None
    # All five levers are always present; an unconfigured project shows them Off.
    assert {lever["lever"] for lever in snap["levers"]} == {
        "semantic_cache",
        "model_downshift",
        "batching",
        "token_trim",
        "smart_routing",
    }
    assert all(lever["value_usd"] is None for lever in snap["levers"])


def test_snapshot_panels_reconcile(client, db_session, provision):
    ws = provision(sub="auth0|snap-measured", email="snap-measured@example.com")
    _seed_measured(db_session, _project(db_session, ws))

    snap = client.get("/v1/dashboard/snapshot", headers=_b(ws["api_key"]), params={"period": "month"}).json()

    assert snap["mode"] == "measured"
    gross = Decimal(snap["gross_savings_usd"])
    assert gross == Decimal("10.00")

    kpis = {kpi["key"]: kpi for kpi in snap["kpis"]}
    # Footer gross == the gross_saved KPI value.
    assert Decimal(kpis["gross_saved"]["value"]) == gross
    # Net KPI is the hero and carries the fee in its detail copy.
    assert kpis["net_saved"]["tone"] == "brand"
    assert Decimal(kpis["net_saved"]["value"]) == Decimal("7.50")
    assert "25%" in kpis["net_saved"]["detail"]
    assert Decimal(kpis["actual_spend"]["value"]) == Decimal("5.00")
    assert Decimal(kpis["without_varsten"]["value"]) == Decimal("15.00")

    # Sum of the lever rows == gross.
    lever_total = sum((Decimal(lv["value_usd"]) for lv in snap["levers"] if lv["value_usd"] is not None), Decimal("0"))
    assert lever_total == gross
    # Chart series sums to gross (savings) and actual (optimized).
    saved_total = sum((Decimal(b["saved_usd"]) for b in snap["savings_trend"]), Decimal("0"))
    opt_total = sum((Decimal(b["optimized_usd"]) for b in snap["savings_trend"]), Decimal("0"))
    assert saved_total == gross
    assert opt_total == Decimal("5.00")

    # Drivers and proof are populated and tenant-window-scoped.
    assert Decimal(snap["drivers"]["actual_total_usd"]) == Decimal("5.00")
    assert any(row["key"] == "engineering" for row in snap["drivers"]["team"])
    assert snap["proof_trust"]["score"] is not None


def test_snapshot_exposes_verified_savings_at_top_level(client, db_session, provision):
    """The headline 'Saved' figures bind to ledger-measured facts, separated from
    the estimate-derived gross. _seed_measured is all direct-measured (cache 6.00 +
    route 2.50 + batch 1.50), no holdback signal."""
    ws = provision(sub="auth0|snap-verified", email="snap-verified@example.com")
    _seed_measured(db_session, _project(db_session, ws))

    snap = client.get("/v1/dashboard/snapshot", headers=_b(ws["api_key"]), params={"period": "month"}).json()

    assert Decimal(snap["verified_savings_usd"]) == Decimal("10.00")
    assert Decimal(snap["direct_measured_usd"]) == Decimal("10.00")
    assert snap["holdback_measured_usd"] is None
    assert snap["holdback_has_signal"] is False
    # verified == direct + holdback(when signal); here it equals the all-direct gross.
    assert Decimal(snap["verified_savings_usd"]) == Decimal(snap["gross_savings_usd"])


def test_export_carries_verified_savings_section(client, db_session, provision):
    ws = provision(sub="auth0|export-verified", email="export-verified@example.com")
    _seed_measured(db_session, _project(db_session, ws))

    rows = _csv_rows(client.get("/v1/dashboard/export", headers=_b(ws["api_key"])).text)
    assert Decimal(_cell(rows, "verified_savings", 1)) == Decimal("10.00")
    assert Decimal(_cell(rows, "direct_measured", 1)) == Decimal("10.00")
    assert _cell(rows, "holdback_has_signal", 1) == "false"


def test_snapshot_accepts_quarter_and_rejects_unknown_period(client, db_session, provision):
    ws = provision(sub="auth0|snap-period", email="snap-period@example.com")
    _seed_measured(db_session, _project(db_session, ws))

    ok = client.get("/v1/dashboard/snapshot", headers=_b(ws["api_key"]), params={"period": "quarter"})
    assert ok.status_code == 200
    assert ok.json()["granularity"] == "week"

    bad = client.get("/v1/dashboard/snapshot", headers=_b(ws["api_key"]), params={"period": "week"})
    assert bad.status_code == 422


def test_snapshot_is_tenant_isolated(client, db_session, provision):
    a = provision(sub="auth0|snap-a", email="snap-a@example.com")
    b = provision(sub="auth0|snap-b", email="snap-b@example.com")
    _seed_measured(db_session, _project(db_session, a))

    other = client.get("/v1/dashboard/snapshot", headers=_b(b["api_key"])).json()
    # Tenant B has no traffic of its own and sees none of A's savings.
    assert other["mode"] == "empty"
    assert other["gross_savings_usd"] is None


def _csv_rows(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text)))


def _cell(rows: list[list[str]], first_col: str, index: int) -> str:
    for row in rows:
        if row and row[0] == first_col:
            return row[index]
    raise AssertionError(f"row {first_col!r} not found")


def test_export_returns_csv_matching_the_snapshot(client, db_session, provision):
    ws = provision(sub="auth0|export-measured", email="export-measured@example.com")
    _seed_measured(db_session, _project(db_session, ws))

    resp = client.get("/v1/dashboard/export", headers=_b(ws["api_key"]), params={"period": "month"})
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    assert "attachment" in resp.headers["content-disposition"]
    assert "varsten-dashboard-month-" in resp.headers["content-disposition"]

    rows = _csv_rows(resp.text)
    # The export carries the same authoritative figures as the snapshot.
    assert Decimal(_cell(rows, "gross_total", 2)) == Decimal("10.00")
    assert Decimal(_cell(rows, "net_saved", 2)) == Decimal("7.50")


def test_export_has_no_fabricated_numbers_on_empty_project(client, provision):
    ws = provision(sub="auth0|export-empty", email="export-empty@example.com")
    resp = client.get("/v1/dashboard/export", headers=_b(ws["api_key"]))
    assert resp.status_code == 200

    rows = _csv_rows(resp.text)
    # Null money serializes to an empty cell, never a fabricated 0.
    assert _cell(rows, "gross_total", 2) == ""
    assert _cell(rows, "net_saved", 2) == ""


def test_export_is_tenant_isolated(client, db_session, provision):
    a = provision(sub="auth0|export-a", email="export-a@example.com")
    b = provision(sub="auth0|export-b", email="export-b@example.com")
    _seed_measured(db_session, _project(db_session, a))

    rows = _csv_rows(client.get("/v1/dashboard/export", headers=_b(b["api_key"])).text)
    assert _cell(rows, "gross_total", 2) == ""  # B sees none of A's savings
