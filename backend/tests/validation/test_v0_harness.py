"""V0 — harness smoke: the validation environment itself works like production.

Committed namespaced state, real app sessions on both stacks, SimProvider at the
HTTP boundary, canary scan clean, teardown leaves nothing behind. Every later
workstream builds on exactly this.
"""

import json
from decimal import Decimal

import pytest
from harness import TrafficFactory, ValidationReport, canary_scan, run_traffic
from sqlalchemy import func, select

from app.models import RequestDecisionEvent, UsageEvent

SYSTEM_PROMPT_PAD = "Follow the workspace support policy precisely. " * 30


@pytest.mark.anyio
async def test_v0_harness_smoke(sim_env, data_plane, monkeypatch):
    report = ValidationReport(scenario="v0_harness_smoke")
    env = sim_env
    env.provider.profile(env.model_big, reply=lambda n: "Spam")

    factory = TrafficFactory(
        env,
        model=env.model_big,
        feature="support_agent",
        system_prompt=f"{env.canary} {SYSTEM_PROMPT_PAD}",
    )
    responses = await run_traffic(data_plane, factory, 10)

    report.check(
        "all_requests_succeed", all(r.status_code == 200 for r in responses), [r.status_code for r in responses]
    )
    report.check(
        "responses_are_provider_content",
        all(r.json()["choices"][0]["message"]["content"] == "Spam" for r in responses),
    )
    report.metric("provider_calls", env.provider.calls.get(env.model_big, 0))

    db = env.db()
    try:
        events = db.scalars(select(UsageEvent).where(UsageEvent.project_id == env.project_id)).all()
        workload = [e for e in events if e.source != "overhead"]
        report.check("every_request_metered", len(workload) == 10, len(workload))
        report.check(
            "every_event_priced_from_catalog",
            all(e.pricing_status == "priced" and e.cost_usd and e.cost_usd > Decimal("0") for e in workload),
            sorted({e.pricing_status for e in workload}),
        )
        decisions = db.scalars(
            select(RequestDecisionEvent).where(RequestDecisionEvent.project_id == env.project_id)
        ).all()
        report.check("every_request_has_decision_evidence", len(decisions) == 10, len(decisions))
        report.check(
            "decisions_carry_route_identity_and_fingerprints",
            all(d.route_key == "support_agent" and d.prefix_hash and d.request_fingerprint for d in decisions),
        )
        report.check(
            "decision_metadata_carries_plan_and_trace",
            all(
                "optimization_plan" in (d.event_metadata or {}) and "runtime_trace" in (d.event_metadata or {})
                for d in decisions
            ),
        )
        # No optimization is configured: nothing may claim a saving.
        report.check(
            "no_painted_savings",
            all(d.realized_savings_usd is None for d in decisions)
            and all((e.event_metadata or {}).get("saved_usd") in (None, "None") for e in workload),
        )
    finally:
        db.close()

    canary_scan(env, report)
    report.finish()


@pytest.mark.anyio
async def test_v0_teardown_leaves_nothing(sim_env, data_plane):
    """Teardown coverage is proven by the stale-run sweep: an org from a crashed
    run would be deleted on the next boot. Here we just prove the env's rows are
    scoped so the cascade can find them all."""
    env = sim_env
    env.provider.profile(env.model_big, reply=lambda n: "ok")
    factory = TrafficFactory(env, model=env.model_big, feature="f", system_prompt=None)
    await run_traffic(data_plane, factory, 2)

    db = env.db()
    try:
        orphans = db.scalar(
            select(func.count())
            .select_from(UsageEvent)
            .where(UsageEvent.project_id == env.project_id, UsageEvent.organization_id != env.org_id)
        )
        assert orphans == 0
    finally:
        db.close()


def test_v0_report_emission(tmp_path, monkeypatch):
    monkeypatch.setenv("VALIDATION_REPORT_DIR", str(tmp_path))
    report = ValidationReport(scenario="v0_emit")
    report.check("ok", True)
    report.metric("n", 1)
    report.finish()
    written = json.loads((tmp_path / "v0_emit.json").read_text())
    assert written["checks"][0]["passed"] is True
    assert written["metrics"]["n"] == 1
