"""V4 — fail-open / chaos battery.

The single invariant: the client's request succeeds (or receives the provider's
own faithful error), never hangs, and never fails because of Varsten's
optimization machinery. Faults are injected both *inside* documented fail-open
guards (infra failures) and *at* the resolver seams (bugs in our own code) —
the philosophy says both classes must cost savings, never traffic.
"""

import random
import uuid
from decimal import Decimal

import pytest
from harness import TrafficFactory, ValidationReport, canary_scan, run_traffic
from sqlalchemy import func, select

from app.core.config import settings
from app.models import ProxyPolicy, RequestDecisionEvent, UsageEvent
from app.proxy import cache as cache_mod
from app.proxy import compression as compression_mod
from app.proxy import router as router_mod
from app.proxy import routing as routing_mod
from app.proxy import trim as trim_mod

BIG_SYSTEM = "Apply the support policy rules in order. " * 30


def _routing_policy(db, env):
    policy = ProxyPolicy(
        organization_id=env.org_id,
        project_id=env.project_id,
        lever="model_downshift",
        target_type="model",
        target_key=env.model_big,
        params={"candidate_model": env.model_small},
        enabled=True,
        holdback_percent=Decimal("0.2"),
        rollout_percent=100,
    )
    db.add(policy)
    db.commit()
    return policy


def _boom(*args, **kwargs):
    raise RuntimeError("chaos: injected failure")


async def _aboom(*args, **kwargs):
    raise RuntimeError("chaos: injected failure")


# Each fault: (name, apply(monkeypatch) -> None, with_routing_policy). Both
# infra-level (inside the guard) and seam-level (the resolver itself is buggy)
# classes are represented. Trim/compression resolvers only run when no routing
# policy matches, so their faults run without one — otherwise the pass is vacuous.
FAULTS = [
    ("exact_cache_lookup_infra", lambda mp: mp.setattr(cache_mod, "get_cached", _aboom), True),
    ("routing_db_infra", lambda mp: mp.setattr(routing_mod, "_routing_policy_for_model", _aboom), True),
    ("routing_resolver_bug", lambda mp: mp.setattr(routing_mod, "resolve_route", _aboom), True),
    ("trim_resolver_bug", lambda mp: mp.setattr(trim_mod, "resolve_trim", _aboom), False),
    ("compression_resolver_bug", lambda mp: mp.setattr(compression_mod, "resolve_compression", _aboom), False),
    ("planner_bug", lambda mp: mp.setattr(router_mod, "build_observe_only_plan", _boom), True),
    ("priors_bug", lambda mp: mp.setattr(router_mod, "outcome_priors_for_request", _aboom), True),
    ("evidence_write_bug", lambda mp: mp.setattr(router_mod, "record_request_decision", _aboom), True),
    ("ledger_write_bug", lambda mp: mp.setattr(router_mod, "record_proxy_usage", _aboom), True),
    ("bandit_stats_bug", lambda mp: mp.setattr(routing_mod, "candidate_stats_for_request", _aboom), True),
]


@pytest.mark.anyio
@pytest.mark.parametrize("fault_name,apply_fault,with_routing_policy", FAULTS, ids=[f[0] for f in FAULTS])
async def test_v4_fail_open_matrix(sim_env, data_plane, monkeypatch, fault_name, apply_fault, with_routing_policy):
    """With each subsystem broken in turn, every request must still succeed with
    real provider content."""
    report = ValidationReport(scenario=f"v4_fail_open_{fault_name}")
    env = sim_env
    random.seed(20260704)
    env.provider.profile(env.model_big, reply=lambda n: "Spam")
    env.provider.profile(env.model_small, reply=lambda n: "Spam")

    db = env.db()
    try:
        if with_routing_policy:
            _routing_policy(db, env)
        apply_fault(monkeypatch)

        big = TrafficFactory(env, model=env.model_big, feature="support_agent", system_prompt=BIG_SYSTEM)
        responses = await run_traffic(data_plane, big, 6)

        report.check(
            "requests_survive_fault",
            all(r.status_code == 200 for r in responses),
            [r.status_code for r in responses],
        )
        report.check(
            "responses_are_real_provider_content",
            all(r.json()["choices"][0]["message"]["content"] == "Spam" for r in responses),
        )

        # Bookkeeping loss is measured, not hidden: broken evidence/ledger writes
        # cost telemetry, never traffic.
        events = db.scalar(select(func.count()).select_from(UsageEvent).where(UsageEvent.project_id == env.project_id))
        decisions = db.scalar(
            select(func.count())
            .select_from(RequestDecisionEvent)
            .where(RequestDecisionEvent.project_id == env.project_id)
        )
        report.metric("usage_events_recorded", events)
        report.metric("decision_events_recorded", decisions)
        report.metric("evidence_loss", 6 - (decisions or 0))

        canary_scan(env, report)
    finally:
        db.close()
    report.finish()


@pytest.mark.anyio
async def test_v4_poisoned_policy_params(sim_env, data_plane, monkeypatch):
    """Malformed policy state (bad shapes, dangling ids) must degrade to
    passthrough, never to an error."""
    report = ValidationReport(scenario="v4_poisoned_params")
    env = sim_env
    random.seed(3)
    monkeypatch.setattr(settings, "bandit_routing_mode", "active")
    env.provider.profile(env.model_big, reply=lambda n: "Spam")
    env.provider.profile(env.model_help, reply=lambda n: "Spam")

    db = env.db()
    try:
        # Routing policy with no candidate + garbage bandit set.
        db.add(
            ProxyPolicy(
                organization_id=env.org_id,
                project_id=env.project_id,
                lever="model_downshift",
                target_type="model",
                target_key=env.model_big,
                params={"candidate_model": None, "bandit_candidates": "not-a-list"},
                enabled=True,
                rollout_percent=100,
            )
        )
        # Compression policy pointing at a nonexistent artifact.
        db.add(
            ProxyPolicy(
                organization_id=env.org_id,
                project_id=env.project_id,
                lever="prompt_compression",
                target_type="model",
                target_key=env.model_help,
                params={"artifact_id": str(uuid.uuid4())},
                enabled=True,
                holdback_percent=Decimal("0"),
                rollout_percent=100,
            )
        )
        db.commit()

        big = TrafficFactory(env, model=env.model_big, feature="support_agent", system_prompt=BIG_SYSTEM)
        help_ = TrafficFactory(env, model=env.model_help, feature="faq", system_prompt="Help. " * 200)
        responses = await run_traffic(data_plane, big, 4)
        responses += await run_traffic(data_plane, help_, 4)

        report.check("requests_survive_poisoned_params", all(r.status_code == 200 for r in responses))
        # The upstream saw the ORIGINAL bodies: nothing was routed or substituted.
        report.check(
            "no_optimization_applied_from_poisoned_state",
            env.provider.calls.get(env.model_small, 0) == 0
            and all(
                b["messages"][0]["content"].startswith("Help. ")
                for b in env.provider.bodies
                if b["model"] == env.model_help
            ),
        )
        canary_scan(env, report)
    finally:
        db.close()
    report.finish()


@pytest.mark.anyio
async def test_v4_upstream_error_storm_is_relayed_faithfully(sim_env, data_plane, monkeypatch):
    """Provider 500s are the provider's problem: after retries the proxy relays
    the provider's own error body, and once the breaker trips it fails fast with
    an honestly-labeled Varsten 503 — never a fake success, never a hang."""
    report = ValidationReport(scenario="v4_upstream_storm")
    env = sim_env
    monkeypatch.setattr(settings, "proxy_retry_base_delay_seconds", 0.0)
    monkeypatch.setattr(settings, "proxy_retry_max_delay_seconds", 0.0)
    monkeypatch.setattr(settings, "circuit_breaker_fail_threshold", 3)
    env.provider.profile(env.model_big, fail=lambda n: (500, {"error": {"message": "sim upstream exploded"}}))

    big = TrafficFactory(env, model=env.model_big, feature="support_agent", system_prompt=BIG_SYSTEM)
    statuses: list[tuple[int, str | None]] = []
    for _ in range(6):
        body, headers = big.next_request()
        response = await data_plane.post("/v1/chat/completions", headers=headers, json=body)
        statuses.append((response.status_code, response.headers.get("x-varsten-origin")))

    relayed = [s for s in statuses if s[0] == 500]
    breaker_fast_fails = [s for s in statuses if s[0] == 503]
    report.metric("statuses", statuses)
    report.check("provider_errors_relayed_before_trip", len(relayed) >= 1, statuses)
    report.check("breaker_fails_fast_after_trip", len(breaker_fast_fails) >= 1, statuses)
    report.check(
        "every_failure_class_is_honestly_labeled",
        all(s in {500, 503} for s, _ in statuses),
        statuses,
    )
    canary_scan(env, report)
    report.finish()


@pytest.mark.anyio
async def test_v4_fallback_keeps_request_alive(sim_env, data_plane, monkeypatch):
    """Primary model down + configured degradation model up: the request is
    served by the fallback, labeled as a fallback, and claims zero savings."""
    report = ValidationReport(scenario="v4_fallback")
    env = sim_env
    monkeypatch.setattr(settings, "proxy_retry_base_delay_seconds", 0.0)
    monkeypatch.setattr(settings, "proxy_retry_max_delay_seconds", 0.0)
    monkeypatch.setattr(settings, "proxy_fallback_models", {str(env.project_id): env.model_small})
    monkeypatch.setattr(settings, "circuit_breaker_fail_threshold", 1000)
    env.provider.profile(env.model_big, fail=lambda n: (503, {"error": {"message": "big is down"}}))
    env.provider.profile(env.model_small, reply=lambda n: "fallback ok")

    big = TrafficFactory(env, model=env.model_big, feature="support_agent", system_prompt=BIG_SYSTEM)
    body, headers = big.next_request()
    response = await data_plane.post("/v1/chat/completions", headers=headers, json=body)

    report.check("request_served_via_fallback", response.status_code == 200, response.status_code)
    report.check("fallback_labeled", response.headers.get("x-varsten-fallback") == env.model_small)
    report.check("fallback_content_real", response.json()["choices"][0]["message"]["content"] == "fallback ok")

    db = env.db()
    try:
        decision = db.scalar(select(RequestDecisionEvent).where(RequestDecisionEvent.project_id == env.project_id))
        report.check(
            "fallback_recorded_with_zero_savings",
            decision is not None
            and decision.fallback_used is True
            and decision.realized_savings_usd is None
            and decision.optimization_applied is False,
        )
        canary_scan(env, report)
    finally:
        db.close()
    report.finish()
