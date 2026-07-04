"""V6 — multi-tenant scoping and concurrency hardening.

Two tenants on the same models must be perfectly isolated (a real client is on
the line: cross-tenant leakage is a hard stop per CLAUDE.md), and the engine's
draws, sweeps, and rollbacks must hold their invariants under parallel load and
racing control-plane actions.
"""

import asyncio
import json
import random
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from harness import (
    _SCAN_MODELS,
    TrafficFactory,
    ValidationReport,
    canary_scan,
    create_sim_env,
    run_traffic,
    teardown_sim_env,
)
from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models import ProxyPolicy, Recommendation, RecommendationAction, RequestDecisionEvent, UsageEvent
from app.proxy import drift as drift_mod
from app.proxy import experiment as experiment_mod
from app.savings import month_start

BIG_SYSTEM = "Apply the support policy rules in order, without exception. " * 25


def _routing_policy(db, env, *, rec=None, holdback="0.3"):
    policy = ProxyPolicy(
        organization_id=env.org_id,
        project_id=env.project_id,
        lever="model_downshift",
        target_type="model",
        target_key=env.model_big,
        params={"candidate_model": env.model_small},
        enabled=True,
        holdback_percent=Decimal(holdback),
        rollout_percent=100,
        source_recommendation_id=rec.id if rec else None,
    )
    db.add(policy)
    db.commit()
    return policy


def _cross_tenant_scan(victim_env, other_canary: str, report: ValidationReport) -> None:
    """Nothing carrying the OTHER tenant's canary may exist in this tenant's rows."""
    db = victim_env.db()
    leaks = []
    try:
        for model in _SCAN_MODELS:
            column = getattr(model, "project_id", None) or model.organization_id
            scope = victim_env.project_id if hasattr(model, "project_id") else victim_env.org_id
            for row in db.scalars(select(model).where(column == scope)).all():
                blob = json.dumps({c.name: getattr(row, c.name, None) for c in model.__table__.columns}, default=str)
                if other_canary in blob:
                    leaks.append(f"{model.__tablename__}:{getattr(row, 'id', '?')}")
    finally:
        db.close()
    report.check("no_cross_tenant_content", not leaks, leaks or "clean")


@pytest.mark.anyio
async def test_v6_two_tenants_fully_isolated(sim_env, data_plane, monkeypatch):
    report = ValidationReport(scenario="v6_tenant_isolation")
    env_a = sim_env
    # Second tenant shares the provider transport (same mocked upstream), with
    # its own org, models, and canary. Torn down here, not by the fixture.
    env_b = create_sim_env(env_a.provider, sweep_stale=False)
    try:
        env_a.provider.profile(env_a.model_big, reply=lambda n: "Spam")
        env_a.provider.profile(env_b.model_big, reply=lambda n: "Ham")
        from app.core.config import settings

        monkeypatch.setattr(
            settings, "proxy_openai_keys", {str(env_a.project_id): "sk-a", str(env_b.project_id): "sk-b"}
        )

        factory_a = TrafficFactory(env_a, model=env_a.model_big, feature="support_agent", system_prompt=BIG_SYSTEM)
        factory_b = TrafficFactory(env_b, model=env_b.model_big, feature="support_agent", system_prompt=BIG_SYSTEM)
        # Interleave the tenants' traffic.
        for _ in range(10):
            body_a, headers_a = factory_a.next_request()
            body_b, headers_b = factory_b.next_request()
            ra = await data_plane.post("/v1/chat/completions", headers=headers_a, json=body_a)
            rb = await data_plane.post("/v1/chat/completions", headers=headers_b, json=body_b)
            assert ra.status_code == 200 and rb.status_code == 200

        db = env_a.db()
        try:
            for env, expected in ((env_a, 10), (env_b, 10)):
                events = db.scalar(
                    select(func.count()).select_from(UsageEvent).where(UsageEvent.project_id == env.project_id)
                )
                report.check(f"tenant_{env.run_id}_event_count_exact", events == expected, events)
            # A's key cannot read B's project through the control plane.
            foreign = env_a.control.get(
                "/v1/engine/recommendations",
                headers=env_a.auth(),
                params={"project_id": str(env_b.project_id)},
            )
            report.check(
                "control_plane_rejects_foreign_project", foreign.status_code in (403, 404), foreign.status_code
            )
        finally:
            db.close()

        _cross_tenant_scan(env_a, env_b.canary, report)
        _cross_tenant_scan(env_b, env_a.canary, report)
        canary_scan(env_a, report)
    finally:
        teardown_sim_env(env_b)
    report.finish()


@pytest.mark.anyio
async def test_v6_parallel_traffic_keeps_ledger_exact(sim_env, data_plane, monkeypatch):
    """30 concurrent requests against one live policy: every request succeeds,
    every request is metered exactly once, and every draw stays consistent."""
    report = ValidationReport(scenario="v6_parallel_traffic")
    env = sim_env
    random.seed(20260704)
    env.provider.profile(env.model_big, reply=lambda n: "Spam")
    env.provider.profile(env.model_small, reply=lambda n: "Spam")

    db = env.db()
    try:
        _routing_policy(db, env)
        factory = TrafficFactory(env, model=env.model_big, feature="support_agent", system_prompt=BIG_SYSTEM)
        requests = [factory.next_request() for _ in range(30)]
        responses = await asyncio.gather(
            *(data_plane.post("/v1/chat/completions", headers=h, json=b) for b, h in requests)
        )
        report.check("all_parallel_requests_succeed", all(r.status_code == 200 for r in responses))

        events = db.scalars(select(UsageEvent).where(UsageEvent.project_id == env.project_id)).all()
        report.check("exactly_once_metering", len(events) == 30, len(events))
        decisions = db.scalars(
            select(RequestDecisionEvent).where(RequestDecisionEvent.project_id == env.project_id)
        ).all()
        report.check("exactly_once_decisions", len(decisions) == 30, len(decisions))
        arms = {(e.event_metadata or {}).get("arm") for e in events}
        report.check("arms_are_valid_under_concurrency", arms <= {"control", "treatment", None}, arms)
        canary_scan(env, report)
    finally:
        db.close()
    report.finish()


@pytest.mark.anyio
async def test_v6_rollback_racing_traffic_stays_consistent(sim_env, data_plane, monkeypatch):
    """A drift rollback firing while treatment traffic is in flight must leave a
    consistent end state: requests all succeed, and once the policy is disabled
    the recommendation agrees with it."""
    report = ValidationReport(scenario="v6_rollback_race")
    env = sim_env
    random.seed(9)
    monkeypatch.setattr(drift_mod, "MIN_ARM_SAMPLES", 8)
    monkeypatch.setattr(experiment_mod, "MIN_ARM_SAMPLES", 8)
    env.provider.profile(env.model_big, reply=lambda n: "Spam")
    env.provider.profile(env.model_small, reply=lambda n: "")  # degraded candidate

    db = env.db()
    try:
        rec = Recommendation(
            organization_id=env.org_id,
            project_id=env.project_id,
            dedupe_key=f"v6-{env.run_id}",
            type="model_downshift",
            lever="model_downshift",
            title="v6 race",
            description="x",
            risk_level="medium",
            confidence="medium",
            related_model=env.model_big,
        )
        db.add(rec)
        db.commit()
        policy = _routing_policy(db, env, rec=rec, holdback="0.35")
        factory = TrafficFactory(env, model=env.model_big, feature="support_agent", system_prompt=BIG_SYSTEM)
        await run_traffic(data_plane, factory, 40)  # accrue degraded evidence

        from app.models import Project

        def sweep_in_thread():
            session = SessionLocal()
            try:
                project = session.get(Project, env.project_id)
                return drift_mod.check_and_rollback_drift(session, project, month_start(datetime.now(UTC)))
            finally:
                session.close()

        # Fire the sweep concurrently with another traffic burst.
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            sweep_future = loop.run_in_executor(pool, sweep_in_thread)
            responses = await run_traffic(data_plane, factory, 15)
            rolled = await sweep_future

        report.check("traffic_survives_concurrent_rollback", all(r.status_code == 200 for r in responses))
        report.check("rollback_fired", bool(rolled))
        db.expire_all()
        report.check(
            "policy_and_recommendation_agree_after_race",
            policy.enabled is False and db.get(Recommendation, rec.id).status == "rolled_back",
            {"policy_enabled": policy.enabled, "rec": db.get(Recommendation, rec.id).status},
        )
        # After the rollback, no new treatment traffic reaches the candidate.
        before = env.provider.calls.get(env.model_small, 0)
        await run_traffic(data_plane, factory, 10)
        report.check("no_exposure_after_race", env.provider.calls.get(env.model_small, 0) == before)
        canary_scan(env, report)
    finally:
        db.close()
    report.finish()


@pytest.mark.anyio
async def test_v6_two_sweeps_racing_roll_back_exactly_once_effectively(sim_env, data_plane, monkeypatch):
    """Two drift sweeps racing on separate sessions (the no-advisory-lock worst
    case): the policy must end disabled with the recommendation consistent; any
    duplicate system-action rows are reported as a metric, not hidden."""
    report = ValidationReport(scenario="v6_sweep_race")
    env = sim_env
    random.seed(4)
    monkeypatch.setattr(drift_mod, "MIN_ARM_SAMPLES", 8)
    monkeypatch.setattr(experiment_mod, "MIN_ARM_SAMPLES", 8)
    env.provider.profile(env.model_big, reply=lambda n: "Spam")
    env.provider.profile(env.model_small, reply=lambda n: "")

    db = env.db()
    try:
        rec = Recommendation(
            organization_id=env.org_id,
            project_id=env.project_id,
            dedupe_key=f"v6b-{env.run_id}",
            type="model_downshift",
            lever="model_downshift",
            title="v6 sweep race",
            description="x",
            risk_level="medium",
            confidence="medium",
            related_model=env.model_big,
        )
        db.add(rec)
        db.commit()
        policy = _routing_policy(db, env, rec=rec, holdback="0.35")
        factory = TrafficFactory(env, model=env.model_big, feature="support_agent", system_prompt=BIG_SYSTEM)
        await run_traffic(data_plane, factory, 40)

        from app.models import Project

        def sweep():
            session = SessionLocal()
            try:
                project = session.get(Project, env.project_id)
                return drift_mod.check_and_rollback_drift(session, project, month_start(datetime.now(UTC)))
            finally:
                session.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: sweep(), range(2)))

        db.expire_all()
        report.check("at_least_one_sweep_rolled_back", any(results), [len(r) for r in results])
        report.check("policy_disabled_exactly", policy.enabled is False)
        report.check("recommendation_consistent", db.get(Recommendation, rec.id).status == "rolled_back")
        actions = db.scalar(
            select(func.count())
            .select_from(RecommendationAction)
            .where(
                RecommendationAction.project_id == env.project_id,
                RecommendationAction.action_type == "rolled_back",
            )
        )
        # The production guard against double-logging is the scheduler's advisory
        # lock; without it a duplicate action row is possible and is REPORTED.
        report.metric("rollback_action_rows", actions)
        report.check("no_runaway_duplicate_actions", (actions or 0) <= 2, actions)
        canary_scan(env, report)
    finally:
        db.close()
    report.finish()
