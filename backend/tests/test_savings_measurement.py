"""Measured savings derived from the ledger: direct (cache/batch/route) and the
holdback A/B with a confidence interval. These prove the auditable "verified"
number is real arithmetic on recorded facts, not an estimate, and that the Proof
endpoint exposes it only on Pro and never calls an estimate "saved".
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from app.auth.entitlements import invalidate_plan_tier
from app.models import PLAN_PERFORMANCE, Organization, Project, Recommendation, UsageEvent
from app.proxy.routing import ARM_CONTROL, ARM_TREATMENT, SMART_ROUTING
from app.savings import month_start, record_applied_savings
from app.savings_measurement import (
    LEVER_BATCHING,
    LEVER_SEMANTIC_CACHE,
    MEASURED_METHODS,
    METHOD_DIRECT_MEASURED,
    METHOD_ESTIMATED,
    METHOD_HOLDBACK_MEASURED,
    compute_verified_savings,
    direct_measured_by_lever,
    holdback_measured,
    is_measured,
)


def _event(db, project_id, org_id, *, cost, metadata, at=None):
    db.add(
        UsageEvent(
            project_id=project_id,
            organization_id=org_id,
            provider="openai",
            model="gpt-4o-mini",
            operation="chat_completion",
            request_type="chat_completion",
            feature="proxy",
            environment="production",
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            cost_usd=Decimal(str(cost)),
            cost_source="catalog",
            pricing_status="priced",
            currency="USD",
            status="success",
            success=True,
            event_metadata=metadata,
            received_at=at or datetime.now(UTC),
            occurred_at=at or datetime.now(UTC),
        )
    )
    db.commit()


def _ids(provision):
    p = provision(sub="auth0|measure", email="measure@example.com")
    return uuid.UUID(p["project_id"]), uuid.UUID(p["org_id"]), p


def test_is_measured_vocabulary():
    assert is_measured(METHOD_DIRECT_MEASURED)
    assert is_measured(METHOD_HOLDBACK_MEASURED)
    assert not is_measured(METHOD_ESTIMATED)
    assert not is_measured(None)
    assert METHOD_DIRECT_MEASURED in MEASURED_METHODS


def test_direct_measured_sums_cache_batch_and_direct_routing(client, db_session, provision):
    project_id, org_id, _ = _ids(provision)
    start = month_start(datetime.now(UTC))
    end = start.replace(year=start.year + 1)

    # Cache hit: avoided the model price outright.
    _event(db_session, project_id, org_id, cost=0, metadata={"proxy": True, "cache": "hit", "saved_usd": "2.00"})
    # Batch: contractual discount on identical tokens.
    _event(
        db_session,
        project_id,
        org_id,
        cost="1.00",
        metadata={"proxy": True, "batch": True, "lever": "batching", "saved_usd": "1.50"},
    )
    # Direct route (NOT a holdback): paid the candidate instead of the incumbent.
    _event(
        db_session,
        project_id,
        org_id,
        cost="0.25",
        metadata={"proxy": True, "cache": "miss", "routed": True, "saved_usd": "0.75"},
    )
    # A holdback treatment route also records saved_usd but must NOT be counted as
    # direct routing (the holdback math owns it), or it would double-count.
    _event(
        db_session,
        project_id,
        org_id,
        cost="0.25",
        metadata={"proxy": True, "routed": True, "holdback": True, "saved_usd": "9.99"},
    )

    by_lever = direct_measured_by_lever(db_session, project_id, start, end)
    assert by_lever[LEVER_SEMANTIC_CACHE] == Decimal("2.00")
    assert by_lever[LEVER_BATCHING] == Decimal("1.50")
    assert by_lever[SMART_ROUTING] == Decimal("0.75")  # the holdback 9.99 is excluded


def test_holdback_measured_has_confidence_interval(client, db_session, provision):
    project_id, org_id, _ = _ids(provision)
    start = month_start(datetime.now(UTC))

    pair = {"holdback": True, "experiment_from": "gpt-4o", "experiment_to": "gpt-4o-mini"}
    # Control arm stays on the incumbent; treatment is routed to the lower-cost candidate.
    for cost in ("0.100", "0.120", "0.110", "0.105"):
        _event(db_session, project_id, org_id, cost=cost, metadata={**pair, "arm": ARM_CONTROL})
    for cost in ("0.040", "0.050", "0.045", "0.042"):
        _event(
            db_session,
            project_id,
            org_id,
            cost=cost,
            metadata={**pair, "arm": ARM_TREATMENT, "routed": True, "saved_usd": "0.06"},
        )

    result = holdback_measured(db_session, project_id, start)
    assert result["total_usd"] > Decimal("0")
    # A real CI, not a hardcoded band: low < point estimate < high.
    assert result["ci_low_usd"] < result["total_usd"] < result["ci_high_usd"]
    assert len(result["experiments"]) == 1


def test_compute_verified_combines_direct_and_holdback(client, db_session, provision):
    project_id, org_id, _ = _ids(provision)
    start = month_start(datetime.now(UTC))
    end = start.replace(year=start.year + 1)

    _event(db_session, project_id, org_id, cost=0, metadata={"proxy": True, "cache": "hit", "saved_usd": "3.00"})
    pair = {"holdback": True, "experiment_from": "gpt-4o", "experiment_to": "gpt-4o-mini"}
    for cost in ("0.100", "0.120"):
        _event(db_session, project_id, org_id, cost=cost, metadata={**pair, "arm": ARM_CONTROL})
    for cost in ("0.040", "0.050"):
        _event(db_session, project_id, org_id, cost=cost, metadata={**pair, "arm": ARM_TREATMENT, "routed": True})
    _event(db_session, project_id, org_id, cost="0.25", metadata={"overhead": "eval_replay"})

    verified = compute_verified_savings(db_session, project_id, start, end)
    assert verified["direct_measured_usd"] == Decimal("3.00")
    assert verified["holdback_measured_usd"] > Decimal("0")
    assert verified["measurement_cost_usd"] > Decimal("0")
    assert verified["optimization_overhead_cost_usd"] == Decimal("0.25")
    assert verified["verified_gross_savings_usd"] == verified["direct_measured_usd"] + verified["holdback_measured_usd"]
    assert verified["verified_savings_usd"] == (
        verified["verified_gross_savings_usd"]
        - verified["measurement_cost_usd"]
        - verified["optimization_overhead_cost_usd"]
    )


def test_estimated_savings_attribution_has_no_fabricated_confidence_band(client, db_session, provision):
    project_id, _, _ = _ids(provision)
    project = db_session.get(Project, project_id)
    rec = Recommendation(
        organization_id=project.organization_id,
        project_id=project.id,
        dedupe_key=f"rec-{uuid.uuid4()}",
        type="model_downshift",
        lever="model_downshift",
        title="Route cheaper model",
        description="x",
        estimated_monthly_savings_usd=Decimal("100.00"),
        measurement_method=METHOD_ESTIMATED,
        risk_level="medium",
        confidence="medium",
    )
    db_session.add(rec)
    db_session.flush()

    attr = record_applied_savings(db_session, project, rec)

    assert attr is not None
    assert attr.status == "estimated"
    assert attr.confidence_low_usd is None
    assert attr.confidence_high_usd is None


def test_proof_endpoint_hides_verified_on_free_and_never_calls_estimate_saved(client, db_session, provision):
    _, _, p = _ids(provision)
    # Base workspace: no verified block, Base note.
    body = client.get("/v1/proof/savings", headers={"Authorization": f"Bearer {p['api_key']}"}).json()
    assert body["plan_tier"] == "free"
    assert "verified" not in body
    assert "estimated" in body
    assert "Base" in body["measurement_note"].lower()


def test_proof_endpoint_exposes_verified_on_performance(client, db_session, provision):
    project_id, org_id, p = _ids(provision)
    _event(db_session, project_id, org_id, cost=0, metadata={"proxy": True, "cache": "hit", "saved_usd": "4.25"})

    org = db_session.get(Organization, org_id)
    org.plan_tier = PLAN_PERFORMANCE
    db_session.commit()
    invalidate_plan_tier()

    body = client.get("/v1/proof/savings", headers={"Authorization": f"Bearer {p['api_key']}"}).json()
    assert body["plan_tier"] == "performance"
    assert Decimal(str(body["verified"]["verified_savings_usd"])) == Decimal("4.25")
    assert Decimal(str(body["verified"]["verified_gross_savings_usd"])) == Decimal("4.25")
    assert Decimal(str(body["verified"]["measurement_cost_usd"])) == Decimal("0.00")
    assert Decimal(str(body["verified"]["optimization_overhead_cost_usd"])) == Decimal("0.00")
    assert Decimal(str(body["verified"]["direct_measured_usd"])) == Decimal("4.25")
    # Estimated and verified are distinct, labeled buckets.
    assert "estimated" in body["estimated"]["label"].lower()
    assert "verified" in body["verified"]["label"].lower()
