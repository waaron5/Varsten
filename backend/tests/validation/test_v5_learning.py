"""V5 — learning-loop integrity: no fake learning.

Every statistic the learning layer uses must reconcile to persisted decisions;
the loop must adopt what measurement supports, refuse what measurement condemns,
and explore only within its declared budget. The bandit's regret is quantified
against a known oracle in a sampler-level simulation.
"""

import random
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from harness import TrafficFactory, ValidationReport, canary_scan, run_traffic
from sqlalchemy import select

from app.core.config import settings
from app.engine import bandit
from app.engine import promotion as promotion_mod
from app.engine.priors import clear_outcome_prior_cache
from app.models import EngineOutcomePrior, EvalRun, ProxyPolicy, Recommendation, RequestDecisionEvent
from app.proxy import drift as drift_mod
from app.proxy import experiment as experiment_mod
from app.savings import month_start

BIG_SYSTEM = "Apply the support policy rules in order, without exception. " * 25


def _routing_policy(db, env, *, holdback="0.1"):
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


async def _post_feedback(data_plane, env, request_ids, outcome="accepted"):
    for request_id in request_ids:
        response = await data_plane.post(
            "/v1/feedback",
            headers={"Authorization": f"Bearer {env.api_key}"},
            json={"request_id": request_id, "outcome": outcome},
        )
        assert response.status_code in (200, 201), response.text


@pytest.mark.anyio
async def test_v5_priors_reconcile_and_promotion_carries_receipts(sim_env, data_plane, monkeypatch):
    """Priors persisted by the sweep must equal blind aggregation of the raw
    decision rows, and a paused-but-proven path must be re-proposed with its
    measured evidence — the loop's central honesty claim."""
    report = ValidationReport(scenario="v5_priors_reconcile")
    env = sim_env
    random.seed(20260704)
    env.provider.profile(env.model_big, reply=lambda n: "Spam")
    env.provider.profile(env.model_small, reply=lambda n: "Spam")

    db = env.db()
    try:
        policy = _routing_policy(db, env)
        big = TrafficFactory(env, model=env.model_big, feature="support_agent", system_prompt=BIG_SYSTEM)
        responses = await run_traffic(data_plane, big, 40)
        # Implicit production signal: the customer accepted these outputs.
        request_ids = [r.headers["X-Varsten-Request-Id"] for r in responses if "X-Varsten-Request-Id" in r.headers]
        await _post_feedback(data_plane, env, request_ids[:30])

        promotion_mod.sweep_all_projects(db)
        db.expire_all()

        priors = db.scalars(
            select(EngineOutcomePrior).where(
                EngineOutcomePrior.project_id == env.project_id,
                EngineOutcomePrior.model_chosen == env.model_small,
            )
        ).all()
        report.check("priors_persisted", priors != [], len(priors))

        # Blind reconciliation: raw decision rows -> the same aggregates.
        decisions = db.scalars(
            select(RequestDecisionEvent).where(
                RequestDecisionEvent.project_id == env.project_id,
                RequestDecisionEvent.optimization_applied.is_(True),
                RequestDecisionEvent.model_chosen == env.model_small,
            )
        ).all()
        prior_samples = sum(p.sample_count for p in priors)
        report.check(
            "prior_sample_count_equals_raw_decisions",
            prior_samples == len(decisions),
            f"priors {prior_samples} vs raw {len(decisions)}",
        )
        raw_quality_passes = sum(1 for d in decisions if d.quality_ok is True)
        weighted_quality = sum((p.quality_pass_rate or Decimal("0")) * p.sample_count for p in priors)
        report.check(
            "prior_quality_equals_raw_pass_rate",
            abs(weighted_quality - Decimal(raw_quality_passes)) < Decimal("0.5"),
            f"weighted {weighted_quality} vs raw passes {raw_quality_passes}",
        )
        raw_savings = sum((d.realized_savings_usd or Decimal("0")) for d in decisions)
        prior_savings = sum((p.total_gross_savings_usd or Decimal("0")) for p in priors)
        report.check(
            "prior_savings_equal_raw_ledger",
            abs(prior_savings - raw_savings) < Decimal("0.0001"),
            f"prior {prior_savings} vs raw {raw_savings}",
        )

        # Pause the proven path; the learning sweep must re-propose it with the
        # measured evidence in the rationale — and only propose, never apply.
        policy.enabled = False
        db.commit()
        clear_outcome_prior_cache()
        promotion_mod.sweep_all_projects(db)
        proposal = db.scalar(
            select(Recommendation).where(
                Recommendation.project_id == env.project_id,
                Recommendation.dedupe_key.like("engine_learning:%"),
            )
        )
        report.check("paused_proven_path_reproposed", proposal is not None)
        report.check(
            "proposal_carries_measured_receipts",
            proposal is not None and "measured" in (proposal.rationale or "").lower(),
        )
        report.check("proposal_is_open_not_applied", proposal is not None and proposal.status == "open")
        db.expire_all()
        report.check("sweep_did_not_reenable_policy", policy.enabled is False)
        canary_scan(env, report)
    finally:
        db.close()
    report.finish()


@pytest.mark.anyio
async def test_v5_learning_refuses_a_degraded_path(sim_env, data_plane, monkeypatch):
    """After a real quality regression rolls a route back, the learning layer
    must mark the path quality-risk and refuse to re-propose it."""
    report = ValidationReport(scenario="v5_refuses_degraded")
    env = sim_env
    random.seed(13)
    monkeypatch.setattr(drift_mod, "MIN_ARM_SAMPLES", 8)
    monkeypatch.setattr(experiment_mod, "MIN_ARM_SAMPLES", 8)
    env.provider.profile(env.model_big, reply=lambda n: "Spam")
    env.provider.profile(env.model_small, reply=lambda n: "")  # bad from the start

    db = env.db()
    try:
        policy = _routing_policy(db, env, holdback="0.35")
        big = TrafficFactory(env, model=env.model_big, feature="support_agent", system_prompt=BIG_SYSTEM)
        responses = await run_traffic(data_plane, big, 50)
        request_ids = [r.headers["X-Varsten-Request-Id"] for r in responses if "X-Varsten-Request-Id" in r.headers]
        await _post_feedback(data_plane, env, request_ids[:10], outcome="rejected")

        rolled = drift_mod.check_and_rollback_drift(db, env.project(db), month_start(datetime.now(UTC)))
        db.expire_all()
        report.check("degraded_route_rolled_back", bool(rolled) and policy.enabled is False)

        promotion_mod.sweep_all_projects(db)
        priors = db.scalars(
            select(EngineOutcomePrior).where(
                EngineOutcomePrior.project_id == env.project_id,
                EngineOutcomePrior.model_chosen == env.model_small,
            )
        ).all()
        report.check(
            "priors_record_the_quality_failure",
            priors != []
            and all(
                (p.quality_pass_rate if p.quality_pass_rate is not None else Decimal("1")) < Decimal("0.5")
                for p in priors
            ),
            [(str(p.quality_pass_rate), p.readiness_status) for p in priors][:4],
        )
        report.check(
            "no_prior_is_recommendable",
            all(p.readiness_status not in {"recommendable", "auto_apply_candidate"} for p in priors),
            sorted({p.readiness_status for p in priors}),
        )
        proposal = db.scalar(
            select(Recommendation).where(
                Recommendation.project_id == env.project_id,
                Recommendation.dedupe_key.like("engine_learning:%"),
            )
        )
        report.check("degraded_path_never_reproposed", proposal is None)
        canary_scan(env, report)
    finally:
        db.close()
    report.finish()


@pytest.mark.anyio
async def test_v5_bandit_explores_within_budget_and_stats_chain_holds(sim_env, data_plane, monkeypatch):
    """Active bandit with a cold, eval-cleared challenger: the challenger may
    only receive the declared exploration budget's share of traffic, and every
    statistic the sampler saw must reconcile to the persisted prior rows."""
    report = ValidationReport(scenario="v5_bandit_budget")
    env = sim_env
    random.seed(20260704)
    monkeypatch.setattr(settings, "bandit_routing_mode", "active")
    monkeypatch.setattr(settings, "bandit_exploration_budget", 0.05)
    env.provider.profile(env.model_big, reply=lambda n: "Spam")
    env.provider.profile(env.model_small, reply=lambda n: "Spam")
    env.provider.profile(env.model_help, reply=lambda n: "Spam")  # the challenger

    db = env.db()
    try:
        # Build measured history for the primary first, so exploit has evidence.
        policy = _routing_policy(db, env, holdback="0.1")
        big = TrafficFactory(env, model=env.model_big, feature="support_agent", system_prompt=BIG_SYSTEM)
        await run_traffic(data_plane, big, 40)
        promotion_mod.sweep_all_projects(db)
        clear_outcome_prior_cache()

        # Clear the challenger through the real gate (safe eval verdict).
        db.add(
            EvalRun(
                organization_id=env.org_id,
                project_id=env.project_id,
                lever="model_downshift",
                route_key=env.model_big,
                incumbent_model=env.model_big,
                candidate_model=env.model_help,
                status="completed",
                verdict="safe",
                sample_count=30,
            )
        )
        db.commit()
        from app.proxy import routing as routing_mod

        db.refresh(policy)
        routing_mod.add_bandit_candidate(db, policy, env.model_help)
        db.commit()

        env.provider.calls.clear()
        await run_traffic(data_plane, big, 120)

        challenger_calls = env.provider.calls.get(env.model_help, 0)
        primary_calls = env.provider.calls.get(env.model_small, 0)
        routed = challenger_calls + primary_calls
        share = challenger_calls / routed if routed else 0.0
        report.metric("challenger_share", round(share, 4))
        report.metric("routed_requests", routed)
        # Budget 5%; allow generous sampling slack on ~100 draws, but nowhere near
        # unbounded: a challenger with zero evidence must stay a small minority.
        report.check("exploration_within_budget", share <= 0.15, share)
        report.check("primary_still_dominates", primary_calls > challenger_calls)

        # Chain of custody: the persisted prior rows the sampler reads must never
        # claim more evidence than the ledger holds.
        rows = db.scalars(
            select(EngineOutcomePrior).where(
                EngineOutcomePrior.project_id == env.project_id,
                EngineOutcomePrior.model_requested == env.model_big,
            )
        ).all()
        by_model: Counter = Counter()
        for row in rows:
            by_model[row.model_chosen] += row.sample_count
        decisions = db.scalars(
            select(RequestDecisionEvent).where(
                RequestDecisionEvent.project_id == env.project_id,
                RequestDecisionEvent.optimization_applied.is_(True),
            )
        ).all()
        # Prior rows were computed at the last sweep; they must never exceed what
        # the ledger holds (no phantom evidence).
        ledger_counts: Counter = Counter(d.model_chosen for d in decisions)
        phantom = {m: c for m, c in by_model.items() if c > ledger_counts.get(m, 0)}
        report.check("no_phantom_evidence_in_priors", not phantom, phantom)
        canary_scan(env, report)
    finally:
        db.close()
    report.finish()


def _run_regret_sim(rounds: int = 2000) -> tuple[dict, Decimal]:
    """Ground truth: candidate A saves 4x candidate B at equal quality. The
    bandit starts cold on both, with B as the incumbent primary."""
    truth = {"A": Decimal("0.020"), "B": Decimal("0.005")}
    counts = {"A": 0, "B": 0}
    realized = Decimal("0")
    for _ in range(rounds):
        candidates = [
            bandit.CandidateStats(
                model=name,
                provider="openai",
                sample_count=counts[name],
                quality_pass_rate=0.99 if counts[name] else None,
                average_savings_usd=truth[name] if counts[name] else None,
            )
            for name in ("A", "B")
        ]
        choice = bandit.select_candidate("B", "openai", candidates)
        picked = choice.model if choice.model in truth else "B"
        counts[picked] += 1
        realized += truth[picked]
    oracle = truth["A"] * rounds
    return counts, (oracle - realized) / oracle


def test_v5_bandit_regret_against_oracle(monkeypatch):
    """Sampler-level simulation against a known oracle. Convergence speed is
    bounded by the declared exploration budget BY DESIGN (no Thompson over
    savings magnitude — priors carry no variance), so the convergence assertion
    runs at a 10% budget; the default-budget regret is reported unasserted as
    the honest cost of the conservative design."""
    report = ValidationReport(scenario="v5_bandit_regret")
    random.seed(20260704)

    monkeypatch.setattr(settings, "bandit_exploration_budget", 0.10)
    counts, regret = _run_regret_sim()
    report.metric("counts_at_10pct_budget", counts)
    report.metric("regret_at_10pct_budget", str(round(regret, 4)))
    report.check("bandit_converges_on_the_better_arm", counts["A"] > 1500, counts)
    report.check("regret_bounded_at_10pct_budget", regret < Decimal("0.25"), str(regret))

    monkeypatch.setattr(settings, "bandit_exploration_budget", 0.02)
    default_counts, default_regret = _run_regret_sim()
    report.metric("counts_at_default_budget", default_counts)
    report.metric("regret_at_default_budget", str(round(default_regret, 4)))
    # Documented tradeoff, quantified not hidden: a 2% budget converges slowly on
    # cold candidates. Upgrading exploit to Thompson-over-savings (needs a
    # variance column on the priors) is the known follow-up.
    report.check("default_budget_still_converges_eventually", default_counts["A"] > 400, default_counts)
    report.finish()
