from __future__ import annotations

from dataclasses import replace

from app.engine.cache_policy import evaluate_cache_eligibility
from app.engine.classification import classify_request
from app.engine.types import (
    SELECTION_PRIORITY,
    CandidateOptimization,
    CandidateStatus,
    OptimizationPlan,
    OptimizationRisk,
    OutcomePrior,
    PlannerInput,
    QualityGateStatus,
    RequestClassification,
    SelectedAction,
)

# Statuses the proxy may act on now (no further gate) vs. those still shadowed.
_ENFORCEABLE = {CandidateStatus.ELIGIBLE, CandidateStatus.RECOMMENDABLE}


def build_optimization_plan(planner_input: PlannerInput) -> OptimizationPlan:
    """Build the optimization plan: classify the request, evaluate each lever into
    a candidate, and select the primary action the planner authorizes.

    The plan is advisory — the proxy still executes — but the selected action plus
    the per-candidate statuses are the single record the proxy's decisions are
    checked against (parity). Content-free: only derived flags and reason codes."""
    classification = classify_request(planner_input.request_facts or planner_input.body, planner_input.context)
    candidates = (
        _with_outcome_prior(_exact_cache_candidate(planner_input, classification), planner_input),
        _with_outcome_prior(_semantic_cache_candidate(planner_input, classification), planner_input),
        _with_outcome_prior(_model_routing_candidate(planner_input, classification), planner_input),
        _with_outcome_prior(_token_trim_candidate(planner_input, classification), planner_input),
        _with_outcome_prior(_prompt_compression_candidate(planner_input, classification), planner_input),
    )

    return OptimizationPlan(
        request_id=planner_input.request_id,
        provider=planner_input.provider,
        model=planner_input.model,
        classification=classification,
        candidates=candidates,
        selected=select_action(candidates, optimize_enabled=planner_input.optimize_enabled),
    )


# Backwards-compatible alias: callers and tests still import this name.
build_observe_only_plan = build_optimization_plan


def select_action(candidates: tuple[CandidateOptimization, ...], *, optimize_enabled: bool) -> SelectedAction:
    """The primary optimization the planner authorizes, walking lever priority.

    An enforceable candidate (eligible / recommendable) is selected in ``enforce``
    mode; failing that, the first shadow-only candidate is selected in ``shadow``
    mode so the intent is visible even before its gate clears; failing both, the
    request is ``observe`` (passthrough). The proxy never has to apply the selected
    action — it is the yardstick parity is measured against."""
    if not optimize_enabled:
        return SelectedAction(action="observe", mode="observe_only", reason_code="optimization_disabled")

    by_lever = {candidate.lever: candidate for candidate in candidates}
    shadow: CandidateOptimization | None = None
    for lever in SELECTION_PRIORITY:
        candidate = by_lever.get(lever)
        if candidate is None:
            continue
        if candidate.status in _ENFORCEABLE:
            return SelectedAction(action=lever, mode="enforce", reason_code=candidate.reason_code)
        if shadow is None and candidate.status == CandidateStatus.SHADOW_ONLY:
            shadow = candidate
    if shadow is not None:
        return SelectedAction(action=shadow.lever, mode="shadow", reason_code=shadow.reason_code)
    return SelectedAction(action="observe", mode="observe_only", reason_code="no_actionable_candidate")


def _exact_cache_candidate(
    planner_input: PlannerInput,
    classification: RequestClassification,
) -> CandidateOptimization:
    if not planner_input.optimize_enabled:
        return _unavailable("exact_cache", classification, "optimization_disabled")
    if not planner_input.exact_cache_enabled:
        return _unavailable("exact_cache", classification, "exact_cache_disabled")

    gate = evaluate_cache_eligibility("exact_cache", classification)
    if not gate.allowed:
        return CandidateOptimization(
            lever="exact_cache",
            status=CandidateStatus.REJECTED,
            quality_gate=QualityGateStatus.BLOCKED,
            risk=classification.risk_level,
            reason_code="cache_requires_explicit_policy",
            reason_detail=gate.metadata(),
        )

    return CandidateOptimization(
        lever="exact_cache",
        status=CandidateStatus.ELIGIBLE,
        quality_gate=QualityGateStatus.NOT_REQUIRED,
        risk=OptimizationRisk.LOW,
        reason_code="exact_cache_candidate",
        reason_detail=gate.metadata(),
    )


def _semantic_cache_candidate(
    planner_input: PlannerInput,
    classification: RequestClassification,
) -> CandidateOptimization:
    if not planner_input.optimize_enabled:
        return _unavailable("semantic_cache", classification, "optimization_disabled")
    if not planner_input.semantic_cache_enabled:
        return _unavailable("semantic_cache", classification, "semantic_cache_disabled")

    gate = evaluate_cache_eligibility("semantic_cache", classification)
    if not gate.allowed:
        return CandidateOptimization(
            lever="semantic_cache",
            status=CandidateStatus.REJECTED,
            quality_gate=QualityGateStatus.BLOCKED,
            risk=classification.risk_level,
            reason_code="semantic_cache_blocked_by_risk",
            reason_detail=gate.metadata(),
        )

    return CandidateOptimization(
        lever="semantic_cache",
        status=CandidateStatus.SHADOW_ONLY,
        quality_gate=QualityGateStatus.REQUIRED,
        risk=OptimizationRisk.MEDIUM,
        reason_code="semantic_cache_requires_quality_gate",
        reason_detail=gate.metadata(),
    )


def _model_routing_candidate(
    planner_input: PlannerInput,
    classification: RequestClassification,
) -> CandidateOptimization:
    if not planner_input.optimize_enabled:
        return _unavailable("model_routing", classification, "optimization_disabled")
    if not planner_input.routing_policy_present:
        return _unavailable("model_routing", classification, "routing_policy_missing")

    blockers = _routing_blockers(classification)
    if blockers:
        return CandidateOptimization(
            lever="model_routing",
            status=CandidateStatus.REJECTED,
            quality_gate=QualityGateStatus.BLOCKED,
            risk=classification.risk_level,
            reason_code="routing_blocked_by_risk",
            reason_detail={"blockers": blockers},
            policy_id=planner_input.routing_policy_id,
        )

    return CandidateOptimization(
        lever="model_routing",
        status=CandidateStatus.SHADOW_ONLY,
        quality_gate=QualityGateStatus.REQUIRED,
        risk=OptimizationRisk.MEDIUM,
        reason_code="routing_requires_eval_gate",
        policy_id=planner_input.routing_policy_id,
    )


def _token_trim_candidate(
    planner_input: PlannerInput,
    classification: RequestClassification,
) -> CandidateOptimization:
    if not planner_input.optimize_enabled:
        return _unavailable("token_trim", classification, "optimization_disabled")
    if not planner_input.trim_policy_present:
        return _unavailable("token_trim", classification, "trim_policy_missing")

    blockers = _trim_blockers(classification)
    if blockers:
        return CandidateOptimization(
            lever="token_trim",
            status=CandidateStatus.REJECTED,
            quality_gate=QualityGateStatus.BLOCKED,
            risk=classification.risk_level,
            reason_code="trim_blocked_by_context_risk",
            reason_detail={"blockers": blockers},
            policy_id=planner_input.trim_policy_id,
        )

    return CandidateOptimization(
        lever="token_trim",
        status=CandidateStatus.SHADOW_ONLY,
        quality_gate=QualityGateStatus.REQUIRED,
        risk=OptimizationRisk.MEDIUM,
        reason_code="trim_requires_quality_gate",
        policy_id=planner_input.trim_policy_id,
    )


def _prompt_compression_candidate(
    planner_input: PlannerInput,
    classification: RequestClassification,
) -> CandidateOptimization:
    """Same conservative blockers as trim: compression is also a body transform,
    and a risky/tool-coordinating/JSON-contract prompt is exactly where an
    approved rewrite could still surprise. The exact-hash match at execution time
    is the second, stricter gate."""
    if not planner_input.optimize_enabled:
        return _unavailable("prompt_compression", classification, "optimization_disabled")
    if not planner_input.compression_policy_present:
        return _unavailable("prompt_compression", classification, "compression_policy_missing")

    blockers = _trim_blockers(classification)
    if blockers:
        return CandidateOptimization(
            lever="prompt_compression",
            status=CandidateStatus.REJECTED,
            quality_gate=QualityGateStatus.BLOCKED,
            risk=classification.risk_level,
            reason_code="compression_blocked_by_context_risk",
            reason_detail={"blockers": blockers},
            policy_id=planner_input.compression_policy_id,
        )

    return CandidateOptimization(
        lever="prompt_compression",
        status=CandidateStatus.SHADOW_ONLY,
        quality_gate=QualityGateStatus.REQUIRED,
        risk=OptimizationRisk.MEDIUM,
        reason_code="compression_requires_quality_gate",
        policy_id=planner_input.compression_policy_id,
    )


def _unavailable(lever: str, classification: RequestClassification, reason_code: str) -> CandidateOptimization:
    return CandidateOptimization(
        lever=lever,
        status=CandidateStatus.UNAVAILABLE,
        quality_gate=QualityGateStatus.BLOCKED,
        risk=classification.risk_level,
        reason_code=reason_code,
    )


def _with_outcome_prior(candidate: CandidateOptimization, planner_input: PlannerInput) -> CandidateOptimization:
    prior = _prior_for(candidate.lever, planner_input.outcome_priors)
    if prior is None:
        return candidate

    reason_detail = {**candidate.reason_detail, "outcome_prior": _prior_metadata(prior)}
    if candidate.status == CandidateStatus.REJECTED:
        return replace(candidate, reason_detail=reason_detail)
    if candidate.status == CandidateStatus.UNAVAILABLE and candidate.reason_code not in {
        "routing_policy_missing",
        "trim_policy_missing",
    }:
        return replace(candidate, reason_detail=reason_detail)
    if prior.readiness_status not in {"recommendable", "auto_apply_candidate"}:
        return replace(candidate, reason_detail=reason_detail)

    return replace(
        candidate,
        status=CandidateStatus.RECOMMENDABLE,
        quality_gate=QualityGateStatus.PASSED,
        risk=OptimizationRisk.LOW,
        reason_code="outcome_prior_recommendable",
        reason_detail=reason_detail,
        estimated_savings_usd=prior.average_gross_savings_usd,
    )


def _prior_for(lever: str, priors: tuple[OutcomePrior, ...]) -> OutcomePrior | None:
    normalized = _normalize_lever(lever)
    for prior in priors:
        if _normalize_lever(prior.lever) == normalized:
            return prior
    return None


def _normalize_lever(lever: str) -> str:
    if lever == "model_downshift":
        return "model_routing"
    return lever


def _prior_metadata(prior: OutcomePrior) -> dict[str, object]:
    return {
        "readiness_status": prior.readiness_status,
        "sample_count": prior.sample_count,
        "measured_savings_count": prior.measured_savings_count,
        "total_gross_savings_usd": prior.total_gross_savings_usd,
        "average_gross_savings_usd": prior.average_gross_savings_usd,
        "quality_pass_rate": prior.quality_pass_rate,
        "feedback_acceptance_rate": prior.feedback_acceptance_rate,
        "reason_codes": list(prior.reason_codes),
    }


def _routing_blockers(classification: RequestClassification) -> list[str]:
    blockers: list[str] = []
    if classification.risky_or_unknown:
        blockers.append("risky_or_unknown")
    if classification.personalized:
        blockers.append("personalized_request")
    if classification.has_multimodal:
        blockers.append("multimodal_content")
    return blockers


def _trim_blockers(classification: RequestClassification) -> list[str]:
    blockers: list[str] = []
    if classification.risky_or_unknown:
        blockers.append("risky_or_unknown")
    if classification.has_tools:
        blockers.append("tools_present")
    if classification.wants_json:
        blockers.append("json_output")
    if classification.has_multimodal:
        blockers.append("multimodal_content")
    return blockers
