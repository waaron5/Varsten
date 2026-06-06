"""Apply gate.

A medium-risk, model-swapping lever (cheaper_model, smart_routing) cannot be
applied until a shadow eval on the route's real traffic has cleared. This is the
safety contract that turns "estimated" recommendations into "quality-verified"
ones. The objective, low-risk levers (semantic_cache, token_trim, batching) are
not gated: they do not change which model answers, so there is no quality risk to
prove away.

Verdict -> apply policy:
    safe          auto or human may apply (objective parity proven)
    needs_human   human may approve; automation may NOT auto-apply (judge noise)
    unsafe        blocked
    insufficient  blocked (gather more samples first)
    no run / pending / failed  blocked (must evaluate first)
"""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import EvalRun, Recommendation
from app.models.eval import (
    RUN_COMPLETED,
    VERDICT_NEEDS_HUMAN,
    VERDICT_SAFE,
)

GATED_LEVERS = {"cheaper_model", "smart_routing"}


class EvalGateError(Exception):
    """Applying is blocked because the route has not cleared shadow evaluation."""


def is_gated(recommendation: Recommendation) -> bool:
    return recommendation.lever in GATED_LEVERS


def latest_run(db: Session, recommendation_id) -> EvalRun | None:
    return db.scalar(
        select(EvalRun)
        .where(EvalRun.recommendation_id == recommendation_id)
        .order_by(EvalRun.created_at.desc())
        .limit(1)
    )


def assert_appliable(db: Session, recommendation: Recommendation, *, automated: bool) -> EvalRun | None:
    """Raise EvalGateError unless this recommendation may be applied now. Returns
    the gating run (or None for an ungated lever) so the caller can attach the
    measured savings."""
    if not is_gated(recommendation):
        return None

    run = latest_run(db, recommendation.id)
    if run is None or run.status != RUN_COMPLETED:
        raise EvalGateError(
            "This route must pass a shadow evaluation before it can be applied. "
            "Run an eval on the candidate model first."
        )
    if run.verdict == VERDICT_SAFE:
        return run
    if run.verdict == VERDICT_NEEDS_HUMAN:
        if automated:
            raise EvalGateError(
                "Subjective route: the eval cleared for human approval but not for "
                "automatic apply. Approve it manually."
            )
        return run
    raise EvalGateError(f"Shadow evaluation did not clear (verdict: {run.verdict}). {run.notes or ''}".strip())


def apply_measured_savings(recommendation: Recommendation, run: EvalRun | None) -> None:
    """When a passing run produced a measured cost delta, upgrade the recommendation
    from an estimate to the measured number so Proof attributes real dollars. The
    estimate stays the fallback when the run measured nothing."""
    if run is None or run.cost_delta_usd is None or run.cost_delta_usd <= Decimal("0"):
        return
    recommendation.estimated_monthly_savings_usd = run.cost_delta_usd
    recommendation.measurement_method = "replay_measured"
