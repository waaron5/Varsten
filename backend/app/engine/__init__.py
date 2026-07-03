"""Provider-agnostic optimization planner primitives.

The planner remains conservative and observe-first, while selected runtime gates
consume its content-free classifications to keep unsafe optimizations out of the
hot path.
"""

from app.engine.cache_policy import CacheEligibilityDecision, evaluate_cache_eligibility
from app.engine.classification import classify_request
from app.engine.outcomes import outcome_prior_from_learning_candidate, score_optimization_outcomes
from app.engine.planner import build_observe_only_plan, build_optimization_plan, select_action
from app.engine.request_facts import normalize_request_facts
from app.engine.runtime_trace import runtime_trace_event
from app.engine.serialization import plan_to_metadata
from app.engine.types import (
    CandidateOptimization,
    CandidateStatus,
    OptimizationPlan,
    OptimizationRisk,
    OutcomePrior,
    PlannerInput,
    QualityGateStatus,
    RequestClassification,
    RequestFacts,
    SelectedAction,
)

__all__ = [
    "CacheEligibilityDecision",
    "CandidateOptimization",
    "CandidateStatus",
    "OptimizationPlan",
    "OptimizationRisk",
    "OutcomePrior",
    "PlannerInput",
    "QualityGateStatus",
    "RequestClassification",
    "RequestFacts",
    "SelectedAction",
    "build_observe_only_plan",
    "build_optimization_plan",
    "classify_request",
    "evaluate_cache_eligibility",
    "normalize_request_facts",
    "outcome_prior_from_learning_candidate",
    "plan_to_metadata",
    "runtime_trace_event",
    "score_optimization_outcomes",
    "select_action",
]
