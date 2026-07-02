from decimal import Decimal

from app.engine.outcomes import score_optimization_outcomes


def _decision(
    idx: int,
    *,
    lever: str = "model_downshift",
    task_type: str = "classification.intent",
    risk_level: str = "low",
    model_requested: str = "gpt-4o",
    model_chosen: str = "gpt-4o-mini",
    savings: str | None = "0.01",
    quality_ok: bool | None = True,
    confidence: str = "measured_priced",
) -> dict:
    return {
        "id": f"decision_{idx}",
        "provider_requested": "openai",
        "model_requested": model_requested,
        "provider_chosen": "openai",
        "model_chosen": model_chosen,
        "decision_type": "experiment_treatment",
        "lever": lever,
        "cache_status": "miss",
        "optimization_applied": True,
        "task_type": task_type,
        "risk_level": risk_level,
        "realized_savings_usd": Decimal(savings) if savings is not None else None,
        "pricing_status": "priced",
        "quality_ok": quality_ok,
        "event_metadata": {"savings_proof": {"confidence": confidence}},
    }


def _feedback(idx: int, *, outcome: str = "accepted", failure_mode: str | None = None) -> dict:
    return {
        "decision_event_id": f"decision_{idx}",
        "outcome": outcome,
        "failure_mode": failure_mode,
    }


def test_outcome_scorer_marks_small_samples_insufficient():
    candidates = score_optimization_outcomes(
        [_decision(1), _decision(2)],
        [_feedback(1), _feedback(2)],
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["readiness"]["status"] == "insufficient_data"
    assert "sample_count_insufficient" in candidate["readiness"]["reason_codes"]
    assert candidate["sample_count"] == 2
    assert candidate["total_gross_savings_usd"] == "0.02"


def test_outcome_scorer_marks_unmeasured_savings_unproven():
    candidates = score_optimization_outcomes(
        [_decision(idx, savings=None) for idx in range(1, 6)],
        [_feedback(idx) for idx in range(1, 6)],
    )

    candidate = candidates[0]
    assert candidate["readiness"]["status"] == "savings_unproven"
    assert "no_measured_savings" in candidate["readiness"]["reason_codes"]
    assert candidate["measured_savings_count"] == 0
    assert candidate["total_gross_savings_usd"] is None


def test_outcome_scorer_marks_quality_failures_risky():
    decisions = [_decision(idx) for idx in range(1, 6)]
    decisions[2]["quality_ok"] = False
    feedback = [_feedback(idx) for idx in range(1, 6)]
    feedback[3] = _feedback(4, outcome="edited", failure_mode="missing_detail")

    candidate = score_optimization_outcomes(decisions, feedback)[0]

    assert candidate["readiness"]["status"] == "quality_risk"
    assert "quality_pass_rate_low" in candidate["readiness"]["reason_codes"]
    assert "corrective_feedback_present" in candidate["readiness"]["reason_codes"]
    assert candidate["quality"] == {
        "measured_count": 5,
        "passed_count": 4,
        "failed_count": 1,
        "pass_rate": "0.8000",
    }
    assert candidate["feedback"]["corrective_count"] == 1
    assert candidate["feedback"]["top_failure_modes"] == [{"key": "missing_detail", "count": 1}]


def test_outcome_scorer_marks_evidence_backed_path_recommendable():
    candidate = score_optimization_outcomes(
        [_decision(idx) for idx in range(1, 6)],
        [_feedback(idx) for idx in range(1, 6)],
    )[0]

    assert candidate["readiness"]["status"] == "recommendable"
    assert candidate["readiness"]["reason_codes"] == ["sample_count_below_auto_threshold"]
    assert candidate["sample_count"] == 5
    assert candidate["measured_savings_count"] == 5
    assert candidate["savings_measurement_rate"] == "1.0000"
    assert candidate["average_gross_savings_usd"] == "0.01"
    assert candidate["feedback"]["acceptance_rate"] == "1.0000"


def test_outcome_scorer_marks_strong_segment_auto_apply_candidate_read_only():
    candidate = score_optimization_outcomes(
        [_decision(idx) for idx in range(1, 21)],
        [_feedback(idx) for idx in range(1, 11)],
    )[0]

    assert candidate["readiness"] == {"status": "auto_apply_candidate", "reason_codes": []}
    assert candidate["sample_count"] == 20
    assert candidate["measured_savings_count"] == 20
    assert candidate["feedback"]["coverage_rate"] == "0.5000"
    assert candidate["total_gross_savings_usd"] == "0.20"


def test_outcome_scorer_ignores_passthrough_and_unlinked_feedback():
    candidates = score_optimization_outcomes(
        [
            {**_decision(1), "optimization_applied": False},
            _decision(2, lever="exact_cache", model_requested="gpt-4o-mini", model_chosen="gpt-4o-mini"),
        ],
        [_feedback(1, outcome="edited"), _feedback(99, outcome="rejected"), _feedback(2)],
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["segment"]["lever"] == "exact_cache"
    assert candidate["feedback"]["feedback_count"] == 1
    assert candidate["feedback"]["corrective_count"] == 0
