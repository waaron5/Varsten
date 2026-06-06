"""Replay capture tap.

Samples a copy of real cache-miss traffic into the replay corpus so cheaper-model
swaps can be proven safe on a route's true distribution. This is the only place
prompt/response content is written outside the semantic cache, so it is gated
twice: a global setting and the project's opt-in flag, then sampled and bounded.

Called from the proxy's post-response best-effort path. It must never raise into
the request: a capture failure is logged and dropped, never surfaced to the
client.
"""

import random
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.models import Project, ReplaySample
from app.models.eval import SOURCE_TRAFFIC

logger = get_logger("varsten.eval.capture")

# Request fields worth keeping to replay a prompt faithfully. Messages are stored
# separately; sampling params shape the candidate call.
_PARAM_FIELDS = (
    "temperature",
    "top_p",
    "max_tokens",
    "max_completion_tokens",
    "tools",
    "tool_choice",
    "response_format",
    "seed",
    "stop",
    "n",
)


def capture_enabled(project: Project) -> bool:
    """Both gates must be on: the operator's global switch and the customer's
    per-project opt-in. Capture writes content, so consent is explicit."""
    return settings.eval_capture_enabled and project.eval_capture_enabled


def _route_key(model: str) -> str:
    # Phase 1 route identity is the requested model. Generalizes to feature/route
    # when the proxy carries richer per-request metadata.
    return model


def capture_sample(
    db: Session,
    project: Project,
    *,
    body: dict,
    response_payload: dict,
    model: str,
    input_tokens: int,
    output_tokens: int,
    now: datetime | None = None,
) -> None:
    """Best-effort: store a sampled (prompt, incumbent response) pair for replay.

    Skips silently when capture is off, the sample roll misses, the request has no
    messages, or there is no assembled response to learn from. Enforces the
    per-route cap by evicting the oldest traffic samples."""
    if not capture_enabled(project):
        return
    # Statistical sampling, not security-sensitive randomness.
    if random.random() >= settings.eval_sample_rate:  # nosec B311
        return
    messages = body.get("messages")
    if not messages or not response_payload:
        return

    try:
        at = now or datetime.now(UTC)
        params = {k: body[k] for k in _PARAM_FIELDS if k in body}
        route_key = _route_key(model)
        sample = ReplaySample(
            organization_id=project.organization_id,
            project_id=project.id,
            route_key=route_key,
            source=SOURCE_TRAFFIC,
            incumbent_model=model,
            request_messages=messages,
            request_params=params,
            incumbent_response=response_payload,
            expected_output=None,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            expires_at=at + timedelta(days=settings.eval_sample_ttl_days),
        )
        db.add(sample)
        db.commit()
        _enforce_route_cap(db, project.id, route_key)
    except Exception:
        db.rollback()
        logger.exception("replay capture failed", extra={"project_id": str(project.id)})


def _enforce_route_cap(db: Session, project_id: uuid.UUID, route_key: str) -> None:
    """Keep at most eval_max_samples_per_route traffic samples per route, evicting
    the oldest. Golden samples are never evicted (they are not source=traffic)."""
    cap = settings.eval_max_samples_per_route
    count = db.scalar(
        select(func.count())
        .select_from(ReplaySample)
        .where(
            ReplaySample.project_id == project_id,
            ReplaySample.route_key == route_key,
            ReplaySample.source == SOURCE_TRAFFIC,
        )
    )
    if count is None or count <= cap:
        return
    # Ids of the newest `cap` to keep; delete the rest.
    keep = (
        select(ReplaySample.id)
        .where(
            ReplaySample.project_id == project_id,
            ReplaySample.route_key == route_key,
            ReplaySample.source == SOURCE_TRAFFIC,
        )
        .order_by(ReplaySample.created_at.desc())
        .limit(cap)
    )
    db.execute(
        delete(ReplaySample).where(
            ReplaySample.project_id == project_id,
            ReplaySample.route_key == route_key,
            ReplaySample.source == SOURCE_TRAFFIC,
            ReplaySample.id.not_in(keep),
        )
    )
    db.commit()


def purge_expired(db: Session, now: datetime | None = None) -> int:
    """Delete traffic samples past their TTL. Golden samples have expires_at NULL
    and are untouched. Returns the number removed. Call from a periodic job."""
    at = now or datetime.now(UTC)
    result = db.execute(
        delete(ReplaySample).where(
            ReplaySample.expires_at.is_not(None),
            ReplaySample.expires_at <= at,
        )
    )
    db.commit()
    return result.rowcount or 0
