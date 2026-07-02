import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.engine.reporting import summarize_feedback_outcomes, summarize_planner_traces
from app.models import Project, RequestDecisionEvent, RequestFeedback


def _b(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _plan_metadata(
    *,
    risk_level: str = "low",
    task_type: str | None = "classification.intent",
    unknown_task: bool = False,
    freshness_sensitive: bool = False,
    personalized: bool = False,
    has_tools: bool = False,
    wants_json: bool = False,
    reason_codes: list[str] | None = None,
    route_policy_id: str | None = None,
    runtime_trace: list[dict] | None = None,
    savings_proof: dict | None = None,
) -> dict:
    metadata = {
        "optimization_plan": {
            "planner_version": "planner_v1_observe_only",
            "selected": {"action": "observe", "mode": "observe_only", "reason_code": "planner_not_wired"},
            "classification": {
                "task_type": task_type,
                "task_confidence": 0.9 if task_type else None,
                "risk_level": risk_level,
                "prompt_chars": 24,
                "message_count": 1,
                "has_tools": has_tools,
                "wants_json": wants_json,
                "has_multimodal": False,
                "personalized": personalized,
                "freshness_sensitive": freshness_sensitive,
                "unknown_task": unknown_task,
                "reason_codes": reason_codes or [],
            },
            "candidates": [
                {
                    "lever": "exact_cache",
                    "status": "eligible" if risk_level == "low" else "rejected",
                    "quality_gate": "not_required" if risk_level == "low" else "blocked",
                    "risk": risk_level,
                    "reason_code": "exact_cache_candidate" if risk_level == "low" else "cache_requires_explicit_policy",
                    "reason_detail": {},
                    "policy_id": None,
                },
                {
                    "lever": "model_routing",
                    "status": "shadow_only" if risk_level == "low" else "rejected",
                    "quality_gate": "required" if risk_level == "low" else "blocked",
                    "risk": "medium" if risk_level == "low" else risk_level,
                    "reason_code": "routing_requires_eval_gate" if risk_level == "low" else "routing_blocked_by_risk",
                    "reason_detail": {},
                    "policy_id": route_policy_id,
                },
            ],
        },
        "runtime_trace": runtime_trace or [],
    }
    if savings_proof is not None:
        metadata["savings_proof"] = savings_proof
    return metadata


def _savings_proof(
    *,
    method: str = "cache_avoidance",
    confidence: str = "measured_priced",
    baseline: str | None = "0.20",
    actual: str | None = "0.05",
    gross: str | None = "0.15",
    quality_status: str = "passed",
    reason_codes: list[str] | None = None,
) -> dict:
    return {
        "method": method,
        "baseline_cost_usd": baseline,
        "actual_cost_usd": actual,
        "gross_savings_usd": gross,
        "optimization_overhead_cost_usd": None,
        "net_savings_usd": None,
        "confidence": confidence,
        "quality_status": quality_status,
        "pricing_status": "priced",
        "cost_source": "catalog",
        "price_version_id": str(uuid.uuid4()),
        "reason_codes": reason_codes or ["optimization_overhead_not_measured"],
    }


def _decision(
    project: Project,
    *,
    request_id: str,
    metadata: dict,
    created_at: datetime | None = None,
    decision_type: str = "passthrough",
    lever: str | None = None,
    model_chosen: str = "gpt-4o-mini",
    task_type: str | None = "classification.intent",
    optimization_applied: bool = False,
):
    return RequestDecisionEvent(
        organization_id=project.organization_id,
        project_id=project.id,
        request_id=request_id,
        provider_requested="openai",
        model_requested="gpt-4o-mini",
        decision_type=decision_type,
        lever=lever,
        model_chosen=model_chosen,
        task_type=task_type,
        optimization_applied=optimization_applied,
        event_metadata=metadata,
        created_at=created_at or datetime.now(UTC),
    )


def test_summarize_planner_traces_counts_statuses_and_reasons():
    summary = summarize_planner_traces(
        [
            _plan_metadata(
                route_policy_id="route-policy-1",
                runtime_trace=[
                    {
                        "stage": "cache_lookup",
                        "lever": "exact_cache",
                        "action": "hit",
                        "reason_code": "exact_cache_hit",
                        "enforced": False,
                    },
                    {
                        "stage": "cache_lookup",
                        "lever": "semantic_cache",
                        "action": "skipped",
                        "reason_code": "semantic_cache_policy_blocked",
                        "enforced": True,
                    },
                ],
                savings_proof=_savings_proof(),
            ),
            _plan_metadata(
                risk_level="high",
                task_type="finance.trade",
                freshness_sensitive=True,
                personalized=True,
                reason_codes=["risk_high", "freshness_sensitive", "personalized_request"],
                route_policy_id="route-policy-2",
                savings_proof=_savings_proof(
                    method="holdback_observation",
                    confidence="requires_aggregate_holdback",
                    baseline="0.12",
                    actual="0.12",
                    gross=None,
                    reason_codes=["aggregate_holdback_required", "optimization_overhead_not_measured"],
                ),
            ),
            {
                "savings_proof": _savings_proof(
                    method="none",
                    confidence="not_applicable",
                    baseline=None,
                    actual="0.01",
                    gross=None,
                    quality_status="not_measured",
                    reason_codes=["quality_not_measured", "optimization_overhead_not_measured"],
                )
            },
            {},
        ],
        total_decisions=4,
    )

    assert summary["total_decisions"] == 4
    assert summary["planned_decisions"] == 2
    assert summary["unplanned_decisions"] == 2
    assert summary["planner_versions"] == [{"key": "planner_v1_observe_only", "count": 2}]
    assert summary["selected_actions"] == [
        {"action": "observe", "mode": "observe_only", "reason_code": "planner_not_wired", "count": 2}
    ]
    assert summary["classification"]["risk_levels"] == {"high": 1, "low": 1}
    assert summary["classification"]["freshness_sensitive_count"] == 1
    assert summary["classification"]["personalized_count"] == 1

    levers = {row["lever"]: row for row in summary["levers"]}
    assert levers["exact_cache"]["statuses"] == {"eligible": 1, "rejected": 1}
    assert levers["model_routing"]["statuses"] == {"rejected": 1, "shadow_only": 1}
    assert levers["model_routing"]["policy_candidate_count"] == 2
    assert {"key": "routing_requires_eval_gate", "count": 1} in levers["model_routing"]["top_reason_codes"]
    assert summary["runtime"]["trace_count"] == 2
    assert summary["runtime"]["enforced_count"] == 1
    assert summary["runtime"]["stages"] == {"cache_lookup": 2}
    assert {
        "stage": "cache_lookup",
        "lever": "exact_cache",
        "action": "hit",
        "reason_code": "exact_cache_hit",
        "enforced": False,
        "count": 1,
    } in summary["runtime"]["top_actions"]
    proof = summary["savings_proof"]
    assert proof["proof_count"] == 3
    assert proof["missing_proof_count"] == 1
    assert proof["methods"] == [
        {"key": "cache_avoidance", "count": 1},
        {"key": "holdback_observation", "count": 1},
        {"key": "none", "count": 1},
    ]
    assert proof["confidences"] == [
        {"key": "measured_priced", "count": 1},
        {"key": "not_applicable", "count": 1},
        {"key": "requires_aggregate_holdback", "count": 1},
    ]
    assert proof["quality_statuses"] == {"not_measured": 1, "passed": 2}
    assert proof["pricing_statuses"] == {"priced": 3}
    assert proof["cost_sources"] == {"catalog": 3}
    assert {"key": "optimization_overhead_not_measured", "count": 3} in proof["top_reason_codes"]
    assert {"key": "aggregate_holdback_required", "count": 1} in proof["top_reason_codes"]
    assert proof["totals"] == {
        "baseline_cost_usd": "0.32",
        "actual_cost_usd": "0.18",
        "gross_savings_usd": "0.15",
        "optimization_overhead_cost_usd": None,
        "net_savings_usd": None,
        "baseline_row_count": 2,
        "actual_row_count": 3,
        "gross_savings_row_count": 1,
        "overhead_row_count": 0,
        "net_savings_row_count": 0,
    }


def test_summarize_feedback_outcomes_counts_linkage_scores_and_contexts():
    summary = summarize_feedback_outcomes(
        [
            {
                "outcome": "accepted",
                "source": "customer",
                "quality_score": Decimal("0.9"),
                "failure_mode": None,
                "decision_event_id": "decision_1",
                "usage_event_id": "usage_1",
                "request_id": "req_1",
                "decision_type": "cache",
                "lever": "exact_cache",
                "task_type": "classification.intent",
                "model_chosen": "gpt-4o-mini",
                "optimization_applied": True,
            },
            {
                "outcome": "edited",
                "source": "customer",
                "quality_score": Decimal("0.5"),
                "failure_mode": "missing_detail",
                "decision_event_id": "decision_2",
                "usage_event_id": "usage_2",
                "request_id": "req_2",
                "decision_type": "experiment_treatment",
                "lever": "model_downshift",
                "task_type": "support.reply",
                "model_chosen": "gpt-3.5-turbo",
                "optimization_applied": True,
            },
            {
                "outcome": "rejected",
                "source": "customer",
                "quality_score": None,
                "failure_mode": "wrong_answer",
                "decision_event_id": None,
                "usage_event_id": "usage_3",
                "request_id": None,
                "decision_type": None,
                "lever": None,
                "task_type": None,
                "model_chosen": None,
                "optimization_applied": None,
            },
        ],
        total_decisions=4,
    )

    assert summary["feedback_count"] == 3
    assert summary["decision_linked_count"] == 2
    assert summary["decision_unlinked_count"] == 1
    assert summary["usage_linked_count"] == 3
    assert summary["request_id_linked_count"] == 2
    assert summary["feedback_per_decision_rate"] == "0.7500"
    assert summary["accepted_count"] == 1
    assert summary["corrective_count"] == 2
    assert summary["acceptance_rate"] == "0.3333"
    assert summary["outcomes"] == [
        {"key": "accepted", "count": 1},
        {"key": "edited", "count": 1},
        {"key": "rejected", "count": 1},
    ]
    assert summary["sources"] == {"customer": 3}
    assert summary["top_failure_modes"] == [
        {"key": "missing_detail", "count": 1},
        {"key": "wrong_answer", "count": 1},
    ]
    assert summary["quality_scores"] == {
        "score_count": 2,
        "average_score": "0.7000",
        "min_score": "0.5000",
        "max_score": "0.9000",
    }
    assert {
        "dimension": "lever",
        "key": "exact_cache",
        "feedback_count": 1,
        "accepted_count": 1,
        "corrective_count": 0,
        "acceptance_rate": "1.0000",
    } in summary["top_contexts"]
    assert {
        "dimension": "optimization_applied",
        "key": "true",
        "feedback_count": 2,
        "accepted_count": 1,
        "corrective_count": 1,
        "acceptance_rate": "0.5000",
    } in summary["top_contexts"]
    assert summary["learning_readiness"] == {
        "ready": True,
        "reason_codes": ["some_feedback_unlinked_from_decisions"],
    }


def test_planner_summary_endpoint_is_project_scoped_and_windowed(client, provision, db_session):
    current = provision(sub="auth0|planner-summary", email="planner-summary@example.com")
    other = provision(sub="auth0|planner-other", email="planner-other@example.com", project_name="other")
    project = db_session.get(Project, uuid.UUID(current["project_id"]))
    other_project = db_session.get(Project, uuid.UUID(other["project_id"]))
    now = datetime.now(UTC)
    planned = _decision(
        project,
        request_id="req_current_planned",
        metadata=_plan_metadata(route_policy_id=str(uuid.uuid4()), savings_proof=_savings_proof()),
        created_at=now - timedelta(days=1),
        decision_type="cache",
        lever="exact_cache",
        optimization_applied=True,
    )
    unplanned = _decision(
        project,
        request_id="req_current_unplanned",
        metadata={},
        created_at=now - timedelta(days=1),
        decision_type="experiment_treatment",
        lever="model_downshift",
        model_chosen="gpt-3.5-turbo",
        optimization_applied=True,
    )
    db_session.add_all(
        [
            planned,
            unplanned,
            _decision(
                project,
                request_id="req_old_planned",
                metadata=_plan_metadata(risk_level="high", reason_codes=["risk_high"]),
                created_at=now - timedelta(days=40),
            ),
            _decision(
                other_project,
                request_id="req_other_planned",
                metadata=_plan_metadata(risk_level="high", reason_codes=["risk_high"]),
                created_at=now - timedelta(days=1),
            ),
        ]
    )
    db_session.flush()
    db_session.add_all(
        [
            RequestFeedback(
                organization_id=project.organization_id,
                project_id=project.id,
                decision_event_id=planned.id,
                request_id=planned.request_id,
                outcome="accepted",
                quality_score=Decimal("0.9"),
                source="customer",
                created_at=now - timedelta(hours=12),
            ),
            RequestFeedback(
                organization_id=project.organization_id,
                project_id=project.id,
                decision_event_id=unplanned.id,
                request_id=unplanned.request_id,
                outcome="edited",
                quality_score=Decimal("0.4"),
                failure_mode="missing_detail",
                source="customer",
                created_at=now - timedelta(hours=6),
            ),
            RequestFeedback(
                organization_id=project.organization_id,
                project_id=project.id,
                decision_event_id=planned.id,
                request_id=planned.request_id,
                outcome="rejected",
                failure_mode="old_feedback",
                source="customer",
                created_at=now - timedelta(days=40),
            ),
            RequestFeedback(
                organization_id=other_project.organization_id,
                project_id=other_project.id,
                request_id="req_other",
                outcome="rejected",
                source="customer",
                created_at=now - timedelta(hours=3),
            ),
        ]
    )
    db_session.commit()

    body = client.get("/v1/engine/planner-summary?days=30", headers=_b(current["api_key"])).json()

    assert body["project_id"] == current["project_id"]
    assert body["window"]["days"] == 30
    assert body["total_decisions"] == 2
    assert body["planned_decisions"] == 1
    assert body["unplanned_decisions"] == 1
    assert body["classification"]["risk_levels"] == {"low": 1}
    assert body["runtime"]["trace_count"] == 0
    assert body["savings_proof"]["proof_count"] == 1
    assert body["savings_proof"]["missing_proof_count"] == 1
    assert body["savings_proof"]["methods"] == [{"key": "cache_avoidance", "count": 1}]
    assert body["savings_proof"]["totals"]["gross_savings_usd"] == "0.15"
    assert body["savings_proof"]["totals"]["net_savings_usd"] is None
    feedback = body["feedback"]
    assert feedback["feedback_count"] == 2
    assert feedback["decision_linked_count"] == 2
    assert feedback["decision_unlinked_count"] == 0
    assert feedback["feedback_per_decision_rate"] == "1.0000"
    assert feedback["accepted_count"] == 1
    assert feedback["corrective_count"] == 1
    assert feedback["acceptance_rate"] == "0.5000"
    assert feedback["outcomes"] == [{"key": "accepted", "count": 1}, {"key": "edited", "count": 1}]
    assert feedback["top_failure_modes"] == [{"key": "missing_detail", "count": 1}]
    assert feedback["quality_scores"] == {
        "score_count": 2,
        "average_score": "0.6500",
        "min_score": "0.4000",
        "max_score": "0.9000",
    }
    assert {
        "dimension": "lever",
        "key": "exact_cache",
        "feedback_count": 1,
        "accepted_count": 1,
        "corrective_count": 0,
        "acceptance_rate": "1.0000",
    } in feedback["top_contexts"]
    assert feedback["learning_readiness"] == {"ready": True, "reason_codes": []}
    learning = body["learning_candidates"]
    assert len(learning) == 2
    cache_candidate = next(candidate for candidate in learning if candidate["segment"]["lever"] == "exact_cache")
    assert cache_candidate["segment"]["task_type"] == "classification.intent"
    assert cache_candidate["sample_count"] == 1
    assert cache_candidate["measured_savings_count"] == 1
    assert cache_candidate["total_gross_savings_usd"] == "0.15"
    assert cache_candidate["feedback"]["accepted_count"] == 1
    assert cache_candidate["readiness"]["status"] == "insufficient_data"
    assert "sample_count_insufficient" in cache_candidate["readiness"]["reason_codes"]
    routed_candidate = next(candidate for candidate in learning if candidate["segment"]["lever"] == "model_downshift")
    assert routed_candidate["feedback"]["corrective_count"] == 1
    assert "missing_detail" in {failure["key"] for failure in routed_candidate["feedback"]["top_failure_modes"]}
    levers = {row["lever"]: row for row in body["levers"]}
    assert levers["exact_cache"]["statuses"] == {"eligible": 1}
    assert levers["model_routing"]["policy_candidate_count"] == 1


def test_planner_summary_rejects_invalid_window(client, provision):
    p = provision(sub="auth0|planner-window", email="planner-window@example.com")

    resp = client.get("/v1/engine/planner-summary?days=0", headers=_b(p["api_key"]))

    assert resp.status_code == 422
