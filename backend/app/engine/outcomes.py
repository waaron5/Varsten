from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from app.engine.types import OutcomePrior

_ACCEPTED_OUTCOMES = {"accepted"}
_CORRECTIVE_OUTCOMES = {"rejected", "edited", "regenerated", "escalated", "overridden"}
_RATE_QUANT = Decimal("0.0001")
_MIN_RECOMMEND_SAMPLES = 5
_MIN_AUTO_SAMPLES = 20
_MIN_RECOMMEND_SAVINGS_COVERAGE = Decimal("0.8")
_MIN_AUTO_SAVINGS_COVERAGE = Decimal("0.95")
_MIN_RECOMMEND_FEEDBACK_COVERAGE = Decimal("0.2")
_MIN_AUTO_FEEDBACK_COVERAGE = Decimal("0.5")
_MIN_RECOMMEND_ACCEPTANCE_RATE = Decimal("0.95")
_MIN_AUTO_ACCEPTANCE_RATE = Decimal("0.99")
_MIN_RECOMMEND_QUALITY_PASS_RATE = Decimal("0.98")
_MIN_AUTO_QUALITY_PASS_RATE = Decimal("0.995")


def score_optimization_outcomes(
    decision_rows: list[dict[str, Any]],
    feedback_rows: list[dict[str, Any]],
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Score observed optimization paths using measured cost and outcome signals.

    This is intentionally read-only. It turns persisted decision evidence into
    conservative candidate priors; it does not authorize any runtime behavior.
    """
    segments: dict[_SegmentKey, _SegmentStats] = defaultdict(_SegmentStats)
    decision_segments: dict[str, _SegmentKey] = {}

    for row in decision_rows:
        if _row_value(row, "optimization_applied") is not True:
            continue
        key = _segment_key(row)
        decision_id = _decision_id(row)
        if key is None or decision_id is None:
            continue
        segments[key].add_decision(row, decision_id)
        decision_segments[decision_id] = key

    for row in feedback_rows:
        decision_id = _decision_id(row)
        if decision_id is None:
            continue
        key = decision_segments.get(decision_id)
        if key is None:
            continue
        segments[key].add_feedback(row, decision_id)

    candidates = [stats.as_dict(key) for key, stats in segments.items()]
    candidates.sort(
        key=lambda item: (
            _readiness_rank(item["readiness"]["status"]),
            -item["sample_count"],
            -(
                Decimal(item["total_gross_savings_usd"])
                if item["total_gross_savings_usd"] is not None
                else Decimal("0")
            ),
            item["segment"]["task_type"],
            item["segment"]["lever"],
        )
    )
    return candidates[:limit]


def outcome_prior_from_learning_candidate(candidate: dict[str, Any]) -> OutcomePrior:
    """Convert a scored learning candidate into a planner advisory prior."""
    raw_segment = candidate.get("segment")
    raw_readiness = candidate.get("readiness")
    raw_quality = candidate.get("quality")
    raw_feedback = candidate.get("feedback")
    segment: dict[str, Any] = raw_segment if isinstance(raw_segment, dict) else {}
    readiness: dict[str, Any] = raw_readiness if isinstance(raw_readiness, dict) else {}
    quality: dict[str, Any] = raw_quality if isinstance(raw_quality, dict) else {}
    feedback: dict[str, Any] = raw_feedback if isinstance(raw_feedback, dict) else {}
    return OutcomePrior(
        lever=str(segment.get("lever") or "unknown"),
        readiness_status=str(readiness.get("status") or "insufficient_data"),
        sample_count=_int(candidate.get("sample_count")),
        measured_savings_count=_int(candidate.get("measured_savings_count")),
        total_gross_savings_usd=_optional_str(candidate.get("total_gross_savings_usd")),
        average_gross_savings_usd=_optional_str(candidate.get("average_gross_savings_usd")),
        quality_pass_rate=_optional_str(quality.get("pass_rate")),
        feedback_acceptance_rate=_optional_str(feedback.get("acceptance_rate")),
        reason_codes=tuple(str(reason) for reason in readiness.get("reason_codes") or ()),
    )


@dataclass(frozen=True)
class _SegmentKey:
    task_type: str
    risk_level: str
    provider_requested: str
    model_requested: str
    provider_chosen: str
    model_chosen: str
    lever: str

    def as_dict(self) -> dict[str, str]:
        return {
            "task_type": self.task_type,
            "risk_level": self.risk_level,
            "provider_requested": self.provider_requested,
            "model_requested": self.model_requested,
            "provider_chosen": self.provider_chosen,
            "model_chosen": self.model_chosen,
            "lever": self.lever,
        }


class _SegmentStats:
    def __init__(self) -> None:
        self.sample_count = 0
        self.measured_savings_count = 0
        self.total_gross_savings = Decimal("0")
        self.pricing_statuses: Counter[str] = Counter()
        self.proof_confidences: Counter[str] = Counter()
        self.quality_measured_count = 0
        self.quality_passed_count = 0
        self.feedback_count = 0
        self.feedback_decision_ids: set[str] = set()
        self.accepted_count = 0
        self.corrective_count = 0
        self.failure_modes: Counter[str] = Counter()

    def add_decision(self, row: dict[str, Any], decision_id: str) -> None:
        del decision_id
        self.sample_count += 1
        savings = _decision_savings(row)
        if savings is not None:
            self.measured_savings_count += 1
            self.total_gross_savings += savings
        self.pricing_statuses.update([str(_row_value(row, "pricing_status") or "unknown")])
        proof = _proof_from_row(row)
        if proof is not None:
            self.proof_confidences.update([str(proof.get("confidence") or "unknown")])

        quality_ok = _row_value(row, "quality_ok")
        if quality_ok is not None:
            self.quality_measured_count += 1
            if quality_ok is True:
                self.quality_passed_count += 1

    def add_feedback(self, row: dict[str, Any], decision_id: str) -> None:
        self.feedback_count += 1
        self.feedback_decision_ids.add(decision_id)
        outcome = str(_row_value(row, "outcome") or "unknown")
        if outcome in _ACCEPTED_OUTCOMES:
            self.accepted_count += 1
        elif outcome in _CORRECTIVE_OUTCOMES:
            self.corrective_count += 1
        failure_mode = _row_value(row, "failure_mode")
        if failure_mode:
            self.failure_modes.update([str(failure_mode)])

    def as_dict(self, key: _SegmentKey) -> dict[str, Any]:
        savings_rate = _rate(self.measured_savings_count, self.sample_count)
        quality_pass_rate = _rate(self.quality_passed_count, self.quality_measured_count)
        feedback_coverage_rate = _rate(len(self.feedback_decision_ids), self.sample_count)
        acceptance_rate = _rate(self.accepted_count, self.accepted_count + self.corrective_count)
        readiness = self._readiness(
            savings_rate=_rate_decimal(self.measured_savings_count, self.sample_count),
            quality_pass_rate=_rate_decimal(self.quality_passed_count, self.quality_measured_count),
            feedback_coverage_rate=_rate_decimal(len(self.feedback_decision_ids), self.sample_count),
            acceptance_rate=_rate_decimal(self.accepted_count, self.accepted_count + self.corrective_count),
        )
        return {
            "segment": key.as_dict(),
            "sample_count": self.sample_count,
            "measured_savings_count": self.measured_savings_count,
            "savings_measurement_rate": savings_rate,
            "total_gross_savings_usd": _money(self.total_gross_savings, self.measured_savings_count),
            "average_gross_savings_usd": _average_money(self.total_gross_savings, self.measured_savings_count),
            "pricing_statuses": dict(sorted(self.pricing_statuses.items())),
            "proof_confidences": _top_counts(self.proof_confidences, limit=None),
            "quality": {
                "measured_count": self.quality_measured_count,
                "passed_count": self.quality_passed_count,
                "failed_count": max(self.quality_measured_count - self.quality_passed_count, 0),
                "pass_rate": quality_pass_rate,
            },
            "feedback": {
                "feedback_count": self.feedback_count,
                "decision_linked_count": len(self.feedback_decision_ids),
                "coverage_rate": feedback_coverage_rate,
                "accepted_count": self.accepted_count,
                "corrective_count": self.corrective_count,
                "acceptance_rate": acceptance_rate,
                "top_failure_modes": _top_counts(self.failure_modes),
            },
            "readiness": readiness,
        }

    def _readiness(
        self,
        *,
        savings_rate: Decimal | None,
        quality_pass_rate: Decimal | None,
        feedback_coverage_rate: Decimal | None,
        acceptance_rate: Decimal | None,
    ) -> dict[str, Any]:
        reason_codes = self._base_readiness_reasons()
        savings_proven = self._savings_proven(savings_rate)
        if not savings_proven:
            reason_codes.append(self._savings_gap_reason())

        quality_reasons = self._quality_risk_reasons(
            quality_pass_rate=quality_pass_rate,
            acceptance_rate=acceptance_rate,
        )
        reason_codes.extend(quality_reasons)

        if self.sample_count < _MIN_RECOMMEND_SAMPLES or self.feedback_count == 0:
            return {"status": "insufficient_data", "reason_codes": reason_codes}
        if not savings_proven:
            return {"status": "savings_unproven", "reason_codes": reason_codes}
        if quality_reasons:
            return {"status": "quality_risk", "reason_codes": reason_codes}

        if self._auto_ready(
            savings_rate=savings_rate,
            feedback_coverage_rate=feedback_coverage_rate,
            quality_pass_rate=quality_pass_rate,
            acceptance_rate=acceptance_rate,
        ):
            return {"status": "auto_apply_candidate", "reason_codes": []}

        if feedback_coverage_rate is not None and feedback_coverage_rate < _MIN_RECOMMEND_FEEDBACK_COVERAGE:
            reason_codes.append("feedback_coverage_low_for_auto")
        if self.sample_count < _MIN_AUTO_SAMPLES:
            reason_codes.append("sample_count_below_auto_threshold")
        return {"status": "recommendable", "reason_codes": reason_codes}

    def _base_readiness_reasons(self) -> list[str]:
        reasons: list[str] = []
        if self.sample_count < _MIN_RECOMMEND_SAMPLES:
            reasons.append("sample_count_insufficient")
        if self.feedback_count == 0:
            reasons.append("no_decision_linked_feedback")
        return reasons

    def _savings_proven(self, savings_rate: Decimal | None) -> bool:
        return (
            self.measured_savings_count > 0
            and self.total_gross_savings > 0
            and savings_rate is not None
            and savings_rate >= _MIN_RECOMMEND_SAVINGS_COVERAGE
        )

    def _savings_gap_reason(self) -> str:
        if self.measured_savings_count == 0:
            return "no_measured_savings"
        if self.total_gross_savings <= 0:
            return "gross_savings_not_positive"
        return "savings_measurement_coverage_low"

    def _quality_risk_reasons(
        self,
        *,
        quality_pass_rate: Decimal | None,
        acceptance_rate: Decimal | None,
    ) -> list[str]:
        reasons: list[str] = []
        if quality_pass_rate is not None and quality_pass_rate < _MIN_RECOMMEND_QUALITY_PASS_RATE:
            reasons.append("quality_pass_rate_low")
        if self.corrective_count > 0:
            reasons.append("corrective_feedback_present")
        if acceptance_rate is not None and acceptance_rate < _MIN_RECOMMEND_ACCEPTANCE_RATE:
            reasons.append("acceptance_rate_low")
        return reasons

    def _auto_ready(
        self,
        *,
        savings_rate: Decimal | None,
        feedback_coverage_rate: Decimal | None,
        quality_pass_rate: Decimal | None,
        acceptance_rate: Decimal | None,
    ) -> bool:
        return (
            self.sample_count >= _MIN_AUTO_SAMPLES
            and savings_rate is not None
            and savings_rate >= _MIN_AUTO_SAVINGS_COVERAGE
            and feedback_coverage_rate is not None
            and feedback_coverage_rate >= _MIN_AUTO_FEEDBACK_COVERAGE
            and (quality_pass_rate is None or quality_pass_rate >= _MIN_AUTO_QUALITY_PASS_RATE)
            and acceptance_rate is not None
            and acceptance_rate >= _MIN_AUTO_ACCEPTANCE_RATE
        )


def _segment_key(row: dict[str, Any]) -> _SegmentKey | None:
    lever = _lever(row)
    if lever is None:
        return None
    return _SegmentKey(
        task_type=str(_row_value(row, "task_type") or "unknown"),
        risk_level=str(_row_value(row, "risk_level") or "unknown"),
        provider_requested=str(_row_value(row, "provider_requested") or "unknown"),
        model_requested=str(_row_value(row, "model_requested") or "unknown"),
        provider_chosen=str(_row_value(row, "provider_chosen") or "unknown"),
        model_chosen=str(_row_value(row, "model_chosen") or "unknown"),
        lever=lever,
    )


def _lever(row: dict[str, Any]) -> str | None:
    lever = _row_value(row, "lever")
    if lever:
        return str(lever)
    cache_status = _row_value(row, "cache_status")
    if cache_status == "semantic":
        return "semantic_cache"
    if cache_status == "hit":
        return "exact_cache"
    if _row_value(row, "decision_type") == "cache":
        return "cache"
    return None


def _decision_id(row: dict[str, Any]) -> str | None:
    value = _row_value(row, "decision_event_id") or _row_value(row, "id")
    return str(value) if value is not None else None


def _decision_savings(row: dict[str, Any]) -> Decimal | None:
    value = _row_value(row, "realized_savings_usd")
    if value is not None:
        return _to_decimal(value)
    proof = _proof_from_row(row)
    if proof is None:
        return None
    return _to_decimal(proof.get("gross_savings_usd"))


def _proof_from_row(row: dict[str, Any]) -> dict[str, Any] | None:
    metadata = _row_value(row, "event_metadata")
    if not isinstance(metadata, dict):
        return None
    proof = metadata.get("savings_proof")
    return proof if isinstance(proof, dict) else None


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


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _optional_str(value: Any) -> str | None:
    return str(value) if value is not None else None


def _rate(numerator: int, denominator: int) -> str | None:
    rate = _rate_decimal(numerator, denominator)
    return str(rate.quantize(_RATE_QUANT)) if rate is not None else None


def _rate_decimal(numerator: int, denominator: int) -> Decimal | None:
    if denominator <= 0:
        return None
    return Decimal(numerator) / Decimal(denominator)


def _money(value: Decimal, row_count: int) -> str | None:
    return str(value) if row_count else None


def _average_money(total: Decimal, row_count: int) -> str | None:
    if row_count <= 0:
        return None
    return str(total / row_count)


def _top_counts(counter: Counter[str], limit: int | None = 10) -> list[dict[str, Any]]:
    items = sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    if limit is not None:
        items = items[:limit]
    return [{"key": key, "count": count} for key, count in items]


def _readiness_rank(status: str) -> int:
    return {
        "auto_apply_candidate": 0,
        "recommendable": 1,
        "quality_risk": 2,
        "savings_unproven": 3,
        "insufficient_data": 4,
    }.get(status, 5)
