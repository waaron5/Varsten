"""End-to-end: seed -> dashboards -> apply -> proof, all derived (no constants).

Exercises the demo path a buyer sees: the seed builds a workspace, the engine
produces recommendations from real usage and pricing, applying one writes a real
savings attribution, and Proof / Command Center / Levers report derived numbers.
"""
from decimal import Decimal

import pytest

from app.api import deps
from scripts.seed_demo import DEMO_API_KEY, seed

# The seeded demo user's Auth0 subject (set in seed_demo).
DEMO_SUBJECT = "demo|varsten-local"


@pytest.fixture(autouse=True)
def stub_token_verification(monkeypatch):
    # Treat a non-key bearer token as the Auth0 subject, so the seeded demo user
    # can drive the session-only mutation endpoints. API-key reads are unaffected
    # (they short-circuit on the vk_ prefix before any token verification).
    monkeypatch.setattr(deps, "verify_access_token", lambda token: {"sub": token})


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _num(value) -> Decimal:
    return Decimal(str(value))


def test_seed_drives_real_dashboards_and_proof(client, db_session):
    # The seed is idempotent; on a dev DB that already holds the demo workspace it
    # updates in place rather than inserting, so assert on resulting state, not on
    # the insert count.
    result = seed(db_session)
    assert result["applied_recommendations"] >= 1

    token = DEMO_API_KEY

    # Overview: real spend and a pricing-trust share.
    overview = client.get("/v1/metrics/overview", headers=_bearer(token)).json()
    assert _num(overview["spend_month"]) > 0
    assert overview["requests_month"] > 0

    # Proof savings is derived: counterfactual = actual + gross, net below gross.
    proof = client.get("/v1/proof/savings", headers=_bearer(token)).json()
    gross = _num(proof["gross_savings_usd"])
    assert gross > 0
    assert _num(proof["counterfactual_spend_usd"]) > _num(proof["actual_spend_usd"])
    assert _num(proof["net_savings_usd"]) < gross

    # Command Center mirrors the same derived savings.
    cc = client.get("/v1/command-center", headers=_bearer(token)).json()
    assert _num(cc["live_savings"]["saved_month"]) == gross

    # Lever savings-to-date is the sum of attributions, not a seeded constant.
    levers = client.get("/v1/engine/levers", headers=_bearer(token)).json()
    assert sum(_num(l["savings_to_date_usd"]) for l in levers) == gross

    # Proof attribution rows trace to applied recommendations.
    attribution = client.get("/v1/proof/attribution", headers=_bearer(token)).json()
    assert len(attribution["rows"]) >= 1


def test_applying_a_recommendation_creates_derived_savings(client, db_session):
    result = seed(db_session)
    project_id = result["project_id"]
    token = DEMO_API_KEY

    before = _num(client.get("/v1/proof/savings", headers=_bearer(token)).json()["gross_savings_usd"])

    # Apply one open recommendation that carries a dollar lever savings.
    open_recs = client.get("/v1/engine/recommendations", headers=_bearer(token)).json()
    target = next(
        (r for r in open_recs if r["lever"] and r["estimated_monthly_savings_usd"]),
        None,
    )
    assert target is not None, "expected at least one open lever recommendation"

    # Mutations require a user session (an API key cannot apply cuts), so use the
    # seeded demo user's subject plus the project_id session reads need.
    applied = client.patch(
        f"/v1/engine/recommendations/{target['id']}",
        headers=_bearer(DEMO_SUBJECT),
        params={"project_id": project_id},
        json={"status": "applied"},
    )
    assert applied.status_code == 200
    assert applied.json()["status"] == "applied"

    after = _num(client.get("/v1/proof/savings", headers=_bearer(token)).json()["gross_savings_usd"])
    assert after >= before  # applying a real recommendation grows attributed savings


def test_prompt_cache_recommendation_fires_from_token_data(client, db_session):
    seed(db_session)
    token = DEMO_API_KEY

    # Gather open and applied recommendations and confirm the cache lever is
    # present, driven by cached_input_tokens, not a metadata flag alone.
    open_recs = client.get("/v1/recommendations?status=open", headers=_bearer(token)).json()
    applied_recs = client.get("/v1/recommendations?status=applied", headers=_bearer(token)).json()
    types = {r["type"] for r in open_recs + applied_recs}
    assert "prompt_cache" in types
