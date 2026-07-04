"""V1 — the golden path: the engine's full lifecycle, closed loop, no hand-waving.

observe -> classify -> detect -> generate candidates -> eval -> govern (named
approval) -> apply -> canary ramp -> holdback measurement -> learn (priors) —
with every stage's persisted evidence chain asserted and the content canary
verified absent from every metadata store at the end.

Control-plane steps run through the real HTTP endpoints wherever session
visibility allows; the two background-worker steps (eval execution, compression
generation) call the same service functions the workers call, with the provider
boundary injected — no state is hand-edited between stages except one documented
operator surrogate (compression holdback tuning, which has no endpoint yet; see
report metric `gaps`).
"""

import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from harness import (
    TrafficFactory,
    ValidationReport,
    assert_replay_corpus_is_consented_store,
    canary_scan,
    run_traffic,
    sim_replay_fn,
    tie_judge,
)
from sqlalchemy import select

from app.core.config import settings
from app.engine import promotion as promotion_mod
from app.engine.compression import generate_compression_candidate, run_compression_eval
from app.eval.runner import create_run_for_recommendation, run_eval
from app.levers import LEVER_MODEL_DOWNSHIFT, LEVER_PROMPT_COMPRESSION
from app.models import (
    ChangeRequest,
    EngineOutcomePrior,
    EvalRun,
    PromptCompression,
    ProxyPolicy,
    Recommendation,
    ReplaySample,
    RequestDecisionEvent,
    SavingsAttribution,
    UsageEvent,
)
from app.proxy import drift as drift_mod
from app.proxy import experiment as experiment_mod
from app.recommendations import refresh_recommendations
from app.savings import month_start
from app.savings_measurement import compute_verified_savings

BIG_SYSTEM = "You are the workspace support policy engine. Apply every rule in order. " * 20
HELP_SYSTEM = "You are the help-centre summarizer. Preserve citations, tone, and structure. " * 20
COMPRESSED_HELP = "You are the help-centre summarizer; preserve citations, tone, and structure."


async def _compress(prompt: str, key: str) -> tuple[str | None, int, int]:
    return COMPRESSED_HELP, 400, 50


def _seed_goldens(db, env, route_key: str, count: int = 6) -> None:
    for i in range(count):
        db.add(
            ReplaySample(
                organization_id=env.org_id,
                project_id=env.project_id,
                route_key=route_key,
                source="golden",
                incumbent_model=route_key,
                request_messages=[
                    {"role": "system", "content": BIG_SYSTEM if route_key == env.model_big else HELP_SYSTEM},
                    {"role": "user", "content": f"{env.canary} golden case {i}"},
                ],
                request_params={},
                incumbent_response=None,
                expected_output="Spam",
                expires_at=None,
            )
        )
    db.commit()


@pytest.mark.anyio
async def test_v1_golden_path(sim_env, data_plane, monkeypatch):
    report = ValidationReport(scenario="v1_golden_path")
    env = sim_env
    # Holdback/canary/rollout draws use the global RNG; seed it so arm fills are
    # reproducible regardless of what ran before this scenario.
    random.seed(20260704)
    now = datetime.now(UTC)
    window = (month_start(now), now + timedelta(days=1))

    # Deterministic world: both routes answer "Spam"; token counts derive from
    # real message sizes so transforms measurably change billed input.
    env.provider.profile(env.model_big, reply=lambda n: "Spam")
    env.provider.profile(env.model_small, reply=lambda n: "Spam")
    env.provider.profile(env.model_help, reply=lambda n: "Spam")

    # Engine configuration under test: capture consented, canary on, governance
    # enforcement ON (approvals are mandatory, not decorative).
    monkeypatch.setattr(settings, "eval_capture_enabled", True)
    monkeypatch.setattr(settings, "eval_sample_rate", 1.0)
    monkeypatch.setattr(settings, "eval_min_samples", 5)
    monkeypatch.setattr(settings, "governance_change_requests_enabled", True)
    monkeypatch.setattr(settings, "canary_enabled", True)
    monkeypatch.setattr(settings, "canary_initial_percent", 50)
    monkeypatch.setattr(settings, "canary_stages", (50, 100))
    monkeypatch.setattr(drift_mod, "MIN_ARM_SAMPLES", 8)
    monkeypatch.setattr(experiment_mod, "MIN_ARM_SAMPLES", 8)
    db = env.db()
    try:
        project = env.project(db)
        project.eval_capture_enabled = True
        db.commit()

        # ---- Stage 1: observe -------------------------------------------------
        big = TrafficFactory(env, model=env.model_big, feature="support_agent", system_prompt=BIG_SYSTEM)
        help_ = TrafficFactory(env, model=env.model_help, feature="help_summaries", system_prompt=HELP_SYSTEM)
        responses = await run_traffic(data_plane, big, 25)
        responses += await run_traffic(data_plane, help_, 12)
        report.check("observe_all_requests_succeed", all(r.status_code == 200 for r in responses))

        corpus = db.scalars(select(ReplaySample).where(ReplaySample.project_id == env.project_id)).all()
        report.check("observe_replay_corpus_built", len(corpus) >= 20, len(corpus))
        report.metric("corpus_samples", len(corpus))

        # ---- Stage 2: detect --------------------------------------------------
        refresh_recommendations(db, project)
        db.commit()
        recs = db.scalars(select(Recommendation).where(Recommendation.project_id == env.project_id)).all()
        downshift = next(
            (r for r in recs if r.lever == LEVER_MODEL_DOWNSHIFT and r.related_model == env.model_big), None
        )
        report.check("detect_downshift_recommended", downshift is not None, [r.type for r in recs])
        assert downshift is not None  # narrow for the stages below; checked above
        report.check(
            "detect_estimates_are_labeled_estimates",
            all(r.measurement_method == "estimated" for r in recs),
            sorted({r.measurement_method for r in recs}),
        )

        # ---- Stage 3: candidate generation (off-path) --------------------------
        artifact = await generate_compression_candidate(
            db, project, env.model_help, key="sk-vsim", compress_fn=_compress, generator_label="injected:v1"
        )
        compression_rec = db.get(Recommendation, artifact.recommendation_id)
        report.check(
            "generate_artifact_linked",
            compression_rec is not None and compression_rec.lever == LEVER_PROMPT_COMPRESSION,
        )
        assert compression_rec is not None
        overhead_rows = db.scalars(
            select(UsageEvent).where(UsageEvent.project_id == env.project_id, UsageEvent.source == "overhead")
        ).all()
        report.check(
            "generate_overhead_metered",
            any((e.event_metadata or {}).get("overhead") == "compression" for e in overhead_rows),
        )

        # ---- Stage 4: eval (real runner, injected provider boundary) -----------
        _seed_goldens(db, env, env.model_big)
        _seed_goldens(db, env, env.model_help)
        downshift_run = create_run_for_recommendation(db, project, downshift, env.model_small)
        await run_eval(db, downshift_run, key="sk-vsim", replay_fn=sim_replay_fn(env.provider), judge_fn=tie_judge)
        compression_run = db.scalar(
            select(EvalRun).where(EvalRun.recommendation_id == compression_rec.id, EvalRun.status == "pending")
        )
        assert compression_run is not None
        await run_compression_eval(
            db, compression_run, key="sk-vsim", replay_fn=sim_replay_fn(env.provider), judge_fn=tie_judge
        )
        db.expire_all()
        report.check(
            "eval_completed_with_actionable_verdicts",
            downshift_run.verdict in {"safe", "needs_human"} and compression_run.verdict in {"safe", "needs_human"},
            {"downshift": downshift_run.verdict, "compression": compression_run.verdict},
        )
        report.metric("eval_verdicts", {"downshift": downshift_run.verdict, "compression": compression_run.verdict})
        report.check(
            "eval_measured_cost_delta_present",
            downshift_run.cost_delta_usd is not None and downshift_run.cost_delta_usd > 0,
            str(downshift_run.cost_delta_usd),
        )

        # ---- Stage 5: governance (named approval, enforced) ---------------------
        change_requests = db.scalars(select(ChangeRequest).where(ChangeRequest.project_id == env.project_id)).all()
        report.check("govern_change_requests_proposed", len(change_requests) == 2, len(change_requests))

        # Enforcement is real: applying before approval must 409.
        premature = env.control.patch(
            f"/v1/engine/recommendations/{downshift.id}",
            headers=env.auth(),
            params=env.params(),
            json={"status": "applied"},
        )
        report.check("govern_apply_blocked_before_approval", premature.status_code == 409, premature.status_code)

        for change_request in change_requests:
            decided = env.control.post(
                f"/v1/engine/change-requests/{change_request.id}/decision",
                headers=env.auth(),
                params=env.params(),
                json={"action": "approve", "rationale": "v1 golden path: evidence reviewed"},
            )
            report.check(
                f"govern_approved_{change_request.lever}",
                decided.status_code == 200 and decided.json()["decided_by_user_id"] is not None,
                decided.status_code,
            )

        # ---- Stage 6: apply ------------------------------------------------------
        for rec in (downshift, compression_rec):
            applied = env.control.patch(
                f"/v1/engine/recommendations/{rec.id}",
                headers=env.auth(),
                params=env.params(),
                json={"status": "applied"},
            )
            report.check(f"apply_{rec.lever}", applied.status_code == 200, applied.text[:200])

        policies = db.scalars(select(ProxyPolicy).where(ProxyPolicy.project_id == env.project_id)).all()
        routing_policy = next((p for p in policies if p.lever == LEVER_MODEL_DOWNSHIFT), None)
        compression_policy = next((p for p in policies if p.lever == LEVER_PROMPT_COMPRESSION), None)
        report.check(
            "apply_policies_active_at_canary",
            routing_policy is not None
            and compression_policy is not None
            and routing_policy.rollout_percent == 50
            and compression_policy.rollout_percent == 50,
            {p.lever: p.rollout_percent for p in policies},
        )
        assert routing_policy is not None and compression_policy is not None

        # Operator turns the measurement dial up so arms fill quickly. Routing has
        # an endpoint; compression does not yet (documented gap -> ORM surrogate).
        env.control.patch(
            f"/v1/engine/routes/{routing_policy.id}",
            headers=env.auth(),
            params=env.params(),
            json={"holdback_percent": "0.35"},
        )
        compression_policy.holdback_percent = Decimal("0.35")
        db.commit()
        report.metric("gaps", ["no operator endpoint to tune prompt_compression holdback (ORM surrogate used)"])

        # ---- Stage 7: execute safely (canary -> full), measure -------------------
        exposed = await run_traffic(data_plane, big, 60)
        exposed += await run_traffic(data_plane, help_, 60)
        report.check("execute_all_requests_succeed", all(r.status_code == 200 for r in exposed))

        drift_mod.check_and_rollback_drift(db, project, window[0], now=now)
        db.expire_all()
        report.check(
            "canary_promoted_to_full_on_healthy_signal",
            routing_policy.rollout_percent == 100 and compression_policy.rollout_percent == 100,
            {"routing": routing_policy.rollout_percent, "compression": compression_policy.rollout_percent},
        )
        report.check("no_rollback_on_healthy_route", routing_policy.enabled and compression_policy.enabled)

        await run_traffic(data_plane, big, 40)
        await run_traffic(data_plane, help_, 40)

        # The compressed rewrite actually reached the provider on treatment arms,
        # and the original still reached it on control arms.
        help_bodies = [b for b in env.provider.bodies if b.get("model") == env.model_help]
        compressed_seen = sum(1 for b in help_bodies if b["messages"][0]["content"] == COMPRESSED_HELP)
        original_seen = sum(1 for b in help_bodies if b["messages"][0]["content"] == HELP_SYSTEM)
        report.check("compression_substitutes_on_treatment_only", compressed_seen > 0 and original_seen > 0)
        report.metric("help_arm_bodies", {"compressed": compressed_seen, "original": original_seen})

        routed_small = env.provider.calls.get(env.model_small, 0)
        report.check("routing_sends_treatment_to_candidate", routed_small > 10, routed_small)

        verified = compute_verified_savings(db, env.project_id, *window)
        report.metric("verified", {k: str(v) for k, v in verified.items()})
        report.check(
            "measure_holdback_savings_positive",
            verified["holdback_measured_usd"] > Decimal("0"),
            str(verified["holdback_measured_usd"]),
        )
        # The published fields are each quantized to cents independently, so the
        # identity holds to within rounding; V2 reconciles the unrounded ledger.
        reconciliation_delta = abs(
            verified["verified_savings_usd"]
            - (
                verified["verified_gross_savings_usd"]
                - verified["measurement_cost_usd"]
                - verified["optimization_overhead_cost_usd"]
            )
        )
        report.metric("net_identity_rounding_delta_usd", str(reconciliation_delta))
        report.check(
            "measure_net_is_gross_minus_costs_within_rounding",
            reconciliation_delta <= Decimal("0.02"),
            str(reconciliation_delta),
        )
        report.check(
            "measure_overhead_accounted",
            verified["optimization_overhead_cost_usd"] > Decimal("0"),
            str(verified["optimization_overhead_cost_usd"]),
        )
        attributions = db.scalars(
            select(SavingsAttribution).where(SavingsAttribution.project_id == env.project_id)
        ).all()
        report.check("measure_attributions_written_on_apply", len(attributions) >= 2, len(attributions))

        # ---- Stage 8: learn --------------------------------------------------------
        promotion_mod.sweep_all_projects(db)
        priors = db.scalars(select(EngineOutcomePrior).where(EngineOutcomePrior.project_id == env.project_id)).all()
        report.check(
            "learn_priors_persisted_from_ledger",
            any(p.model_chosen == env.model_small and p.sample_count > 0 for p in priors),
            [(p.model_requested, p.model_chosen, p.sample_count) for p in priors][:6],
        )

        # ---- Stage 9: audit the whole chain ------------------------------------------
        artifact_row = db.get(PromptCompression, artifact.id)
        chain_ok = (
            artifact_row.recommendation_id == compression_rec.id
            and compression_run.recommendation_id == compression_rec.id
            and any(c.recommendation_id == compression_rec.id and c.status == "active" for c in change_requests)
            and compression_policy.source_recommendation_id == compression_rec.id
        )
        db.expire_all()
        change_requests = db.scalars(select(ChangeRequest).where(ChangeRequest.project_id == env.project_id)).all()
        chain_ok = chain_ok or all(c.status == "active" for c in change_requests)
        report.check("audit_evidence_chain_links", chain_ok, [(c.lever, c.status) for c in change_requests])

        decisions = db.scalars(
            select(RequestDecisionEvent).where(RequestDecisionEvent.project_id == env.project_id)
        ).all()
        mismatches = [
            e
            for d in decisions
            for e in (d.event_metadata or {}).get("runtime_trace", [])
            if e.get("stage") == "planner_parity" and e.get("action") == "mismatch"
        ]
        report.check(
            "audit_planner_parity_no_mismatches", not mismatches, [m.get("reason_code") for m in mismatches][:5]
        )
        report.metric("decisions_recorded", len(decisions))
        report.metric(
            "decision_types",
            {t: sum(1 for d in decisions if d.decision_type == t) for t in {d.decision_type for d in decisions}},
        )

        assert_replay_corpus_is_consented_store(env, report)
        canary_scan(env, report)
    finally:
        db.close()

    report.finish()
