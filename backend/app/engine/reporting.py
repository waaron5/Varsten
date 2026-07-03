from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
from typing import Any

_ACCEPTED_OUTCOMES = {"accepted"}
_CORRECTIVE_OUTCOMES = {"rejected", "edited", "regenerated", "escalated", "overridden"}
_CONTEXT_DIMENSIONS = ("decision_type", "lever", "task_type", "model_chosen", "optimization_applied")
_RATE_QUANT = Decimal("0.0001")


def summarize_planner_traces(
    event_metadatas: Iterable[dict[str, Any] | None],
    *,
    total_decisions: int,
) -> dict[str, Any]:
    """Aggregate content-free planner metadata into a read-side summary.

    The proxy stores planner traces inside RequestDecisionEvent.metadata. This
    helper intentionally ignores malformed rows instead of treating read-side
    reporting as a hot-path invariant.
    """
    accumulator = _PlannerTraceAccumulator()
    for metadata in event_metadatas:
        accumulator.add_metadata(metadata)
    return accumulator.as_dict(total_decisions=total_decisions)


class _PlannerTraceAccumulator:
    def __init__(self) -> None:
        self.planner_versions: Counter[str] = Counter()
        self.selected_actions: Counter[tuple[str, str, str]] = Counter()
        self.risk_levels: Counter[str] = Counter()
        self.task_types: Counter[str] = Counter()
        self.classification_reasons: Counter[str] = Counter()
        self.lever_totals: Counter[str] = Counter()
        self.lever_statuses: defaultdict[str, Counter[str]] = defaultdict(Counter)
        self.lever_quality_gates: defaultdict[str, Counter[str]] = defaultdict(Counter)
        self.lever_risks: defaultdict[str, Counter[str]] = defaultdict(Counter)
        self.lever_reasons: defaultdict[str, Counter[str]] = defaultdict(Counter)
        self.lever_policy_candidates: Counter[str] = Counter()
        self.runtime_stages: Counter[str] = Counter()
        self.runtime_actions: Counter[tuple[str, str, str, str, bool]] = Counter()
        self.parity_outcomes: Counter[str] = Counter()
        self.parity_mismatch_reasons: Counter[str] = Counter()
        self.proof_methods: Counter[str] = Counter()
        self.proof_confidences: Counter[str] = Counter()
        self.proof_quality_statuses: Counter[str] = Counter()
        self.proof_pricing_statuses: Counter[str] = Counter()
        self.proof_cost_sources: Counter[str] = Counter()
        self.proof_reason_codes: Counter[str] = Counter()
        self.proof_totals = _ProofTotals()
        self.planned_decisions = 0
        self.proof_count = 0
        self.runtime_trace_count = 0
        self.runtime_enforced_count = 0
        self.unknown_task_count = 0
        self.personalized_count = 0
        self.freshness_sensitive_count = 0
        self.tools_present_count = 0
        self.json_output_count = 0
        self.multimodal_count = 0

    def add_metadata(self, metadata: dict[str, Any] | None) -> None:
        proof = _proof_from_metadata(metadata)
        if proof is not None:
            self._add_proof(proof)

        plan = _plan_from_metadata(metadata)
        if plan is None:
            return

        self.planned_decisions += 1
        self.planner_versions.update([str(plan.get("planner_version") or "unknown")])
        self._add_selected(plan.get("selected"))
        self._add_classification(plan.get("classification"))
        self._add_candidates(plan.get("candidates"))
        runtime_trace = metadata.get("runtime_trace") if isinstance(metadata, dict) else None
        self._add_runtime_trace(runtime_trace)

    def _add_proof(self, proof: dict[str, Any]) -> None:
        self.proof_count += 1
        self.proof_methods.update([str(proof.get("method") or "unknown")])
        self.proof_confidences.update([str(proof.get("confidence") or "unknown")])
        self.proof_quality_statuses.update([str(proof.get("quality_status") or "unknown")])
        self.proof_pricing_statuses.update([str(proof.get("pricing_status") or "unknown")])
        self.proof_cost_sources.update([str(proof.get("cost_source") or "unknown")])
        _update_strings(self.proof_reason_codes, proof.get("reason_codes"))
        self.proof_totals.add(proof)

    def _add_selected(self, selected: Any) -> None:
        if not isinstance(selected, dict):
            return
        self.selected_actions.update(
            [
                (
                    str(selected.get("action") or "unknown"),
                    str(selected.get("mode") or "unknown"),
                    str(selected.get("reason_code") or "unknown"),
                )
            ]
        )

    def _add_classification(self, classification: Any) -> None:
        if not isinstance(classification, dict):
            return
        self.risk_levels.update([str(classification.get("risk_level") or "unknown")])
        task_type = classification.get("task_type")
        if task_type:
            self.task_types.update([str(task_type)])
        if classification.get("unknown_task") is True:
            self.unknown_task_count += 1
        if classification.get("personalized") is True:
            self.personalized_count += 1
        if classification.get("freshness_sensitive") is True:
            self.freshness_sensitive_count += 1
        if classification.get("has_tools") is True:
            self.tools_present_count += 1
        if classification.get("wants_json") is True:
            self.json_output_count += 1
        if classification.get("has_multimodal") is True:
            self.multimodal_count += 1
        _update_strings(self.classification_reasons, classification.get("reason_codes"))

    def _add_candidates(self, candidates: Any) -> None:
        if not isinstance(candidates, list):
            return
        for candidate in candidates:
            self._add_candidate(candidate)

    def _add_candidate(self, candidate: Any) -> None:
        if not isinstance(candidate, dict):
            return
        lever = str(candidate.get("lever") or "unknown")
        self.lever_totals.update([lever])
        self.lever_statuses[lever].update([str(candidate.get("status") or "unknown")])
        self.lever_quality_gates[lever].update([str(candidate.get("quality_gate") or "unknown")])
        self.lever_risks[lever].update([str(candidate.get("risk") or "unknown")])
        self.lever_reasons[lever].update([str(candidate.get("reason_code") or "unknown")])
        if candidate.get("policy_id"):
            self.lever_policy_candidates.update([lever])

    def _add_runtime_trace(self, runtime_trace: Any) -> None:
        if not isinstance(runtime_trace, list):
            return
        for event in runtime_trace:
            self._add_runtime_event(event)

    def _add_runtime_event(self, event: Any) -> None:
        if not isinstance(event, dict):
            return
        self.runtime_trace_count += 1
        stage = str(event.get("stage") or "unknown")
        lever = str(event.get("lever") or "unknown")
        action = str(event.get("action") or "unknown")
        reason_code = str(event.get("reason_code") or "unknown")
        enforced = event.get("enforced") is True
        if enforced:
            self.runtime_enforced_count += 1
        self.runtime_stages.update([stage])
        self.runtime_actions.update([(stage, lever, action, reason_code, enforced)])
        if stage == "planner_parity":
            # action is "match" / "mismatch"; reason_code explains a mismatch.
            self.parity_outcomes.update([action])
            if action == "mismatch":
                self.parity_mismatch_reasons.update([reason_code])

    def as_dict(self, *, total_decisions: int) -> dict[str, Any]:
        return {
            "total_decisions": total_decisions,
            "planned_decisions": self.planned_decisions,
            "unplanned_decisions": max(total_decisions - self.planned_decisions, 0),
            "planner_versions": _top_counts(self.planner_versions, limit=None),
            "selected_actions": self._selected_action_summary(),
            "classification": {
                "risk_levels": dict(sorted(self.risk_levels.items())),
                "unknown_task_count": self.unknown_task_count,
                "personalized_count": self.personalized_count,
                "freshness_sensitive_count": self.freshness_sensitive_count,
                "tools_present_count": self.tools_present_count,
                "json_output_count": self.json_output_count,
                "multimodal_count": self.multimodal_count,
                "top_task_types": _top_counts(self.task_types),
                "top_reason_codes": _top_counts(self.classification_reasons),
            },
            "levers": self._lever_summary(),
            "runtime": self._runtime_summary(),
            "savings_proof": {
                "proof_count": self.proof_count,
                "missing_proof_count": max(total_decisions - self.proof_count, 0),
                "methods": _top_counts(self.proof_methods, limit=None),
                "confidences": _top_counts(self.proof_confidences, limit=None),
                "quality_statuses": dict(sorted(self.proof_quality_statuses.items())),
                "pricing_statuses": dict(sorted(self.proof_pricing_statuses.items())),
                "cost_sources": dict(sorted(self.proof_cost_sources.items())),
                "top_reason_codes": _top_counts(self.proof_reason_codes),
                "totals": self.proof_totals.as_dict(),
            },
        }

    def _selected_action_summary(self) -> list[dict[str, Any]]:
        return [
            {
                "action": action,
                "mode": mode,
                "reason_code": reason_code,
                "count": count,
            }
            for (action, mode, reason_code), count in sorted(
                self.selected_actions.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ]

    def _lever_summary(self) -> list[dict[str, Any]]:
        return [
            {
                "lever": lever,
                "candidate_count": self.lever_totals[lever],
                "statuses": dict(sorted(self.lever_statuses[lever].items())),
                "quality_gates": dict(sorted(self.lever_quality_gates[lever].items())),
                "risks": dict(sorted(self.lever_risks[lever].items())),
                "top_reason_codes": _top_counts(self.lever_reasons[lever]),
                "policy_candidate_count": self.lever_policy_candidates[lever],
            }
            for lever in sorted(self.lever_totals)
        ]

    def _runtime_summary(self) -> dict[str, Any]:
        parity_total = sum(self.parity_outcomes.values())
        return {
            "trace_count": self.runtime_trace_count,
            "enforced_count": self.runtime_enforced_count,
            "stages": dict(sorted(self.runtime_stages.items())),
            "parity": {
                "checked_count": parity_total,
                "match_count": self.parity_outcomes.get("match", 0),
                "mismatch_count": self.parity_outcomes.get("mismatch", 0),
                "match_rate": (
                    str(
                        (Decimal(self.parity_outcomes.get("match", 0)) / Decimal(parity_total)).quantize(
                            Decimal("0.0001")
                        )
                    )
                    if parity_total
                    else None
                ),
                "top_mismatch_reasons": _top_counts(self.parity_mismatch_reasons),
            },
            "top_actions": [
                {
                    "stage": stage,
                    "lever": lever,
                    "action": action,
                    "reason_code": reason_code,
                    "enforced": enforced,
                    "count": count,
                }
                for (stage, lever, action, reason_code, enforced), count in sorted(
                    self.runtime_actions.items(),
                    key=lambda item: (-item[1], item[0]),
                )[:10]
            ],
        }


def summarize_feedback_outcomes(
    feedback_rows: Iterable[dict[str, Any]],
    *,
    total_decisions: int,
) -> dict[str, Any]:
    """Aggregate content-free customer outcome feedback.

    Feedback only becomes useful learning input when it is tied back to a
    decision row. This summary keeps that distinction explicit.
    """
    outcomes: Counter[str] = Counter()
    sources: Counter[str] = Counter()
    failure_modes: Counter[str] = Counter()
    context_stats: dict[tuple[str, str], _OutcomeStats] = defaultdict(_OutcomeStats)
    feedback_count = 0
    decision_linked_count = 0
    usage_linked_count = 0
    request_id_linked_count = 0
    accepted_count = 0
    corrective_count = 0
    score_total = Decimal("0")
    score_count = 0
    score_min: Decimal | None = None
    score_max: Decimal | None = None

    for row in feedback_rows:
        feedback_count += 1
        outcome = str(_row_value(row, "outcome") or "unknown")
        outcomes.update([outcome])
        sources.update([str(_row_value(row, "source") or "unknown")])
        failure_mode = _row_value(row, "failure_mode")
        if failure_mode:
            failure_modes.update([str(failure_mode)])

        if outcome in _ACCEPTED_OUTCOMES:
            accepted_count += 1
        elif outcome in _CORRECTIVE_OUTCOMES:
            corrective_count += 1

        if _row_value(row, "decision_event_id") is not None:
            decision_linked_count += 1
        if _row_value(row, "usage_event_id") is not None:
            usage_linked_count += 1
        if _row_value(row, "request_id") is not None:
            request_id_linked_count += 1

        score = _to_decimal(_row_value(row, "quality_score"))
        if score is not None:
            score_total += score
            score_count += 1
            score_min = score if score_min is None else min(score_min, score)
            score_max = score if score_max is None else max(score_max, score)

        for dimension in _CONTEXT_DIMENSIONS:
            context_key = _context_value(_row_value(row, dimension))
            if context_key is None:
                continue
            context_stats[(dimension, context_key)].add(outcome)

    readiness_reasons = _learning_readiness_reasons(
        feedback_count=feedback_count,
        decision_linked_count=decision_linked_count,
        decision_unlinked_count=max(feedback_count - decision_linked_count, 0),
        corrective_count=corrective_count,
        score_count=score_count,
    )
    outcome_denominator = accepted_count + corrective_count
    return {
        "feedback_count": feedback_count,
        "decision_linked_count": decision_linked_count,
        "decision_unlinked_count": max(feedback_count - decision_linked_count, 0),
        "usage_linked_count": usage_linked_count,
        "request_id_linked_count": request_id_linked_count,
        "feedback_per_decision_rate": _rate(feedback_count, total_decisions),
        "accepted_count": accepted_count,
        "corrective_count": corrective_count,
        "acceptance_rate": _rate(accepted_count, outcome_denominator),
        "outcomes": _top_counts(outcomes, limit=None),
        "sources": dict(sorted(sources.items())),
        "top_failure_modes": _top_counts(failure_modes),
        "quality_scores": {
            "score_count": score_count,
            "average_score": _score_string(score_total / score_count) if score_count else None,
            "min_score": _score_string(score_min),
            "max_score": _score_string(score_max),
        },
        "top_contexts": [
            stats.as_dict(dimension=dimension, key=key)
            for (dimension, key), stats in sorted(
                context_stats.items(),
                key=lambda item: (-item[1].feedback_count, item[0]),
            )[:12]
        ],
        "learning_readiness": {
            "ready": decision_linked_count > 0,
            "reason_codes": readiness_reasons,
        },
    }


def _plan_from_metadata(metadata: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(metadata, dict):
        return None
    plan = metadata.get("optimization_plan")
    return plan if isinstance(plan, dict) else None


def _proof_from_metadata(metadata: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(metadata, dict):
        return None
    proof = metadata.get("savings_proof")
    return proof if isinstance(proof, dict) else None


def _update_strings(counter: Counter[str], values: Any) -> None:
    if not isinstance(values, list):
        return
    for value in values:
        if value:
            counter.update([str(value)])


def _top_counts(counter: Counter[str], limit: int | None = 10) -> list[dict[str, Any]]:
    items = sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    if limit is not None:
        items = items[:limit]
    return [{"key": key, "count": count} for key, count in items]


def _row_value(row: dict[str, Any], key: str) -> Any:
    if isinstance(row, dict):
        return row.get(key)
    return getattr(row, key, None)


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _context_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return str(value).lower()
    text = str(value)
    return text if text else None


def _rate(numerator: int, denominator: int) -> str | None:
    if denominator <= 0:
        return None
    return _decimal_string((Decimal(numerator) / Decimal(denominator)).quantize(_RATE_QUANT))


def _decimal_string(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _score_string(value: Decimal | None) -> str | None:
    return str(value.quantize(_RATE_QUANT)) if value is not None else None


def _learning_readiness_reasons(
    *,
    feedback_count: int,
    decision_linked_count: int,
    decision_unlinked_count: int,
    corrective_count: int,
    score_count: int,
) -> list[str]:
    reasons: list[str] = []
    if feedback_count == 0:
        reasons.append("no_feedback")
    if decision_linked_count == 0:
        reasons.append("no_decision_linked_feedback")
    if decision_unlinked_count > 0:
        reasons.append("some_feedback_unlinked_from_decisions")
    if corrective_count == 0:
        reasons.append("no_corrective_feedback")
    if score_count == 0:
        reasons.append("no_quality_scores")
    return reasons


class _OutcomeStats:
    def __init__(self) -> None:
        self.feedback_count = 0
        self.accepted_count = 0
        self.corrective_count = 0

    def add(self, outcome: str) -> None:
        self.feedback_count += 1
        if outcome in _ACCEPTED_OUTCOMES:
            self.accepted_count += 1
        elif outcome in _CORRECTIVE_OUTCOMES:
            self.corrective_count += 1

    def as_dict(self, *, dimension: str, key: str) -> dict[str, Any]:
        denominator = self.accepted_count + self.corrective_count
        return {
            "dimension": dimension,
            "key": key,
            "feedback_count": self.feedback_count,
            "accepted_count": self.accepted_count,
            "corrective_count": self.corrective_count,
            "acceptance_rate": _rate(self.accepted_count, denominator),
        }


class _ProofTotals:
    def __init__(self) -> None:
        self.baseline_cost_usd = Decimal("0")
        self.actual_cost_usd = Decimal("0")
        self.gross_savings_usd = Decimal("0")
        self.optimization_overhead_cost_usd = Decimal("0")
        self.net_savings_usd = Decimal("0")
        self.baseline_row_count = 0
        self.actual_row_count = 0
        self.gross_savings_row_count = 0
        self.overhead_row_count = 0
        self.net_savings_row_count = 0

    def add(self, proof: dict[str, Any]) -> None:
        self._add_money("baseline_cost_usd", proof.get("baseline_cost_usd"))
        self._add_money("actual_cost_usd", proof.get("actual_cost_usd"))
        self._add_money("gross_savings_usd", proof.get("gross_savings_usd"))
        self._add_money("optimization_overhead_cost_usd", proof.get("optimization_overhead_cost_usd"))
        self._add_money("net_savings_usd", proof.get("net_savings_usd"))

    def _add_money(self, field: str, value: Any) -> None:
        amount = _to_decimal(value)
        if amount is None:
            return
        setattr(self, field, getattr(self, field) + amount)
        count_field = _COUNT_FIELDS[field]
        setattr(self, count_field, getattr(self, count_field) + 1)

    def as_dict(self) -> dict[str, Any]:
        return {
            "baseline_cost_usd": _money_total(self.baseline_cost_usd, self.baseline_row_count),
            "actual_cost_usd": _money_total(self.actual_cost_usd, self.actual_row_count),
            "gross_savings_usd": _money_total(self.gross_savings_usd, self.gross_savings_row_count),
            "optimization_overhead_cost_usd": _money_total(
                self.optimization_overhead_cost_usd,
                self.overhead_row_count,
            ),
            "net_savings_usd": _money_total(self.net_savings_usd, self.net_savings_row_count),
            "baseline_row_count": self.baseline_row_count,
            "actual_row_count": self.actual_row_count,
            "gross_savings_row_count": self.gross_savings_row_count,
            "overhead_row_count": self.overhead_row_count,
            "net_savings_row_count": self.net_savings_row_count,
        }


_COUNT_FIELDS = {
    "baseline_cost_usd": "baseline_row_count",
    "actual_cost_usd": "actual_row_count",
    "gross_savings_usd": "gross_savings_row_count",
    "optimization_overhead_cost_usd": "overhead_row_count",
    "net_savings_usd": "net_savings_row_count",
}


def _money_total(value: Decimal, row_count: int) -> str | None:
    return str(value) if row_count else None
