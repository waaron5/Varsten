"""Demo seeder: isolation guardrails and the cross-dashboard reconciliation.

The seeder's job is to produce a 30-day proxy narrative whose numbers agree across
every Command Center surface. These tests pin the two things that must hold:

  * Isolation: the seeder structurally refuses to touch any org that is not
    is_demo=True, so it can never wipe a real customer tenant.
  * Reconciliation: the Command Center KPI `saved_month`, the Margin chart
    (savings-trend), and the proxy traffic panels all read the same underlying
    ledger savings the attributions claim. No painted-on numbers.

The seeder writes via the sync ORM, so these use the sync db_session + client and
read back through the same session.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select, update

from app.models import Organization, Project, SavingsAttribution
from scripts.seed_demo_tenant import (
    DEMO_ORG_NAME,
    DemoSafetyError,
    assert_demo_org,
    build_demo,
    resolve_demo_org,
    wipe_demo_data,
)

# Small but enough to exercise growth, weekend dips, and a populated current month.
_BASE = 120


def _b(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _in_current_month(date_str: str, now: datetime) -> bool:
    d = datetime.fromisoformat(date_str)
    return d.year == now.year and d.month == now.month


# --- isolation guardrails -----------------------------------------------------


def test_assert_demo_org_refuses_real_tenant(db_session):
    real = Organization(name="Real Customer Inc")  # is_demo defaults to False
    db_session.add(real)
    db_session.flush()
    with pytest.raises(DemoSafetyError):
        assert_demo_org(real)
    with pytest.raises(DemoSafetyError):
        assert_demo_org(None)


def test_wipe_refuses_non_demo_org(db_session):
    real = Organization(name="Real Customer Inc")
    db_session.add(real)
    db_session.flush()

    with pytest.raises(DemoSafetyError):
        wipe_demo_data(db_session, real, Project(organization_id=real.id, name="Real Project"))


def test_resolve_refuses_name_clash_with_real_org(db_session):
    # Robust to a committed demo org already existing in the dev DB (a prior real
    # seed): neutralize any demo-named org inside this rolled-back transaction so the
    # only "Varsten Demo" is the non-demo squatter we add. resolve must then refuse.
    db_session.execute(
        update(Organization).where(Organization.name == DEMO_ORG_NAME).values(name="__neutralized_for_test__")
    )
    db_session.add(Organization(name=DEMO_ORG_NAME))  # is_demo=False
    db_session.flush()
    with pytest.raises(DemoSafetyError):
        resolve_demo_org(db_session)


def test_resolve_creates_demo_org_flagged(db_session):
    org = resolve_demo_org(db_session)
    assert org.is_demo is True
    assert org.name == "Varsten Demo"


# --- reconciliation -----------------------------------------------------------


def test_command_center_reconciles_with_ledger(db_session, client):
    now = datetime.now(UTC)
    result = build_demo(db_session, base_requests=_BASE, now=now)

    cc = client.get("/v1/command-center", headers=_b(result.api_key)).json()
    live = cc["live_savings"]

    # Every headline value is backed by data (no "—" on a seeded tenant).
    assert live["saved_month"] is not None
    assert live["net_saved_month"] is not None
    assert live["annual_run_rate"] is not None
    assert live["trust_score"] is not None

    # The KPI saved_month equals the sum of the per-lever attributions exactly.
    saved_month = Decimal(str(live["saved_month"]))
    assert saved_month == result.expected_saved_month
    assert cc["requests_month"] == result.month_events

    # ... and that figure ties back to the raw ledger savings for the current
    # month (the savings-trend the Margin chart draws), within per-lever cent
    # rounding across the three levers.
    trend = client.get("/v1/metrics/savings-trend", headers=_b(result.api_key)).json()
    assert trend["points"], "Margin chart must not be empty on a seeded tenant"
    month_ledger_saved = sum(
        (Decimal(p["saved_usd"]) for p in trend["points"] if _in_current_month(p["date"], now)),
        Decimal("0"),
    )
    assert abs(month_ledger_saved - saved_month) <= Decimal("0.03")

    # net = gross - Varsten fee.
    net = Decimal(str(live["net_saved_month"]))
    assert net < saved_month


def test_proxy_traffic_panels_are_populated(db_session, client):
    result = build_demo(db_session, base_requests=_BASE)

    pt = client.get("/v1/metrics/proxy-traffic", headers=_b(result.api_key)).json()
    assert pt["requests"] > 0
    assert pt["hit"] > 0 and pt["miss"] > 0
    assert pt["hit_rate"] is not None
    assert pt["latency_p95_ms"] is not None
    assert pt["cache_series"], "hit-rate series must be populated"
    assert pt["latency_series"], "latency series must be populated"
    assert pt["batch_jobs"] > 0
    assert Decimal(pt["batch_saved_usd"]) > 0


def test_active_route_holdback_is_present(db_session, client):
    result = build_demo(db_session, base_requests=_BASE)

    routes = client.get("/v1/engine/routes", headers=_b(result.api_key)).json()
    assert len(routes) == 1
    route = routes[0]
    assert route["incumbent_model"] == "gpt-4o"
    assert route["candidate_model"] == "gpt-4o-mini"
    # Both arms carry traffic this month, so the A/B has something to measure.
    assert route["control_requests"] + route["treatment_requests"] > 0


def test_reseed_is_idempotent(db_session, client):
    first = build_demo(db_session, base_requests=_BASE)
    second = build_demo(db_session, base_requests=_BASE)

    # Deterministic seed: a re-run wipes and regenerates identical data, never stacks.
    assert second.total_events == first.total_events
    assert second.expected_saved_month == first.expected_saved_month

    attributions = db_session.scalars(
        select(SavingsAttribution).where(SavingsAttribution.project_id == second.project_id)
    ).all()
    assert len(attributions) == 3  # one per lever, refreshed not duplicated

    cc = client.get("/v1/command-center", headers=_b(second.api_key)).json()
    assert Decimal(str(cc["live_savings"]["saved_month"])) == second.expected_saved_month
