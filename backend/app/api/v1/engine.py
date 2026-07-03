from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import resolve_project
from app.db.session import get_db
from app.engine.outcomes import score_optimization_outcomes
from app.engine.reporting import summarize_feedback_outcomes, summarize_planner_traces
from app.models import Project, RequestDecisionEvent, RequestFeedback

router = APIRouter(prefix="/engine", tags=["engine"])


class CountBucket(BaseModel):
    key: str
    count: int


class SelectedActionBucket(BaseModel):
    action: str
    mode: str
    reason_code: str
    count: int


class PlannerClassificationSummary(BaseModel):
    risk_levels: dict[str, int]
    unknown_task_count: int
    personalized_count: int
    freshness_sensitive_count: int
    tools_present_count: int
    json_output_count: int
    multimodal_count: int
    top_task_types: list[CountBucket]
    top_reason_codes: list[CountBucket]


class PlannerLeverSummary(BaseModel):
    lever: str
    candidate_count: int
    statuses: dict[str, int]
    quality_gates: dict[str, int]
    risks: dict[str, int]
    top_reason_codes: list[CountBucket]
    policy_candidate_count: int


class RuntimeActionBucket(BaseModel):
    stage: str
    lever: str
    action: str
    reason_code: str
    enforced: bool
    count: int


class PlannerParitySummary(BaseModel):
    checked_count: int
    match_count: int
    mismatch_count: int
    match_rate: str | None
    top_mismatch_reasons: list[CountBucket]


class RuntimeTraceSummary(BaseModel):
    trace_count: int
    enforced_count: int
    stages: dict[str, int]
    parity: PlannerParitySummary
    top_actions: list[RuntimeActionBucket]


class SavingsProofTotals(BaseModel):
    baseline_cost_usd: str | None
    actual_cost_usd: str | None
    gross_savings_usd: str | None
    optimization_overhead_cost_usd: str | None
    net_savings_usd: str | None
    baseline_row_count: int
    actual_row_count: int
    gross_savings_row_count: int
    overhead_row_count: int
    net_savings_row_count: int


class SavingsProofSummary(BaseModel):
    proof_count: int
    missing_proof_count: int
    methods: list[CountBucket]
    confidences: list[CountBucket]
    quality_statuses: dict[str, int]
    pricing_statuses: dict[str, int]
    cost_sources: dict[str, int]
    top_reason_codes: list[CountBucket]
    totals: SavingsProofTotals


class FeedbackQualityScoreSummary(BaseModel):
    score_count: int
    average_score: str | None
    min_score: str | None
    max_score: str | None


class FeedbackContextBucket(BaseModel):
    dimension: str
    key: str
    feedback_count: int
    accepted_count: int
    corrective_count: int
    acceptance_rate: str | None


class FeedbackLearningReadiness(BaseModel):
    ready: bool
    reason_codes: list[str]


class FeedbackSummary(BaseModel):
    feedback_count: int
    decision_linked_count: int
    decision_unlinked_count: int
    usage_linked_count: int
    request_id_linked_count: int
    feedback_per_decision_rate: str | None
    accepted_count: int
    corrective_count: int
    acceptance_rate: str | None
    outcomes: list[CountBucket]
    sources: dict[str, int]
    top_failure_modes: list[CountBucket]
    quality_scores: FeedbackQualityScoreSummary
    top_contexts: list[FeedbackContextBucket]
    learning_readiness: FeedbackLearningReadiness


class LearningCandidateSegment(BaseModel):
    route_key: str
    task_type: str
    risk_level: str
    provider_requested: str
    model_requested: str
    provider_chosen: str
    model_chosen: str
    lever: str


class LearningCandidateQuality(BaseModel):
    measured_count: int
    passed_count: int
    failed_count: int
    pass_rate: str | None


class LearningCandidateFeedback(BaseModel):
    feedback_count: int
    decision_linked_count: int
    coverage_rate: str | None
    accepted_count: int
    corrective_count: int
    acceptance_rate: str | None
    top_failure_modes: list[CountBucket]


class LearningCandidateReadiness(BaseModel):
    status: str
    reason_codes: list[str]


class LearningCandidate(BaseModel):
    segment: LearningCandidateSegment
    sample_count: int
    measured_savings_count: int
    savings_measurement_rate: str | None
    total_gross_savings_usd: str | None
    average_gross_savings_usd: str | None
    pricing_statuses: dict[str, int]
    proof_confidences: list[CountBucket]
    quality: LearningCandidateQuality
    feedback: LearningCandidateFeedback
    readiness: LearningCandidateReadiness


class PlannerSummaryWindow(BaseModel):
    days: int
    start: datetime
    end: datetime


class PlannerSummaryOut(BaseModel):
    project_id: str
    window: PlannerSummaryWindow
    total_decisions: int
    planned_decisions: int
    unplanned_decisions: int
    planner_versions: list[CountBucket]
    selected_actions: list[SelectedActionBucket]
    classification: PlannerClassificationSummary
    levers: list[PlannerLeverSummary]
    runtime: RuntimeTraceSummary
    savings_proof: SavingsProofSummary
    feedback: FeedbackSummary
    learning_candidates: list[LearningCandidate]


@router.get("/planner-summary", response_model=PlannerSummaryOut)
def planner_summary(
    project: Project = Depends(resolve_project),
    db: Session = Depends(get_db),
    days: int = Query(default=30, ge=1, le=90),
) -> dict[str, Any]:
    """Read-side aggregate of observe-only planner traces.

    This endpoint reports what the planner considered. It does not trigger
    recommendations, mutate policies, or authorize any optimization.
    """
    end = datetime.now(UTC)
    start = end - timedelta(days=days)
    decision_rows = [
        dict(row._mapping)
        for row in db.execute(
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
            )
            .where(
                RequestDecisionEvent.project_id == project.id,
                RequestDecisionEvent.created_at >= start,
                RequestDecisionEvent.created_at <= end,
            )
            .order_by(RequestDecisionEvent.created_at.asc())
        )
    ]
    metadata_rows = [row["event_metadata"] for row in decision_rows]
    summary = summarize_planner_traces(metadata_rows, total_decisions=len(metadata_rows))
    feedback_rows = [
        dict(row._mapping)
        for row in db.execute(
            select(
                RequestFeedback.outcome.label("outcome"),
                RequestFeedback.source.label("source"),
                RequestFeedback.quality_score.label("quality_score"),
                RequestFeedback.failure_mode.label("failure_mode"),
                RequestFeedback.decision_event_id.label("decision_event_id"),
                RequestFeedback.usage_event_id.label("usage_event_id"),
                RequestFeedback.request_id.label("request_id"),
                RequestDecisionEvent.decision_type.label("decision_type"),
                RequestDecisionEvent.lever.label("lever"),
                RequestDecisionEvent.task_type.label("task_type"),
                RequestDecisionEvent.model_chosen.label("model_chosen"),
                RequestDecisionEvent.optimization_applied.label("optimization_applied"),
            )
            .outerjoin(RequestDecisionEvent, RequestFeedback.decision_event_id == RequestDecisionEvent.id)
            .where(
                RequestFeedback.project_id == project.id,
                RequestFeedback.created_at >= start,
                RequestFeedback.created_at <= end,
            )
            .order_by(RequestFeedback.created_at.asc())
        )
    ]
    feedback_summary = summarize_feedback_outcomes(feedback_rows, total_decisions=len(metadata_rows))
    learning_candidates = score_optimization_outcomes(decision_rows, feedback_rows)
    return {
        "project_id": str(project.id),
        "window": {"days": days, "start": start, "end": end},
        **summary,
        "feedback": feedback_summary,
        "learning_candidates": learning_candidates,
    }
