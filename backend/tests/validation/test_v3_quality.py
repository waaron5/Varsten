"""V3 — quality-preservation battery.

The engine's hardest promise: optimizations never silently degrade output.
These scenarios inject real degradation through the live proxy and measure the
guard's behavior — how fast a clear regression rolls back and how much traffic
it exposed; that a sub-tolerance dip is respected (no flappiness under repeated
peeking); that latency is a first-class rollback trigger; and that a subjective
(judge-scored) verdict can never reach production without a named human.
"""

import random
import time
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from harness import TrafficFactory, ValidationReport, canary_scan, run_traffic, sim_replay_fn
from sqlalchemy import select

from app.core.config import settings
from app.engine import promotion as promotion_mod
from app.engine.compression import generate_compression_candidate, run_compression_eval
from app.eval.gate import EvalGateError, assert_appliable
from app.models import EvalRun, ProxyPolicy, Recommendation, ReplaySample
from app.proxy import drift as drift_mod
from app.proxy import experiment as experiment_mod
from app.savings import month_start

BIG_SYSTEM = "Apply the support policy rules in order, without exception. " * 25
HELP_SYSTEM = "You are the help-centre summarizer. Preserve citations and tone. " * 25


def _routing_policy(db, env, *, holdback="0.35", rec: Recommendation | None = None):
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


def _recommendation(db, env, lever="model_downshift") -> Recommendation:
    rec = Recommendation(
        organization_id=env.org_id,
        project_id=env.project_id,
        dedupe_key=f"v3-{env.run_id}-{lever}-{random.randint(0, 10**9)}",
        type=lever,
        lever=lever,
        title="v3 scenario recommendation",
        description="x",
        risk_level="medium",
        confidence="medium",
        related_model=env.model_big if lever == "model_downshift" else env.model_help,
    )
    db.add(rec)
    db.commit()
    return rec


@pytest.mark.anyio
async def test_v3_clear_degradation_rolls_back_and_exposure_is_measured(sim_env, data_plane, monkeypatch):
    """The candidate goes objectively bad mid-run: the guard must confirm the
    drop (peeking-safe) and roll back; the scenario reports exactly how much
    traffic was exposed before it did."""
    report = ValidationReport(scenario="v3_clear_degradation")
    env = sim_env
    random.seed(20260704)
    monkeypatch.setattr(drift_mod, "MIN_ARM_SAMPLES", 8)
    monkeypatch.setattr(experiment_mod, "MIN_ARM_SAMPLES", 8)

    env.provider.profile(env.model_big, reply=lambda n: "Spam")
    # SMALL answers correctly for its first 10 calls, then returns empty output —
    # an objective quality failure — for every call after.
    degrade_after = 10
    env.provider.profile(env.model_small, reply=lambda n: "Spam" if n <= degrade_after else "")

    db = env.db()
    try:
        rec = _recommendation(db, env)
        policy = _routing_policy(db, env, rec=rec)
        big = TrafficFactory(env, model=env.model_big, feature="support_agent", system_prompt=BIG_SYSTEM)

        exposed_after_degradation = 0
        sweeps_to_rollback = 0
        rolled = []
        for sweep_round in range(1, 9):
            await run_traffic(data_plane, big, 15)
            calls_small = env.provider.calls.get(env.model_small, 0)
            exposed_after_degradation = max(calls_small - degrade_after, 0)
            rolled = drift_mod.check_and_rollback_drift(db, env.project(db), month_start(datetime.now(UTC)))
            sweeps_to_rollback = sweep_round
            if rolled:
                break

        db.expire_all()
        report.check("rollback_fired_on_confirmed_degradation", bool(rolled), rolled and rolled[0].get("trigger"))
        report.check("policy_disabled", policy.enabled is False)
        report.check("recommendation_marked_rolled_back", db.get(Recommendation, rec.id).status == "rolled_back")
        report.metric("degraded_requests_exposed_before_rollback", exposed_after_degradation)
        report.metric("sweeps_to_rollback", sweeps_to_rollback)

        # After rollback the route heals immediately: traffic stays on the incumbent.
        before = env.provider.calls.get(env.model_small, 0)
        await run_traffic(data_plane, big, 10)
        report.check(
            "no_further_exposure_after_rollback",
            env.provider.calls.get(env.model_small, 0) == before,
        )
        canary_scan(env, report)
    finally:
        db.close()
    report.finish()


@pytest.mark.anyio
async def test_v3_sub_tolerance_dip_never_rolls_back_under_peeking(sim_env, data_plane, monkeypatch):
    """A ~3% quality dip sits below the 5% tolerance: fifty repeated sweeps over
    the same accumulating arms must never roll it back (time-uniform guarantee on
    the real SQL path, not just the simulation)."""
    report = ValidationReport(scenario="v3_sub_tolerance_no_flap")
    env = sim_env
    random.seed(11)
    monkeypatch.setattr(drift_mod, "MIN_ARM_SAMPLES", 8)
    monkeypatch.setattr(experiment_mod, "MIN_ARM_SAMPLES", 8)

    env.provider.profile(env.model_big, reply=lambda n: "Spam")
    env.provider.profile(env.model_small, reply=lambda n: "" if n % 33 == 0 else "Spam")  # ~3% bad

    db = env.db()
    try:
        policy = _routing_policy(db, env, rec=_recommendation(db, env))
        big = TrafficFactory(env, model=env.model_big, feature="support_agent", system_prompt=BIG_SYSTEM)
        await run_traffic(data_plane, big, 70)

        rollbacks = 0
        for _ in range(50):  # deliberate heavy peeking
            if drift_mod.check_and_rollback_drift(db, env.project(db), month_start(datetime.now(UTC))):
                rollbacks += 1
        db.expire_all()
        report.check("no_rollback_below_tolerance", rollbacks == 0 and policy.enabled, rollbacks)
        report.metric("peek_count", 50)
        canary_scan(env, report)
    finally:
        db.close()
    report.finish()


@pytest.mark.anyio
async def test_v3_latency_regression_rolls_back_through_live_traffic(sim_env, data_plane, monkeypatch):
    """The candidate answers correctly but slowly: quality holds, latency is the
    regression, and it must trigger rollback on its own."""
    report = ValidationReport(scenario="v3_latency_regression")
    env = sim_env
    random.seed(5)
    monkeypatch.setattr(drift_mod, "MIN_ARM_SAMPLES", 8)
    monkeypatch.setattr(experiment_mod, "MIN_ARM_SAMPLES", 8)
    # Wide margins so wall-clock jitter cannot flake the confidence sequence:
    # treatment sleeps ~120ms, control is instant, tolerance is 25ms.
    monkeypatch.setattr(settings, "latency_drift_tolerance_ms", 25.0)

    def slow_reply(n: int) -> str:
        time.sleep(0.12)
        return "Spam"

    env.provider.profile(env.model_big, reply=lambda n: "Spam")
    env.provider.profile(env.model_small, reply=slow_reply)

    db = env.db()
    try:
        rec = _recommendation(db, env)
        policy = _routing_policy(db, env, rec=rec)
        big = TrafficFactory(env, model=env.model_big, feature="support_agent", system_prompt=BIG_SYSTEM)
        await run_traffic(data_plane, big, 45)

        rolled = drift_mod.check_and_rollback_drift(db, env.project(db), month_start(datetime.now(UTC)))
        db.expire_all()
        report.check("latency_regression_rolled_back", bool(rolled), rolled)
        report.check(
            "trigger_is_latency_not_quality",
            bool(rolled) and rolled[0].get("trigger") in {"latency", "latency_slo"},
            rolled and rolled[0].get("trigger"),
        )
        report.check("policy_disabled", policy.enabled is False)
        if rolled:
            report.metric("latency_delta_ms", rolled[0].get("latency_delta_ms"))
        canary_scan(env, report)
    finally:
        db.close()
    report.finish()


@pytest.mark.anyio
async def test_v3_judge_verdict_never_reaches_production_without_a_human(sim_env, data_plane, monkeypatch):
    """Subjective (judge-scored) evidence is a hard ceiling: the automated path
    is refused by the gate, the HTTP apply is refused without an approved
    ChangeRequest, and the learning sweep proposes — never applies."""
    report = ValidationReport(scenario="v3_judge_ceiling")
    env = sim_env
    monkeypatch.setattr(settings, "eval_min_samples", 4)
    monkeypatch.setattr(settings, "governance_change_requests_enabled", True)
    # Long freeform outputs: short (<=40 char) incumbents would trip the
    # objective exact-match tier and this scenario must be genuinely subjective.
    env.provider.profile(
        env.model_help,
        reply=lambda n: "A thorough, plausible summary of the thread covering every participant's position in detail.",
    )

    db = env.db()
    try:
        # A judge-only corpus: traffic samples with incumbent responses but no
        # expected outputs and no objective signal -> every score is subjective.
        for i in range(6):
            db.add(
                ReplaySample(
                    organization_id=env.org_id,
                    project_id=env.project_id,
                    route_key=env.model_help,
                    source="traffic",
                    incumbent_model=env.model_help,
                    request_messages=[
                        {"role": "system", "content": HELP_SYSTEM},
                        {"role": "user", "content": f"{env.canary} summarize thread {i}"},
                    ],
                    request_params={},
                    incumbent_response={
                        "choices": [
                            {
                                "index": 0,
                                "message": {
                                    "role": "assistant",
                                    "content": (
                                        "An incumbent summary of the discussion thread, long enough that no "
                                        "objective scoring tier can claim it as an exact-match signal."
                                    ),
                                },
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {"prompt_tokens": 400, "completion_tokens": 30},
                    },
                    expected_output=None,
                    expires_at=None,
                )
            )
        db.commit()

        async def _compress(prompt: str, key: str):
            return "You are the help-centre summarizer; keep citations and tone.", 100, 20

        artifact = await generate_compression_candidate(
            db, env.project(db), env.model_help, key="sk-vsim", compress_fn=_compress
        )
        rec = db.get(Recommendation, artifact.recommendation_id)
        run = db.scalar(select(EvalRun).where(EvalRun.recommendation_id == rec.id, EvalRun.status == "pending"))

        async def equivalent_judge(prompt, incumbent, candidate, key):
            return "tie", "sim judge: equivalent quality"

        await run_compression_eval(
            db, run, key="sk-vsim", replay_fn=sim_replay_fn(env.provider), judge_fn=equivalent_judge
        )
        db.expire_all()
        report.check("judge_only_eval_yields_needs_human", run.verdict == "needs_human", run.verdict)

        # 1. The automated path is refused by the gate itself.
        automated_blocked = False
        try:
            assert_appliable(db, rec, automated=True)
        except EvalGateError:
            automated_blocked = True
        report.check("automated_apply_refused_by_gate", automated_blocked)

        # 2. The human HTTP path is refused until a named approval exists.
        premature = env.control.patch(
            f"/v1/engine/recommendations/{rec.id}",
            headers=env.auth(),
            params=env.params(),
            json={"status": "applied"},
        )
        report.check("http_apply_refused_without_approval", premature.status_code == 409, premature.status_code)

        # 3. The learning sweep proposes, never applies.
        promotion_mod.sweep_all_projects(db)
        db.expire_all()
        report.check("sweep_never_applies_gated_lever", db.get(Recommendation, rec.id).status == "open")
        policies = db.scalars(
            select(ProxyPolicy).where(
                ProxyPolicy.project_id == env.project_id, ProxyPolicy.lever == "prompt_compression"
            )
        ).all()
        report.check("no_policy_activated_without_human", policies == [])
        canary_scan(env, report)
    finally:
        db.close()
    report.finish()


@pytest.mark.anyio
async def test_v3_compression_mismatch_storm_exposes_nothing(sim_env, data_plane, monkeypatch):
    """A live compression policy whose route's prompts all drift from the
    evaluated original must expose zero requests to the rewrite — and the
    detector should flip to recommending a prefix restructure."""
    report = ValidationReport(scenario="v3_compression_mismatch_storm")
    env = sim_env
    random.seed(9)
    from app.engine.compression import system_text_hash
    from app.models import PromptCompression

    env.provider.profile(env.model_help, reply=lambda n: "Spam")

    db = env.db()
    try:
        evaluated_original = HELP_SYSTEM
        artifact = PromptCompression(
            organization_id=env.org_id,
            project_id=env.project_id,
            route_key=env.model_help,
            model=env.model_help,
            original_system_hash=system_text_hash(evaluated_original),
            original_chars=len(evaluated_original),
            compressed_system_prompt="You are the help-centre summarizer.",
            compressed_chars=36,
            generator="injected:v3",
        )
        db.add(artifact)
        db.flush()
        db.add(
            ProxyPolicy(
                organization_id=env.org_id,
                project_id=env.project_id,
                lever="prompt_compression",
                target_type="model",
                target_key=env.model_help,
                params={"artifact_id": str(artifact.id)},
                enabled=True,
                holdback_percent=Decimal("0"),  # every request is treatment
                rollout_percent=100,
            )
        )
        db.commit()

        # Every request carries a *different* system prompt (per-request injection
        # of volatile content): none may be substituted. Prompts are large enough
        # (>1500 tokens) that the prompt-cache/restructure detector engages.
        factory = TrafficFactory(env, model=env.model_help, feature="help_summaries", system_prompt=None)
        responses = []
        for i in range(25):
            body, headers = factory.next_request()
            body["messages"].insert(0, {"role": "system", "content": f"{HELP_SYSTEM * 4} Session {i} at t={i}."})
            responses.append(await data_plane.post("/v1/chat/completions", headers=headers, json=body))
        report.check("all_requests_succeed", all(r.status_code == 200 for r in responses))

        substituted = [
            b
            for b in env.provider.bodies
            if b.get("model") == env.model_help and "Session" not in b["messages"][0]["content"]
        ]
        report.check("zero_requests_exposed_to_rewrite", substituted == [], len(substituted))

        from app.recommendations import refresh_recommendations

        refresh_recommendations(db, env.project(db))
        db.commit()
        restructure = db.scalar(
            select(Recommendation).where(
                Recommendation.project_id == env.project_id,
                Recommendation.type == "prompt_prefix_restructure",
            )
        )
        report.check("unstable_prefix_flips_to_restructure_recommendation", restructure is not None)
        canary_scan(env, report)
    finally:
        db.close()
    report.finish()
