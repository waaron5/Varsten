"""Fail-open SDK telemetry ingest.

When the SDK falls back directly to the provider, Varsten never saw the request in
real time. The SDK reports a small, content-free marker here, best-effort and off
its own request path, so the dashboard can show fallback windows.

Hard rule (frozen in docs/design/SDK_FAILOPEN_DESIGN_FREEZE.md): only the allowlisted
metadata fields below are accepted. The schema is strict (extra="forbid"), so a
client that tries to send prompt or completion text gets a 422, never silent
storage. Phase 2 logs the markers; durable persistence + the dashboard panel are a
later phase.
"""

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import ApiKeyContext, require_api_key_context_async
from app.core.logging import get_logger

router = APIRouter(tags=["telemetry"])
logger = get_logger("varsten.sdk_fallback")


class FallbackMarker(BaseModel):
    """One fallback event. Allowlist only; no request/response content."""

    model_config = ConfigDict(extra="forbid")

    request_id: str | None = Field(default=None, max_length=128)
    timestamp: datetime | None = None
    reason_code: str = Field(max_length=64)
    phase: str = Field(max_length=32)
    varsten_status: int | None = None
    model: str | None = Field(default=None, max_length=128)
    latency_ms: int | None = Field(default=None, ge=0)
    sdk_version: str | None = Field(default=None, max_length=64)


class FallbackBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: list[FallbackMarker] = Field(max_length=500)


@router.post("/telemetry/fallback", status_code=202)
async def ingest_fallback(
    batch: FallbackBatch,
    api_context: ApiKeyContext = Depends(require_api_key_context_async),
) -> dict:
    """Accept a batch of fallback markers from the SDK. Write-only, best-effort.

    Authenticated by the project's vk_ key so markers are tenant-scoped. Returns
    202: the SDK fires this fire-and-forget and never blocks a customer request on
    the result.
    """
    project = api_context.project
    for ev in batch.events:
        logger.info(
            "sdk_fallback",
            extra={
                "project_id": str(project.id),
                "request_id": ev.request_id,
                "reason_code": ev.reason_code,
                "phase": ev.phase,
                "varsten_status": ev.varsten_status,
                "model": ev.model,
                "latency_ms": ev.latency_ms,
                "sdk_version": ev.sdk_version,
            },
        )
    return {"accepted": len(batch.events)}
