"""V2 — honest-savings adversarial audit.

Every scenario here tries to manufacture fake money and asserts the engine
refuses it. The core discipline: claimed numbers are re-derived inside the test
from raw ledger rows — never through the code that produced the claim.
"""

import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from harness import TrafficFactory, ValidationReport, canary_scan, run_traffic
from sqlalchemy import select

from app.core.config import settings
from app.engine.compression import generate_compression_candidate
from app.models import ModelPrice, ProxyPolicy, Recommendation, ReplaySample, UsageEvent
from app.recommendations import refresh_recommendations
from app.savings import month_start
from app.savings_measurement import compute_verified_savings

CENT = Decimal("0.01")
BIG_SYSTEM = "Apply the support policy rules in order, without exception. " * 25


def _window(now):
    return month_start(now), now + timedelta(days=1)


def _routing_policy(db, env, holdback="0.4"):
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
    )
    db.add(policy)
    db.commit()
    return policy


def _events(db, env) -> list[UsageEvent]:
    return db.scalars(select(UsageEvent).where(UsageEvent.project_id == env.project_id)).all()


def _recompute_from_ledger(events: list[UsageEvent]) -> dict:
    """Independent recomputation of every savings component from raw rows."""
    meta = [(e, e.event_metadata or {}) for e in events]
    direct_cache = sum(
        (Decimal(m["saved_usd"]) for e, m in meta if m.get("cache") == "hit" and m.get("saved_usd")), Decimal("0")
    )
    # Holdback per experiment pair: (mean_control - mean_treatment) * n_treatment.
    pairs: dict[tuple[str, str], dict[str, list[Decimal]]] = {}
    for e, m in meta:
        if m.get("holdback") and m.get("experiment_from") and m.get("experiment_to"):
            pair = pairs.setdefault((m["experiment_from"], m["experiment_to"]), {"control": [], "treatment": []})
            pair[m["arm"]].append(e.cost_usd or Decimal("0"))
    holdback_total = Decimal("0")
    measurement_cost = Decimal("0")
    for arms in pairs.values():
        if not arms["control"] or not arms["treatment"]:
            continue
        mean_c = sum(arms["control"], Decimal("0")) / len(arms["control"])
        mean_t = sum(arms["treatment"], Decimal("0")) / len(arms["treatment"])
        per_request = mean_c - mean_t
        holdback_total += per_request * len(arms["treatment"])
        measurement_cost += max(per_request, Decimal("0")) * len(arms["control"])
    overhead = sum((e.cost_usd or Decimal("0") for e, m in meta if e.source == "overhead"), Decimal("0"))
    return {
        "direct": direct_cache,
        "holdback": holdback_total,
        "measurement_cost": measurement_cost,
        "overhead": overhead,
        "net": direct_cache + holdback_total - measurement_cost - overhead,
    }


@pytest.mark.anyio
async def test_v2_independent_reconciliation(sim_env, data_plane, monkeypatch):
    """The engine's published savings must equal blind arithmetic on raw rows."""
    report = ValidationReport(scenario="v2_independent_reconciliation")
    env = sim_env
    random.seed(20260704)
    now = datetime.now(UTC)
    env.provider.profile(env.model_big, reply=lambda n: "Spam")
    env.provider.profile(env.model_small, reply=lambda n: "Spam")
    env.provider.profile(env.model_help, reply=lambda n: "Spam")

    db = env.db()
    try:
        _routing_policy(db, env)

        # Routed traffic (holdback A/B on BIG) + exact-cache hits on HELP.
        big = TrafficFactory(env, model=env.model_big, feature="support_agent", system_prompt=BIG_SYSTEM)
        await run_traffic(data_plane, big, 60)
        help_ = TrafficFactory(env, model=env.model_help, feature="faq", system_prompt=None)
        body, headers = help_.next_request(user_text=f"{env.canary} what are your hours?")
        for _ in range(6):  # identical request: 1 miss + 5 exact-cache hits
            r = await data_plane.post("/v1/chat/completions", headers=headers, json=body)
            assert r.status_code == 200

        events = _events(db, env)
        manual = _recompute_from_ledger(events)
        verified = compute_verified_savings(db, env.project_id, *_window(now))
        report.metric("manual", {k: str(v) for k, v in manual.items()})
        report.metric("engine", {k: str(v) for k, v in verified.items()})

        report.check(
            "direct_matches_raw_arithmetic",
            abs(verified["direct_measured_usd"] - manual["direct"]) <= CENT,
            f"engine {verified['direct_measured_usd']} vs manual {manual['direct']}",
        )
        report.check(
            "holdback_matches_raw_arithmetic",
            abs(verified["holdback_measured_usd"] - manual["holdback"]) <= CENT,
            f"engine {verified['holdback_measured_usd']} vs manual {manual['holdback']}",
        )
        report.check(
            "measurement_cost_matches_raw_arithmetic",
            abs(verified["measurement_cost_usd"] - manual["measurement_cost"]) <= CENT,
        )
        report.check(
            "net_matches_raw_arithmetic",
            abs(verified["verified_savings_usd"] - manual["net"]) <= Decimal("0.05"),
            f"engine {verified['verified_savings_usd']} vs manual {manual['net']}",
        )
        report.check("cache_hits_actually_saved", manual["direct"] > 0, str(manual["direct"]))
        report.check("holdback_actually_measured", manual["holdback"] > 0, str(manual["holdback"]))

        canary_scan(env, report)
    finally:
        db.close()
    report.finish()


@pytest.mark.anyio
async def test_v2_no_double_counting_and_control_purity(sim_env, data_plane, monkeypatch):
    report = ValidationReport(scenario="v2_double_count_traps")
    env = sim_env
    random.seed(7)
    now = datetime.now(UTC)
    env.provider.profile(env.model_big, reply=lambda n: "Spam")
    env.provider.profile(env.model_small, reply=lambda n: "Spam")

    db = env.db()
    try:
        _routing_policy(db, env)
        big = TrafficFactory(env, model=env.model_big, feature="support_agent", system_prompt=BIG_SYSTEM)
        await run_traffic(data_plane, big, 50)

        events = _events(db, env)
        meta = [(e, e.event_metadata or {}) for e in events]

        controls = [(e, m) for e, m in meta if m.get("arm") == "control"]
        report.check("controls_exist", len(controls) >= 5, len(controls))
        report.check(
            "control_arm_never_claims_savings",
            all(not m.get("saved_usd") for _, m in controls),
            [m.get("saved_usd") for _, m in controls if m.get("saved_usd")],
        )
        # Holdback treatments carry per-event saved_usd for the dashboard view but
        # must be EXCLUDED from verified direct savings (the A/B owns them).
        verified = compute_verified_savings(db, env.project_id, *_window(now))
        report.check(
            "holdback_treatments_not_double_counted_as_direct",
            verified["direct_measured_usd"] == Decimal("0.00"),
            str(verified["direct_measured_usd"]),
        )
        report.check(
            "verified_gross_is_exactly_holdback_here",
            verified["verified_gross_savings_usd"] == verified["holdback_measured_usd"],
        )
        canary_scan(env, report)
    finally:
        db.close()
    report.finish()


@pytest.mark.anyio
async def test_v2_overhead_can_push_net_negative(sim_env, data_plane, monkeypatch):
    """A route whose proof/overhead costs exceed its savings must report a
    negative net — never clamp to zero, never hide the cost."""
    report = ValidationReport(scenario="v2_overhead_dominance")
    env = sim_env
    now = datetime.now(UTC)
    env.provider.profile(env.model_help, reply=lambda n: "Spam")
    monkeypatch.setattr(settings, "compression_generator_model", env.model_big)  # priced, expensive

    db = env.db()
    try:
        help_ = TrafficFactory(env, model=env.model_help, feature="faq", system_prompt="Summarize helpfully. " * 60)
        await run_traffic(data_plane, help_, 3)  # a little real traffic, no levers -> ~no savings

        # Seed a corpus row so generation has a dominant prompt, then "spend" an
        # enormous generation call.
        db.add(
            ReplaySample(
                organization_id=env.org_id,
                project_id=env.project_id,
                route_key=env.model_help,
                source="golden",
                incumbent_model=env.model_help,
                request_messages=[
                    {"role": "system", "content": "Summarize helpfully. " * 60},
                    {"role": "user", "content": "x"},
                ],
                request_params={},
                expected_output="ok",
                expires_at=None,
            )
        )
        db.commit()

        async def expensive_compress(prompt: str, key: str) -> tuple[str | None, int, int]:
            return "Summarize helpfully.", 400_000, 50_000  # a very costly rewrite

        await generate_compression_candidate(
            db, env.project(db), env.model_help, key="sk-vsim", compress_fn=expensive_compress
        )

        verified = compute_verified_savings(db, env.project_id, *_window(now))
        report.metric("verified", {k: str(v) for k, v in verified.items()})
        report.check(
            "overhead_recorded",
            verified["optimization_overhead_cost_usd"] > Decimal("1"),
            str(verified["optimization_overhead_cost_usd"]),
        )
        report.check(
            "net_reported_negative_not_clamped",
            verified["verified_savings_usd"] < Decimal("0"),
            str(verified["verified_savings_usd"]),
        )
        canary_scan(env, report)
    finally:
        db.close()
    report.finish()


@pytest.mark.anyio
async def test_v2_do_nothing_customer_gets_zero_not_painted(sim_env, data_plane):
    report = ValidationReport(scenario="v2_do_nothing_customer")
    env = sim_env
    now = datetime.now(UTC)
    env.provider.profile(env.model_big, reply=lambda n: "Spam")

    db = env.db()
    try:
        big = TrafficFactory(env, model=env.model_big, feature="support_agent", system_prompt=BIG_SYSTEM)
        await run_traffic(data_plane, big, 15)

        verified = compute_verified_savings(db, env.project_id, *_window(now))
        report.check(
            "all_savings_exactly_zero",
            all(
                verified[k] == Decimal("0.00")
                for k in (
                    "direct_measured_usd",
                    "holdback_measured_usd",
                    "measurement_cost_usd",
                    "optimization_overhead_cost_usd",
                    "verified_gross_savings_usd",
                    "verified_savings_usd",
                )
            ),
            {k: str(v) for k, v in verified.items() if isinstance(v, Decimal)},
        )
        report.check(
            "no_event_claims_savings", all(not (e.event_metadata or {}).get("saved_usd") for e in _events(db, env))
        )

        refresh_recommendations(db, env.project(db))
        db.commit()
        recs = db.scalars(select(Recommendation).where(Recommendation.project_id == env.project_id)).all()
        report.check(
            "recommendations_are_estimates_never_verified",
            recs != [] and all(r.measurement_method == "estimated" for r in recs),
            sorted({r.measurement_method for r in recs}),
        )
        canary_scan(env, report)
    finally:
        db.close()
    report.finish()


@pytest.mark.anyio
async def test_v2_mid_experiment_price_change_cancels(sim_env, data_plane, monkeypatch):
    """Provider price moves hit both concurrent arms and cancel: the measured
    holdback savings still equals blind arithmetic on the rows, with no
    'adjustment' anywhere."""
    report = ValidationReport(scenario="v2_price_change")
    env = sim_env
    random.seed(11)
    now = datetime.now(UTC)
    env.provider.profile(env.model_big, reply=lambda n: "Spam")
    env.provider.profile(env.model_small, reply=lambda n: "Spam")

    db = env.db()
    try:
        _routing_policy(db, env)
        big = TrafficFactory(env, model=env.model_big, feature="support_agent", system_prompt=BIG_SYSTEM)
        await run_traffic(data_plane, big, 30)

        # Price shock: both models triple, effective immediately.
        for key, cin, cout in (
            (env.model_big, "0.00003000", "0.00009000"),
            (env.model_small, "0.00000300", "0.00000900"),
        ):
            db.add(
                ModelPrice(
                    model_key=key,
                    provider="openai",
                    currency="USD",
                    input_cost_per_token=Decimal(cin),
                    output_cost_per_token=Decimal(cout),
                    source="catalog",
                    effective_at=now,
                )
            )
        db.commit()
        from app.pricing import service as pricing_service

        if hasattr(pricing_service, "clear_price_cache"):
            pricing_service.clear_price_cache()

        await run_traffic(data_plane, big, 30)

        manual = _recompute_from_ledger(_events(db, env))
        verified = compute_verified_savings(db, env.project_id, *_window(now))
        report.metric("manual_holdback", str(manual["holdback"]))
        report.metric("engine_holdback", str(verified["holdback_measured_usd"]))
        report.check(
            "post_shock_engine_still_equals_raw_arithmetic",
            abs(verified["holdback_measured_usd"] - manual["holdback"]) <= CENT,
        )
        report.check("savings_still_positive_through_shock", verified["holdback_measured_usd"] > 0)
        canary_scan(env, report)
    finally:
        db.close()
    report.finish()
