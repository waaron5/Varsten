"""Shadow-evaluation runner.

Given an EvalRun (incumbent_model -> candidate_model on a route), replays the
route's stored samples through the candidate, scores each pair, and writes an
auditable verdict. Runs in a worker, never in the request hot path.

The two model-calling steps (replay, judge) are injected so the aggregation and
verdict logic is unit-testable with no network. Defaults call OpenAI off-path.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import AsyncSessionLocal
from app.engine import governance
from app.eval import scoring
from app.eval.failure_registry import record_failure
from app.eval.openai_ops import judge_pairwise, replay_candidate
from app.levers import LEVER_MODEL_DOWNSHIFT
from app.models import EvalRun, EvalSampleResult, Project, Recommendation, ReplaySample, UsageEvent
from app.models.eval import (
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_RUNNING,
    SOURCE_GOLDEN,
    VERDICT_INSUFFICIENT,
    VERDICT_NEEDS_HUMAN,
    VERDICT_SAFE,
    VERDICT_UNSAFE,
)
from app.pricing import price_usage_event
from app.proxy import predicate as predicate_mod

logger = get_logger("varsten.eval.runner")

# Tolerance on the confidence-interval lower bound. A candidate can be marginally
# below incumbent within noise and still be acceptable; meaningful degradation is
# not. Objective-family runs use this band; judge runs require lo >= 0 (stricter,
# because they can never auto-apply anyway).
_CI_TOLERANCE = Decimal("-0.05")


def _prompt_text(messages: list[dict]) -> str:
    parts = []
    for m in messages or []:
        content = m.get("content", "")
        if isinstance(content, list):
            content = " ".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
        parts.append(f"{m.get('role', '')}: {content}")
    return "\n".join(parts).strip()


def _usage_tokens(payload: dict) -> tuple[int, int]:
    usage = payload.get("usage") or {}
    return int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)


async def _price_usage(
    org_id: uuid.UUID,
    model: str,
    in_tok: int,
    out_tok: int,
    at: datetime,
) -> tuple[Decimal | None, str, str, uuid.UUID | None]:
    # pricing is async; run_eval is a coroutine, so bridge by opening a scoped
    # AsyncSession here rather than threading one through run_eval's sync session.
    # Pricing reads stable catalog data, so a separate session is consistent.
    async with AsyncSessionLocal() as adb:
        return await price_usage_event(
            adb,
            organization_id=org_id,
            model_key=model,
            provider="openai",
            input_tokens=in_tok,
            output_tokens=out_tok,
            cached_input_tokens=0,
            reported_cost_usd=None,
            at=at,
        )


async def _price(org_id: uuid.UUID, model: str, in_tok: int, out_tok: int, at: datetime) -> Decimal | None:
    cost, _, _, _ = await _price_usage(org_id, model, in_tok, out_tok, at)
    return cost


async def _record_eval_replay_overhead(
    db: Session,
    run: EvalRun,
    input_tokens: int,
    output_tokens: int,
    at: datetime,
) -> None:
    """Persist the real candidate replay cost as optimization overhead.

    The row commits with the eval run's result, so a completed run carries all of
    the replay cost that produced its verdict.
    """
    try:
        cost, cost_source, pricing_status, price_version_id = await _price_usage(
            run.organization_id,
            run.candidate_model,
            input_tokens,
            output_tokens,
            at,
        )
        db.add(
            UsageEvent(
                project_id=run.project_id,
                organization_id=run.organization_id,
                api_key_id=None,
                source="overhead",
                provider="openai",
                model=run.candidate_model,
                operation="eval_replay",
                request_type="eval_replay",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_input_tokens=0,
                total_tokens=input_tokens + output_tokens,
                cost_usd=cost,
                cost_source=cost_source,
                pricing_status=pricing_status,
                price_version_id=price_version_id,
                currency="USD",
                status="success",
                success=True,
                event_metadata={"overhead": "eval_replay", "eval_run_id": str(run.id)},
                occurred_at=at,
                environment="production",
            )
        )
    except Exception:
        logger.exception("eval replay overhead metering failed", extra={"eval_run_id": str(run.id)})


def _eligible_for_smart_routing(sample: ReplaySample) -> bool:
    """Whether a captured sample would be routed to the candidate under the default
    smart-routing predicate (the same one activation seeds)."""
    body = {"messages": sample.request_messages, **(sample.request_params or {})}
    return predicate_mod.is_eligible(body, predicate_mod.DEFAULT_PREDICATE)


def select_samples(db: Session, run: EvalRun) -> list[ReplaySample]:
    """Samples for the route, golden first (strongest), then newest traffic that
    has an incumbent answer to compare against. Capped for run cost."""
    stmt = (
        select(ReplaySample)
        .where(
            ReplaySample.project_id == run.project_id,
            ReplaySample.route_key == run.route_key,
        )
        .where((ReplaySample.source == SOURCE_GOLDEN) | (ReplaySample.incumbent_response.is_not(None)))
        # Golden (expected_output set) first, then most recent traffic.
        .order_by(ReplaySample.expected_output.is_(None), ReplaySample.created_at.desc())
        .limit(settings.eval_replay_max_samples)
    )
    return list(db.scalars(stmt))


async def run_eval(
    db: Session,
    run: EvalRun,
    *,
    key: str,
    replay_fn=replay_candidate,
    judge_fn=judge_pairwise,
    now: datetime | None = None,
    source_dataset: str = "unknown",
) -> EvalRun:
    at = now or datetime.now(UTC)
    run.status = RUN_RUNNING
    db.commit()

    try:
        samples = select_samples(db, run)
        # Smart routing only ever sends the predicate-eligible subset to the
        # candidate, so prove the candidate on exactly that subset, not on traffic
        # it would never receive.
        if run.lever == "smart_routing":
            samples = [s for s in samples if _eligible_for_smart_routing(s)]
        scores: list[Decimal] = []
        scorers: set[str] = set()
        obj_total = 0
        obj_pass = 0
        cost_deltas: list[Decimal] = []

        for sample in samples:
            cand_payload = await replay_fn(sample.request_messages, sample.request_params, run.candidate_model, key)
            if cand_payload is None:
                continue  # replay failed; skip rather than poison the verdict
            cand_in, cand_out = _usage_tokens(cand_payload)
            await _record_eval_replay_overhead(db, run, cand_in, cand_out, at)
            cand_text = scoring.assistant_text(cand_payload)
            inc_text = scoring.assistant_text(sample.incumbent_response)

            scorer, score, obj = scoring.score_sample(sample, inc_text, cand_text)
            winner: str | None = None
            judge_reasoning: str = ""
            if obj is None:
                # No objective signal: fall back to the pairwise judge (approve-only).
                winner, judge_reasoning = await judge_fn(
                    _prompt_text(sample.request_messages), inc_text, cand_text, key
                )
                score, _ = scoring.judge_score(winner)
                scorer = scoring.SCORER_JUDGE
            else:
                obj_total += 1
                obj_pass += 1 if obj else 0
            scorers.add(scorer)
            scores.append(score)

            inc_cost = await _price(
                run.organization_id, run.incumbent_model, sample.input_tokens, sample.output_tokens, at
            )
            cand_cost = await _price(
                run.organization_id, run.candidate_model, cand_in or sample.input_tokens, cand_out, at
            )
            if inc_cost is not None and cand_cost is not None:
                cost_deltas.append(inc_cost - cand_cost)

            db.add(
                EvalSampleResult(
                    eval_run_id=run.id,
                    replay_sample_id=sample.id,
                    candidate_response=cand_payload,
                    scorer=scorer,
                    objective_pass=obj,
                    judge_winner=winner,
                    score=score,
                    candidate_cost_usd=cand_cost,
                    incumbent_cost_usd=inc_cost,
                )
            )

            # Failure registry: append a structured record for every candidate loss.
            if score < 0:
                record_failure(
                    incumbent_model=run.incumbent_model,
                    candidate_model=run.candidate_model,
                    messages=sample.request_messages or [],
                    incumbent_response=sample.incumbent_response,
                    candidate_response=cand_payload,
                    judge_reasoning=judge_reasoning or (f"objective_fail:{scorer}" if obj is False else ""),
                    incumbent_score=1.0 if score < 0 else 0.0,
                    candidate_score=float(score),
                    source_dataset=source_dataset,
                    input_tokens=sample.input_tokens or 0,
                    output_tokens=sample.output_tokens or 0,
                )

        _finalize(db, run, scores, scorers, obj_total, obj_pass, cost_deltas, at)
    except Exception as exc:
        db.rollback()
        run.status = RUN_FAILED
        run.error = f"{exc.__class__.__name__}: {exc}"
        run.completed_at = at
        db.commit()
        logger.exception("eval run failed", extra={"eval_run_id": str(run.id)})
    return run


def _finalize(
    db: Session,
    run: EvalRun,
    scores: list[Decimal],
    scorers: set[str],
    obj_total: int,
    obj_pass: int,
    cost_deltas: list[Decimal],
    at: datetime,
) -> None:
    run.sample_count = len(scores)
    run.win_count = sum(1 for s in scores if s > 0)
    run.tie_count = sum(1 for s in scores if s == 0)
    run.loss_count = sum(1 for s in scores if s < 0)

    mean, lo, hi = scoring.mean_ci(scores)
    run.score_delta = mean
    run.score_delta_ci_low = lo
    run.score_delta_ci_high = hi

    obj_rate = Decimal(str(round(obj_pass / obj_total, 4))) if obj_total else None
    run.objective_pass_count = obj_pass if obj_total else None
    run.objective_pass_rate = obj_rate

    has_judge = scoring.SCORER_JUDGE in scorers
    if scorers == {scoring.SCORER_GOLDEN}:
        run.scorer_type = "golden"
    elif scorers == {scoring.SCORER_OBJECTIVE}:
        run.scorer_type = "objective"
    elif scorers == {scoring.SCORER_JUDGE}:
        run.scorer_type = "judge"
    elif scorers:
        run.scorer_type = "mixed"

    run.cost_delta_usd = _measured_cost_delta(db, run, cost_deltas)

    if len(scores) < settings.eval_min_samples:
        run.verdict = VERDICT_INSUFFICIENT
        run.notes = (
            f"Only {len(scores)} samples scored (need {settings.eval_min_samples}). "
            "Capture more traffic or add a golden set before this can gate an apply."
        )
    elif has_judge:
        # Any subjective scoring means the verdict can never be auto-applied.
        # Judge noise is too high to bet auto-rollback on (CLAUDE.md), so the best
        # outcome is approve-mode with the evidence shown.
        if lo >= 0:
            run.verdict = VERDICT_NEEDS_HUMAN
            run.notes = "Subjective route: no significant degradation, route to human approval."
        else:
            run.verdict = VERDICT_UNSAFE
            run.notes = "Judge found the candidate worse beyond noise. Blocked."
    else:
        # Objective-family run: the only path to auto-eligibility.
        if obj_rate is not None and float(obj_rate) >= settings.eval_objective_pass_threshold and lo >= _CI_TOLERANCE:
            run.verdict = VERDICT_SAFE
            run.notes = f"Objective parity {obj_rate} >= {settings.eval_objective_pass_threshold}. Auto-eligible."
        else:
            run.verdict = VERDICT_UNSAFE
            run.notes = f"Objective parity {obj_rate} below bar or interval shows degradation. Blocked."

    run.status = RUN_COMPLETED
    run.completed_at = at

    # Governance: an actionable verdict on a routing-lever recommendation proposes
    # a ChangeRequest carrying this run's evidence bundle for a named human to
    # decide. Self-guarding; a governance failure never fails the eval.
    governance.ensure_change_request(db, run)

    db.commit()


def _measured_cost_delta(db: Session, run: EvalRun, cost_deltas: list[Decimal]) -> Decimal | None:
    """Measured per-request savings extrapolated to the route's monthly volume from
    the linked recommendation. This is a MEASURED number (real candidate token
    usage at catalog price), stronger than the recommendation's estimate."""
    if not cost_deltas:
        return None
    per_request = sum(cost_deltas) / Decimal(len(cost_deltas))
    volume = None
    if run.recommendation_id is not None:
        rec = db.get(Recommendation, run.recommendation_id)
        if rec is not None:
            volume = rec.monthly_request_volume
    multiplier = Decimal(volume) if volume else Decimal(len(cost_deltas))
    return (per_request * multiplier).quantize(Decimal("0.00000001"))


def create_run_for_recommendation(
    db: Session, project: Project, recommendation: Recommendation, candidate_model: str
) -> EvalRun:
    """Open a pending eval run for a model-downshift recommendation. route_key and
    incumbent_model come from the recommendation's target model."""
    run = EvalRun(
        organization_id=project.organization_id,
        project_id=project.id,
        recommendation_id=recommendation.id,
        lever=recommendation.lever or LEVER_MODEL_DOWNSHIFT,
        route_key=recommendation.related_model or recommendation.target_key or "",
        incumbent_model=recommendation.related_model or "",
        candidate_model=candidate_model,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run
