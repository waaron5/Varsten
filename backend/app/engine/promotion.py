"""Learning-loop promotion: measured outcome evidence becomes recommendations.

This is the edge that closes the engine's loop (roadmap phase A). Outcome
scoring (``app.engine.outcomes``) turns decision evidence + feedback into
readiness-tiered learning candidates; this module promotes the ones that
cleared the evidence bar (``recommendable`` / ``auto_apply_candidate``) into
``Recommendation`` rows so they enter the existing decision loop: eval gate ->
approve/apply -> policy activation -> holdback A/B -> drift guard.

Promotion never applies anything. It creates open recommendations only; the
apply path (with its eval gate) remains the sole authorization point, and the
readiness thresholds do the safety filtering upstream — a route rolled back for
quality drift scores ``quality_risk`` and never reaches this module.

Scope, deliberately narrow for the first slice:
- Only the policy-backed levers (model_downshift, smart_routing, token_trim).
  Cache and batching evidence comes from always-on levers with nothing to
  approve.
- A segment whose lever+model already has an enabled ProxyPolicy is skipped:
  the optimization is already running, so there is nothing to propose. The
  interesting promotions are paths whose policy was paused, dismissed, or
  rolled back and whose measured evidence says they were saving money at
  quality — the engine re-proposes them with receipts.
- Automation-mode upgrades (approve -> auto when readiness hits
  auto_apply_candidate on an enabled policy) are proposed as recommendations.
"""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.engine.outcomes import score_optimization_outcomes
from app.engine.priors import refresh_project_outcome_priors
from app.engine.route_identity import DEFAULT_ROUTE
from app.levers import LEVER_LABELS, LEVER_TOKEN_TRIM, ROUTING_LEVERS
from app.models import LeverConfig, Project, ProxyPolicy, RecommendationAction, RequestDecisionEvent, RequestFeedback
from app.proxy.experiment import compute_experiment
from app.proxy.trim import LEVER as TRIM_LEVER
from app.recommendations import RecommendationSeed, _upsert

logger = get_logger("varsten.engine.promotion")

PROMOTABLE_READINESS = frozenset({"recommendable", "auto_apply_candidate"})
PROMOTABLE_LEVERS = frozenset({*ROUTING_LEVERS, LEVER_TOKEN_TRIM})
HOLDBACK_LEVERS = frozenset({*ROUTING_LEVERS, TRIM_LEVER})

_DAYS_PER_MONTH = Decimal("30")
_CENTS = Decimal("0.01")
_HOLDBACK_DEFAULT = Decimal("0.05")
_HOLDBACK_STEP_2 = Decimal("0.02")
_HOLDBACK_FLOOR = Decimal("0.01")


def _dedupe_key(segment: dict[str, str], now: datetime) -> str:
    """Stable per-segment, per-month key. Hashed because model names alone can
    exceed the 255-char column; the readable identity lives in title/rationale."""
    digest = _segment_digest(segment)
    return f"engine_learning:{segment['lever']}:{digest}:{now:%Y-%m}"


def _segment_digest(segment: dict[str, str]) -> str:
    blob = json.dumps(segment, sort_keys=True, separators=(",", ":"))
    return hashlib.blake2b(blob.encode("utf-8"), digest_size=8).hexdigest()


def _automation_dedupe_key(segment: dict[str, str], now: datetime) -> str:
    digest = _segment_digest(segment)
    return f"engine_learning:automation:{segment['lever']}:{digest}:{now:%Y-%m}"


def _to_decimal(value) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _monthly_run_rate(total: Decimal | None, window_days: int) -> Decimal | None:
    if total is None or total <= 0 or window_days <= 0:
        return None
    return (total / Decimal(window_days) * _DAYS_PER_MONTH).quantize(_CENTS)


def _has_enabled_policy(
    db: Session, project_id, lever: str, incumbent_model: str, route_key: str | None = None
) -> bool:
    stmt = select(ProxyPolicy.id).where(
        ProxyPolicy.project_id == project_id,
        ProxyPolicy.lever == lever,
        ProxyPolicy.target_key == incumbent_model,
        ProxyPolicy.enabled.is_(True),
    )
    if route_key:
        exact = db.scalar(stmt.where(ProxyPolicy.route_key == route_key).limit(1))
        if exact is not None:
            return True
        stmt = stmt.where(ProxyPolicy.route_key == DEFAULT_ROUTE)
    return db.scalar(stmt.limit(1)) is not None


def _automation_config(db: Session, project_id, lever: str) -> LeverConfig | None:
    return db.scalar(
        select(LeverConfig).where(
            LeverConfig.project_id == project_id,
            LeverConfig.lever == lever,
            LeverConfig.enabled.is_(True),
            LeverConfig.automation_mode == "approve",
        )
    )


def _risk_level(segment_risk: str) -> str:
    return segment_risk if segment_risk in {"low", "medium", "high"} else "medium"


def _route_label(policy: ProxyPolicy, candidate: str) -> str:
    if policy.lever in ROUTING_LEVERS:
        return f"{policy.target_key} -> {candidate}"
    return f"{policy.target_key} (trim)"


def _title(segment: dict[str, str], monthly_savings: Decimal | None) -> str:
    label = LEVER_LABELS.get(segment["lever"], segment["lever"])
    if segment["lever"] in ROUTING_LEVERS and segment["model_chosen"] not in {"unknown", segment["model_requested"]}:
        target = f"{segment['model_requested']} -> {segment['model_chosen']}"
    else:
        target = segment["model_requested"]
    money = f" (~${monthly_savings}/mo measured)" if monthly_savings else ""
    return f"Learned: {label} on {target}{money}"[:255]


def _rationale(candidate: dict, window_days: int) -> str:
    quality = candidate["quality"]
    feedback = candidate["feedback"]
    readiness = candidate["readiness"]
    parts = [
        f"Promoted from measured production evidence over the last {window_days} days.",
        f"Samples: {candidate['sample_count']} optimized requests, "
        f"{candidate['measured_savings_count']} with measured savings "
        f"(total ${candidate['total_gross_savings_usd']}).",
    ]
    if quality["pass_rate"] is not None:
        parts.append(f"Objective quality pass rate: {quality['pass_rate']} ({quality['measured_count']} measured).")
    if feedback["acceptance_rate"] is not None:
        parts.append(f"Feedback acceptance rate: {feedback['acceptance_rate']} ({feedback['feedback_count']} signals).")
    parts.append(f"Readiness: {readiness['status']}.")
    return " ".join(parts)


def _automation_title(segment: dict[str, str]) -> str:
    label = LEVER_LABELS.get(segment["lever"], segment["lever"])
    return f"Learned: enable auto mode for {label} on {segment['model_requested']}"[:255]


def _automation_rationale(candidate: dict, window_days: int) -> str:
    quality = candidate["quality"]
    feedback = candidate["feedback"]
    parts = [
        f"Auto-readiness reached from production evidence over the last {window_days} days.",
        f"Samples: {candidate['sample_count']} optimized requests, "
        f"{candidate['measured_savings_count']} with measured savings "
        f"(total ${candidate['total_gross_savings_usd']}).",
    ]
    if quality["pass_rate"] is not None:
        parts.append(f"Objective quality pass rate: {quality['pass_rate']} ({quality['measured_count']} measured).")
    if feedback["acceptance_rate"] is not None:
        parts.append(f"Feedback acceptance rate: {feedback['acceptance_rate']} ({feedback['feedback_count']} signals).")
    parts.append("Readiness: auto_apply_candidate.")
    return " ".join(parts)


def _fetch_decision_rows(db: Session, project_id, start: datetime, end: datetime) -> list[dict]:
    rows = db.execute(
        select(
            RequestDecisionEvent.id.label("id"),
            RequestDecisionEvent.event_metadata.label("event_metadata"),
            RequestDecisionEvent.provider_requested.label("provider_requested"),
            RequestDecisionEvent.model_requested.label("model_requested"),
            RequestDecisionEvent.provider_chosen.label("provider_chosen"),
            RequestDecisionEvent.model_chosen.label("model_chosen"),
            RequestDecisionEvent.decision_type.label("decision_type"),
            RequestDecisionEvent.lever.label("lever"),
            RequestDecisionEvent.cache_status.label("cache_status"),
            RequestDecisionEvent.optimization_applied.label("optimization_applied"),
            RequestDecisionEvent.task_type.label("task_type"),
            RequestDecisionEvent.route_key.label("route_key"),
            RequestDecisionEvent.feature.label("feature"),
            RequestDecisionEvent.workflow.label("workflow"),
            RequestDecisionEvent.request_type.label("request_type"),
            RequestDecisionEvent.risk_level.label("risk_level"),
            RequestDecisionEvent.realized_savings_usd.label("realized_savings_usd"),
            RequestDecisionEvent.pricing_status.label("pricing_status"),
            RequestDecisionEvent.quality_ok.label("quality_ok"),
            RequestDecisionEvent.created_at.label("created_at"),
        ).where(
            RequestDecisionEvent.project_id == project_id,
            RequestDecisionEvent.created_at >= start,
            RequestDecisionEvent.created_at <= end,
        )
    )
    return [dict(row._mapping) for row in rows]


def _fetch_feedback_rows(db: Session, project_id, start: datetime, end: datetime) -> list[dict]:
    rows = db.execute(
        select(
            RequestFeedback.outcome.label("outcome"),
            RequestFeedback.failure_mode.label("failure_mode"),
            RequestFeedback.decision_event_id.label("decision_event_id"),
        ).where(
            RequestFeedback.project_id == project_id,
            RequestFeedback.created_at >= start,
            RequestFeedback.created_at <= end,
        )
    )
    return [dict(row._mapping) for row in rows]


def score_project_learning_candidates(
    db: Session,
    project: Project,
    *,
    now: datetime | None = None,
    window_days: int | None = None,
) -> list[dict]:
    at = now or datetime.now(UTC)
    days = window_days or settings.learning_promotion_window_days
    start = at - timedelta(days=days)
    decision_rows = _fetch_decision_rows(db, project.id, start, at)
    if not decision_rows:
        return []
    feedback_rows = _fetch_feedback_rows(db, project.id, start, at)
    return score_optimization_outcomes(
        decision_rows,
        feedback_rows,
        now=at,
        half_life_days=settings.learning_prior_half_life_days,
    )


def promote_learning_candidates(
    db: Session,
    project: Project,
    *,
    now: datetime | None = None,
    window_days: int | None = None,
    candidates: list[dict] | None = None,
) -> list[str]:
    """Promote evidence-cleared learning candidates into open recommendations.

    Returns the dedupe keys of the segments promoted (created or refreshed) this
    sweep. Commits are the caller's responsibility, matching the other
    recommendation writers.
    """
    at = now or datetime.now(UTC)
    days = window_days or settings.learning_promotion_window_days

    if candidates is None:
        candidates = score_project_learning_candidates(db, project, now=at, window_days=days)
    if not candidates:
        return []

    promoted: list[str] = []
    for candidate in candidates:
        segment = candidate["segment"]
        lever = segment["lever"]
        if candidate["readiness"]["status"] not in PROMOTABLE_READINESS:
            continue
        if lever not in PROMOTABLE_LEVERS:
            continue
        incumbent = segment["model_requested"]
        route_key = str(segment.get("route_key") or "default")
        if incumbent == "unknown" or _has_enabled_policy(db, project.id, lever, incumbent, route_key):
            continue

        monthly_savings = _monthly_run_rate(_to_decimal(candidate["total_gross_savings_usd"]), days)
        monthly_volume = int(Decimal(candidate["sample_count"]) / Decimal(days) * _DAYS_PER_MONTH)
        seed = RecommendationSeed(
            dedupe_key=_dedupe_key(segment, at),
            type=lever,
            title=_title(segment, monthly_savings),
            description=(
                "The engine measured this optimization path on live traffic and it cleared the "
                "evidence bar for savings and quality. No policy is currently running it. "
                "Applying re-activates it through the standard gate."
            ),
            # The window's savings are measured ledger facts, but the monthly
            # number is a forward projection of them, so it stays an estimate
            # until the holdback measures it live again (no painted-on savings).
            estimated_monthly_savings_usd=monthly_savings,
            risk_level=_risk_level(segment["risk_level"]),
            confidence="high" if candidate["readiness"]["status"] == "auto_apply_candidate" else "medium",
            lever=lever,
            target_type="route",
            target_key=route_key[:255],
            rationale=_rationale(candidate, days),
            monthly_request_volume=monthly_volume or None,
            measurement_method="estimated",
            related_provider=segment["provider_requested"] if segment["provider_requested"] != "unknown" else None,
            related_model=incumbent,
        )
        _upsert(db, project, seed)
        promoted.append(seed.dedupe_key)

    automation_promoted = propose_automation_upgrade_candidates(
        db,
        project,
        candidates,
        now=at,
        window_days=days,
    )
    promoted.extend(automation_promoted)

    if promoted:
        logger.info(
            "learning promotion created/refreshed recommendations",
            extra={"project_id": str(project.id), "count": len(promoted)},
        )
    return promoted


def propose_automation_upgrade_candidates(
    db: Session,
    project: Project,
    candidates: list[dict],
    *,
    now: datetime,
    window_days: int,
) -> list[str]:
    """Propose approve->auto upgrades when live evidence has earned it.

    This creates only a human-approved recommendation. It never flips
    ``LeverConfig.automation_mode`` directly.
    """
    promoted: list[str] = []
    for candidate in candidates:
        segment = candidate["segment"]
        lever = segment["lever"]
        if candidate["readiness"]["status"] != "auto_apply_candidate":
            continue
        if lever not in PROMOTABLE_LEVERS:
            continue
        incumbent = segment["model_requested"]
        route_key = str(segment.get("route_key") or "default")
        if incumbent == "unknown":
            continue
        if not _has_enabled_policy(db, project.id, lever, incumbent, route_key):
            continue
        if _automation_config(db, project.id, lever) is None:
            continue

        monthly_savings = _monthly_run_rate(_to_decimal(candidate["total_gross_savings_usd"]), window_days)
        monthly_volume = int(Decimal(candidate["sample_count"]) / Decimal(window_days) * _DAYS_PER_MONTH)
        seed = RecommendationSeed(
            dedupe_key=_automation_dedupe_key(segment, now),
            type="automation_upgrade",
            title=_automation_title(segment),
            description=(
                "This lever is already running under approve mode, and measured production evidence "
                "has reached the auto-apply readiness bar. Approving this proposal allows future "
                "equivalent changes for this lever to run automatically within guardrails."
            ),
            estimated_monthly_savings_usd=monthly_savings,
            risk_level=_risk_level(segment["risk_level"]),
            confidence="high",
            lever=lever,
            target_type="automation_mode",
            target_key=lever,
            rationale=_automation_rationale(candidate, window_days),
            monthly_request_volume=monthly_volume or None,
            measurement_method="estimated",
            related_provider=segment["provider_requested"] if segment["provider_requested"] != "unknown" else None,
            related_model=incumbent,
        )
        _upsert(db, project, seed)
        promoted.append(seed.dedupe_key)

    return promoted


def _holdback_candidate(policy: ProxyPolicy) -> str | None:
    if policy.lever in ROUTING_LEVERS:
        return policy.candidate_model
    if policy.lever == TRIM_LEVER:
        return policy.target_key
    return None


def _next_holdback(current: Decimal, experiment: dict) -> tuple[Decimal | None, str]:
    ci_low = _to_decimal(experiment.get("savings_per_request_ci_low_usd"))
    ci_high = _to_decimal(experiment.get("savings_per_request_ci_high_usd"))
    if ci_low is None or ci_high is None or not experiment.get("has_signal"):
        return None, "insufficient_signal"

    if ci_low > 0:
        if current > _HOLDBACK_DEFAULT:
            return _HOLDBACK_DEFAULT, "confident_savings_reduce_to_standard_holdback"
        if current > _HOLDBACK_STEP_2:
            return _HOLDBACK_STEP_2, "confident_savings_reduce_holdback"
        if current > _HOLDBACK_FLOOR:
            return _HOLDBACK_FLOOR, "confident_savings_reduce_holdback"
        return None, "holdback_at_floor"

    if current < _HOLDBACK_DEFAULT and ci_low <= 0 <= ci_high:
        return _HOLDBACK_DEFAULT, "savings_confidence_reincluded_zero"

    return None, "no_holdback_change"


def _holdback_action_title(policy: ProxyPolicy, candidate: str, old: Decimal, new: Decimal) -> str:
    direction = "Reduce" if new < old else "Restore"
    return f"{direction} holdback for {_route_label(policy, candidate)}: {old} -> {new}"[:255]


def _holdback_action_detail(reason: str, experiment: dict) -> str:
    return (
        f"Adaptive holdback adjustment reason={reason}. "
        f"control_requests={experiment.get('control_requests')}, "
        f"treatment_requests={experiment.get('treatment_requests')}, "
        f"savings_per_request={experiment.get('savings_per_request_usd')}, "
        f"cs_low={experiment.get('savings_per_request_ci_low_usd')}, "
        f"cs_high={experiment.get('savings_per_request_ci_high_usd')}."
    )


def adjust_adaptive_holdbacks(
    db: Session,
    project: Project,
    *,
    now: datetime | None = None,
    window_days: int | None = None,
) -> list[dict[str, str]]:
    """Adjust live holdback cost when the sequential experiment has enough signal.

    The policy change is small and reversible: confident positive savings step
    holdback down (5% -> 2% -> 1%), while a confidence sequence that includes
    zero restores the standard 5% measurement rate. Every change is written as a
    system action so the customer can audit why measurement cost moved.
    """
    at = now or datetime.now(UTC)
    days = window_days or settings.learning_promotion_window_days
    period_start = at - timedelta(days=days)
    policies = list(
        db.scalars(
            select(ProxyPolicy).where(
                ProxyPolicy.project_id == project.id,
                ProxyPolicy.lever.in_(HOLDBACK_LEVERS),
                ProxyPolicy.enabled.is_(True),
            )
        )
    )

    adjusted: list[dict[str, str]] = []
    for policy in policies:
        candidate = _holdback_candidate(policy)
        if not candidate:
            continue
        try:
            experiment = compute_experiment(db, project.id, policy.target_key, candidate, period_start)
        except Exception:
            logger.exception(
                "adaptive holdback lookup failed; leaving policy unchanged",
                extra={"project_id": str(project.id), "policy_id": str(policy.id)},
            )
            continue
        current = Decimal(policy.holdback_percent or 0)
        proposed, reason = _next_holdback(current, experiment)
        if proposed is None or proposed == current:
            continue
        policy.holdback_percent = proposed
        db.add(
            RecommendationAction(
                organization_id=project.organization_id,
                project_id=project.id,
                recommendation_id=policy.source_recommendation_id,
                actor_user_id=None,
                lever=policy.lever,
                action_type="holdback_adjusted",
                status="completed",
                source="system",
                title=_holdback_action_title(policy, candidate, current, proposed),
                detail=_holdback_action_detail(reason, experiment),
                occurred_at=at,
            )
        )
        adjusted.append(
            {
                "policy_id": str(policy.id),
                "lever": policy.lever,
                "route": _route_label(policy, candidate),
                "old_holdback_percent": str(current),
                "new_holdback_percent": str(proposed),
                "reason": reason,
            }
        )

    if adjusted:
        db.flush()
        logger.info(
            "adaptive holdback adjusted policies",
            extra={"project_id": str(project.id), "count": len(adjusted)},
        )
    return adjusted


def sweep_all_projects(db: Session, *, now: datetime | None = None) -> dict[str, dict[str, list]]:
    """Run learning promotion and adaptive holdback management for active projects.

    The scheduler's entry point; idempotent for recommendations (dedupe keys make
    re-promotion a refresh, and non-open recommendations are never resurrected).
    Holdback adjustments are emitted only when the policy value changes.
    """
    at = now or datetime.now(UTC)
    days = settings.learning_promotion_window_days
    start = at - timedelta(days=days)
    project_ids = set(
        db.scalars(select(RequestDecisionEvent.project_id).where(RequestDecisionEvent.created_at >= start).distinct())
    )
    project_ids.update(
        db.scalars(
            select(ProxyPolicy.project_id)
            .where(
                ProxyPolicy.lever.in_(HOLDBACK_LEVERS),
                ProxyPolicy.enabled.is_(True),
            )
            .distinct()
        )
    )
    results: dict[str, dict[str, list]] = {}
    for pid in project_ids:
        project = db.get(Project, pid)
        if project is None:
            continue
        candidates = score_project_learning_candidates(db, project, now=at, window_days=days)
        refresh_project_outcome_priors(db, project, candidates, window_days=days, computed_at=at)
        promoted = promote_learning_candidates(db, project, now=at, window_days=days, candidates=candidates)
        adjusted = adjust_adaptive_holdbacks(db, project, now=at, window_days=days)
        if promoted or adjusted:
            results[str(pid)] = {"promoted": promoted, "holdback_adjusted": adjusted}
    db.commit()
    return results
