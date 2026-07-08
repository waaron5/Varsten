"""Batching lever API: the async /v1/batches mirror.

Authenticated by the same vk_ API key as the inline proxy. The client stages its
.jsonl directly to object storage via a pre-signed URL (the proxy never holds the
file), then creates a batch referencing the staged input. Varsten streams it to
OpenAI's Batch API off-path, polls, and serves the results, measuring the ~50%
batch savings against the synchronous price.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import ApiKeyContext, require_api_key_context
from app.auth.entitlements import require_performance
from app.core.config import settings
from app.db.session import get_db
from app.models import BatchJob, Project
from app.models.batch import STATUS_CREATED, STATUS_FINALIZED
from app.proxy import batch as batch_service
from app.proxy.keys import provider_key_for_project
from app.storage import get_storage

router = APIRouter(tags=["batches"])


def _client_key(project: Project) -> str:
    key = provider_key_for_project(project.id, "openai")
    if not key:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="no OpenAI key configured for this project",
        )
    return key


def _serialize(job: BatchJob) -> dict:
    return {
        "id": str(job.id),
        "status": job.status,
        "endpoint": job.endpoint,
        "completion_window": job.completion_window,
        "input_file_id": str(job.id),
        "provider_batch_id": job.provider_batch_id,
        "request_count": job.request_count,
        "input_tokens": job.input_tokens,
        "output_tokens": job.output_tokens,
        "actual_cost_usd": str(job.actual_cost_usd) if job.actual_cost_usd is not None else None,
        "naive_cost_usd": str(job.naive_cost_usd) if job.naive_cost_usd is not None else None,
        "saved_usd": str(job.saved_usd) if job.saved_usd is not None else None,
        "error": job.error,
        "submitted_at": job.submitted_at,
        "completed_at": job.completed_at,
        "expires_at": job.expires_at,
        "created_at": job.created_at,
    }


def _get_job(db: Session, project: Project, job_id: uuid.UUID) -> BatchJob:
    job = db.get(BatchJob, job_id)
    if job is None or job.project_id != project.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="batch not found")
    return job


@router.post("/batches/input-files", response_model=None)
def create_input_file(
    api_context: ApiKeyContext = Depends(require_api_key_context),
    db: Session = Depends(get_db),
) -> dict:
    """Reserve a batch job and return a pre-signed URL to upload the input .jsonl
    straight to object storage. The returned input_file_id is used in POST /batches."""
    job = batch_service.stage_input_job(
        db,
        api_context.project,
        api_context.api_key.id,
        endpoint="/v1/chat/completions",
        completion_window=settings.batch_completion_window,
    )
    upload_url = get_storage().presigned_put_url(job.input_storage_key)
    return {
        "input_file_id": str(job.id),
        "upload_url": upload_url,
        "upload_method": "PUT",
        "storage_key": job.input_storage_key,
        "expires_at": job.expires_at,
    }


@router.put("/batches/local-storage/{key:path}", response_model=None)
async def local_storage_upload(
    key: str,
    request: Request,
    api_context: ApiKeyContext = Depends(require_api_key_context),
) -> dict:
    """Dev/CI upload passthrough for the local storage backend. In production the
    client PUTs straight to S3 via the pre-signed URL and never hits this route."""
    if settings.batch_storage_backend != "local":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    # Tenant isolation: a key is <project_id>/...; reject writes outside the caller's tree.
    if not key.startswith(f"{api_context.project.id}/"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
    body = await request.body()
    get_storage().write(key, body)
    return {"ok": True, "bytes": len(body)}


class CreateBatch(BaseModel):
    input_file_id: uuid.UUID
    endpoint: str = "/v1/chat/completions"
    completion_window: str = Field(default="24h")


@router.post("/batches", response_model=None)
async def create_batch(
    payload: CreateBatch,
    api_context: ApiKeyContext = Depends(require_api_key_context),
    db: Session = Depends(get_db),
) -> dict:
    """Create the batch over an uploaded input file: stream it to OpenAI and start
    the job. Fails if the input has not been uploaded yet."""
    project = api_context.project
    # Submitting a batch is a behaviour-changing savings lever -> Optimize only.
    require_performance(db, project, action="Submitting a batch job")
    job = _get_job(db, project, payload.input_file_id)
    if job.status != STATUS_CREATED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="batch already submitted")
    job.endpoint = payload.endpoint
    job.completion_window = payload.completion_window
    db.commit()
    try:
        job = await batch_service.submit_job(db, job, _client_key(project))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _serialize(job)


@router.get("/batches", response_model=None)
def list_batches(
    api_context: ApiKeyContext = Depends(require_api_key_context),
    db: Session = Depends(get_db),
) -> list[dict]:
    jobs = db.scalars(
        select(BatchJob)
        .where(BatchJob.project_id == api_context.project.id)
        .order_by(BatchJob.created_at.desc())
        .limit(100)
    )
    return [_serialize(j) for j in jobs]


@router.get("/batches/{job_id}", response_model=None)
async def get_batch(
    job_id: uuid.UUID,
    api_context: ApiKeyContext = Depends(require_api_key_context),
    db: Session = Depends(get_db),
) -> dict:
    """Current batch state. Syncs from the provider (and finalizes + measures
    savings on completion) before returning."""
    project = api_context.project
    job = _get_job(db, project, job_id)
    if job.provider_batch_id:
        job = await batch_service.sync_job(db, job, _client_key(project))
    return _serialize(job)


@router.get("/batches/{job_id}/output", response_model=None)
def batch_output(
    job_id: uuid.UUID,
    api_context: ApiKeyContext = Depends(require_api_key_context),
    db: Session = Depends(get_db),
) -> dict:
    """A pre-signed URL to download the finalized output .jsonl from storage."""
    job = _get_job(db, api_context.project, job_id)
    if job.status != STATUS_FINALIZED or not job.output_storage_key:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="batch output not ready")
    return {"output_url": get_storage().presigned_get_url(job.output_storage_key)}


@router.post("/batches/sync", response_model=None)
async def sync_batches(
    api_context: ApiKeyContext = Depends(require_api_key_context),
    db: Session = Depends(get_db),
) -> dict:
    """Poll all non-terminal jobs for this project and finalize completed ones. The
    production trigger is a scheduled poller; exposed for cron/operator use."""
    project = api_context.project
    synced = await batch_service.sync_active_jobs(db, project, _client_key(project))
    return {"synced": [_serialize(j) for j in synced]}
