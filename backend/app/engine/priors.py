from __future__ import annotations

import threading
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from cachetools import TTLCache
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.engine.outcomes import outcome_prior_from_learning_candidate
from app.engine.types import OutcomePrior
from app.models import EngineOutcomePrior, Project

logger = get_logger("varsten.engine.priors")

_PRIOR_CACHE_TTL_SECONDS = 60
_prior_cache: TTLCache[tuple[str, str], tuple[OutcomePrior, ...]] = TTLCache(
    maxsize=4096,
    ttl=_PRIOR_CACHE_TTL_SECONDS,
)
_prior_lock = threading.Lock()


def clear_outcome_prior_cache(project_id: uuid.UUID | None = None) -> None:
    with _prior_lock:
        if project_id is None:
            _prior_cache.clear()
            return
        prefix = str(project_id)
        for key in list(_prior_cache.keys()):
            if key[0] == prefix:
                _prior_cache.pop(key, None)


def refresh_project_outcome_priors(
    db: Session,
    project: Project,
    candidates: list[dict[str, Any]],
    *,
    window_days: int,
    computed_at,
) -> int:
    """Replace this project's persisted outcome priors with the current sweep.

    The candidates are already content-free scored aggregates. This function
    persists only segment identity and aggregate evidence, never prompt/output
    text.
    """
    db.execute(delete(EngineOutcomePrior).where(EngineOutcomePrior.project_id == project.id))
    inserted = 0
    for candidate in candidates:
        segment = _dict(candidate.get("segment"))
        readiness = _dict(candidate.get("readiness"))
        quality = _dict(candidate.get("quality"))
        feedback = _dict(candidate.get("feedback"))
        db.add(
            EngineOutcomePrior(
                organization_id=project.organization_id,
                project_id=project.id,
                lever=_segment_value(segment, "lever"),
                task_type=_segment_value(segment, "task_type"),
                risk_level=_segment_value(segment, "risk_level"),
                provider_requested=_segment_value(segment, "provider_requested"),
                model_requested=_segment_value(segment, "model_requested"),
                provider_chosen=_segment_value(segment, "provider_chosen"),
                model_chosen=_segment_value(segment, "model_chosen"),
                readiness_status=str(readiness.get("status") or "insufficient_data"),
                sample_count=_int(candidate.get("sample_count")),
                measured_savings_count=_int(candidate.get("measured_savings_count")),
                total_gross_savings_usd=_decimal(candidate.get("total_gross_savings_usd")),
                average_gross_savings_usd=_decimal(candidate.get("average_gross_savings_usd")),
                quality_pass_rate=_decimal(quality.get("pass_rate")),
                feedback_acceptance_rate=_decimal(feedback.get("acceptance_rate")),
                reason_codes=[str(reason) for reason in readiness.get("reason_codes") or ()],
                window_days=window_days,
                computed_at=computed_at,
            )
        )
        inserted += 1
    clear_outcome_prior_cache(project.id)
    return inserted


async def outcome_priors_for_request(
    db: AsyncSession,
    project_id: uuid.UUID,
    model_requested: str,
) -> tuple[OutcomePrior, ...]:
    """Cheap hot-path lookup of precomputed priors.

    Fail-open: every error returns an empty tuple so the planner simply runs
    without learned evidence.
    """
    if not model_requested:
        return ()
    key = (str(project_id), model_requested)
    with _prior_lock:
        cached = _prior_cache.get(key)
    if cached is not None:
        return cached

    try:
        with db.no_autoflush:
            async with db.begin_nested():
                rows = (
                    await db.scalars(
                        select(EngineOutcomePrior)
                        .where(
                            EngineOutcomePrior.project_id == project_id,
                            EngineOutcomePrior.model_requested == model_requested,
                        )
                        .order_by(
                            EngineOutcomePrior.lever,
                            EngineOutcomePrior.computed_at.desc(),
                        )
                    )
                ).all()
        priors = tuple(_row_to_prior(row) for row in rows)
    except Exception:
        logger.exception("engine outcome prior lookup failed; planning without priors")
        return ()

    with _prior_lock:
        _prior_cache[key] = priors
    return priors


def _row_to_prior(row: EngineOutcomePrior) -> OutcomePrior:
    return outcome_prior_from_learning_candidate(
        {
            "segment": {"lever": row.lever},
            "readiness": {
                "status": row.readiness_status,
                "reason_codes": row.reason_codes or (),
            },
            "sample_count": row.sample_count,
            "measured_savings_count": row.measured_savings_count,
            "total_gross_savings_usd": _optional_str(row.total_gross_savings_usd),
            "average_gross_savings_usd": _optional_str(row.average_gross_savings_usd),
            "quality": {"pass_rate": _optional_str(row.quality_pass_rate)},
            "feedback": {"acceptance_rate": _optional_str(row.feedback_acceptance_rate)},
        }
    )


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _segment_value(segment: dict[str, Any], key: str) -> str:
    limits = {
        "lever": 32,
        "task_type": 128,
        "risk_level": 32,
        "provider_requested": 64,
        "model_requested": 128,
        "provider_chosen": 64,
        "model_chosen": 128,
    }
    return str(segment.get(key) or "unknown")[: limits.get(key, 255)]


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _optional_str(value: Any) -> str | None:
    return str(value) if value is not None else None
