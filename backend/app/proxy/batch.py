"""Batching lever service: the async /v1/batches data plane.

Lifecycle (all off the request hot path):

  stage_input_job   -> a BatchJob row + a tenant-scoped storage key. The client
                       uploads its .jsonl straight to storage via a pre-signed URL.
  submit_job        -> stream the staged input to OpenAI's Files API, create the
                       batch, record provider ids.
  sync_job          -> poll the batch; when it completes, finalize.
  finalize_job      -> download the output, stage it, measure savings (batch price
                       vs the synchronous price for the same tokens), write the
                       ledger, mark finalized.

The proxy never holds the file in memory beyond the single streamed hop to
OpenAI; content lives in object storage and is TTL'd.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.models import BatchJob, ModelPrice, Project
from app.models.batch import (
    ACTIVE_STATUSES,
    STATUS_COMPLETED,
    STATUS_CREATED,
    STATUS_FAILED,
    STATUS_FINALIZED,
    STATUS_IN_PROGRESS,
    STATUS_SUBMITTED,
)
from app.proxy import openai_batch
from app.proxy.ledger import record_batch_usage
from app.storage import get_storage

logger = get_logger("varsten.proxy.batch")

_Q = Decimal("0.000000000001")

# OpenAI batch status -> our status. Anything else stays in_progress (still polling).
_STATUS_MAP = {
    "validating": STATUS_IN_PROGRESS,
    "in_progress": STATUS_IN_PROGRESS,
    "finalizing": STATUS_IN_PROGRESS,
    "completed": STATUS_COMPLETED,
    "failed": STATUS_FAILED,
    "expired": "expired",
    "cancelling": STATUS_IN_PROGRESS,
    "cancelled": "cancelled",
}


def _input_key(project_id: uuid.UUID, job_id: uuid.UUID) -> str:
    return f"{project_id}/batches/{job_id}/input.jsonl"


def _output_key(project_id: uuid.UUID, job_id: uuid.UUID) -> str:
    return f"{project_id}/batches/{job_id}/output.jsonl"


def purge_expired_objects(db: Session, now: datetime | None = None) -> int:
    """Delete staged batch content (input/output .jsonl) past its TTL from storage.

    The batch file is a documented content store, like the cache, so it must be
    retention-bounded. The BatchJob row is metadata and is kept (savings history,
    audit); only the content objects are deleted, and objects_purged_at marks the
    row so a re-sweep does not retry. Per-object delete failures are logged, never
    raised, so one bad key cannot stall the sweep. Returns the number of jobs
    purged. Sync (the scheduler runs it off the event loop)."""
    at = now or datetime.now(UTC)
    storage = get_storage()
    jobs = db.scalars(
        select(BatchJob).where(
            BatchJob.expires_at.is_not(None),
            BatchJob.expires_at <= at,
            BatchJob.objects_purged_at.is_(None),
        )
    ).all()
    purged = 0
    for job in jobs:
        for key in (job.input_storage_key, job.output_storage_key):
            if not key or key == "pending":
                continue
            try:
                storage.delete(key)
            except Exception:
                logger.warning("batch object delete failed", extra={"job_id": str(job.id), "key": key})
        job.objects_purged_at = at
        purged += 1
    db.commit()
    return purged


def stage_input_job(
    db: Session,
    project: Project,
    api_key_id: uuid.UUID | None,
    *,
    endpoint: str,
    completion_window: str,
    now: datetime | None = None,
) -> BatchJob:
    """Create a job awaiting the client's upload. The caller hands back the
    pre-signed upload URL for its storage key."""
    at = now or datetime.now(UTC)
    job = BatchJob(
        organization_id=project.organization_id,
        project_id=project.id,
        api_key_id=api_key_id,
        endpoint=endpoint,
        completion_window=completion_window,
        status=STATUS_CREATED,
        input_storage_key="pending",
        expires_at=at + timedelta(hours=settings.batch_object_ttl_hours),
    )
    db.add(job)
    db.flush()  # need the id for the key
    job.input_storage_key = _input_key(project.id, job.id)
    db.commit()
    db.refresh(job)
    return job


async def submit_job(db: Session, job: BatchJob, client_key: str) -> BatchJob:
    """Stream the staged input to OpenAI and create the batch."""
    storage = get_storage()
    if not storage.exists(job.input_storage_key):
        raise FileNotFoundError("input file has not been uploaded yet")
    content = storage.read(job.input_storage_key)

    file_id = await openai_batch.upload_input_file(content, "batch_input.jsonl", client_key)
    batch = await openai_batch.create_batch(file_id, job.endpoint, job.completion_window, client_key)
    job.provider_input_file_id = file_id
    job.provider_batch_id = batch.get("id")
    job.status = _STATUS_MAP.get(batch.get("status", ""), STATUS_SUBMITTED)
    job.submitted_at = datetime.now(UTC)
    db.commit()
    db.refresh(job)
    return job


async def sync_job(db: Session, job: BatchJob, client_key: str, *, now: datetime | None = None) -> BatchJob:
    """Poll the provider and, on completion, finalize. Idempotent: a finalized job
    is returned untouched."""
    if job.status in (STATUS_FINALIZED, STATUS_FAILED) or not job.provider_batch_id:
        return job
    batch = await openai_batch.get_batch(job.provider_batch_id, client_key)
    provider_status = batch.get("status", "")
    job.status = _STATUS_MAP.get(provider_status, job.status)
    job.provider_output_file_id = batch.get("output_file_id") or job.provider_output_file_id
    job.provider_error_file_id = batch.get("error_file_id") or job.provider_error_file_id
    counts = batch.get("request_counts") or {}
    if counts.get("total"):
        job.request_count = int(counts["total"])
    db.commit()

    if job.status == STATUS_COMPLETED and job.provider_output_file_id:
        return await finalize_job(db, job, client_key, now=now)
    db.refresh(job)
    return job


async def finalize_job(db: Session, job: BatchJob, client_key: str, *, now: datetime | None = None) -> BatchJob:
    """Download and stage the output, measure savings, write the ledger, mark done."""
    at = now or datetime.now(UTC)
    output = await openai_batch.download_file(job.provider_output_file_id, client_key)
    storage = get_storage()
    out_key = _output_key(job.project_id, job.id)
    storage.write(out_key, output)
    job.output_storage_key = out_key

    project = db.get(Project, job.project_id)
    totals = _measure_and_record(db, project, job, output, at)
    job.request_count = totals["request_count"] or job.request_count
    job.input_tokens = totals["input_tokens"]
    job.output_tokens = totals["output_tokens"]
    job.actual_cost_usd = totals["actual_cost_usd"]
    job.naive_cost_usd = totals["naive_cost_usd"]
    job.saved_usd = totals["saved_usd"]
    job.status = STATUS_FINALIZED
    job.completed_at = at
    db.commit()
    db.refresh(job)
    return job


async def poll_all_projects(db: Session, *, now: datetime | None = None) -> dict[str, int]:
    """Poll in-flight batch jobs for every project that has one. The scheduler's
    entry point. Projects without a configured OpenAI key are skipped. Returns a
    map of project_id -> number of jobs synced."""
    from app.proxy.keys import provider_key_for_project

    project_ids = list(db.scalars(select(BatchJob.project_id).where(BatchJob.status.in_(ACTIVE_STATUSES)).distinct()))
    out: dict[str, int] = {}
    for pid in project_ids:
        project = db.get(Project, pid)
        if project is None:
            continue
        client_key = provider_key_for_project(pid, "openai")
        if not client_key:
            continue
        synced = await sync_active_jobs(db, project, client_key, now=now)
        out[str(pid)] = len(synced)
    return out


async def sync_active_jobs(
    db: Session, project: Project, client_key: str, *, now: datetime | None = None
) -> list[BatchJob]:
    """Sweep this project's non-terminal jobs. The production trigger is a
    scheduled poller; exposed as an endpoint so a cron (or the operator) drives it."""
    jobs = list(
        db.scalars(
            select(BatchJob).where(
                BatchJob.project_id == project.id,
                BatchJob.status.in_(ACTIVE_STATUSES),
            )
        )
    )
    synced: list[BatchJob] = []
    for job in jobs:
        try:
            synced.append(await sync_job(db, job, client_key, now=now))
        except Exception:
            logger.exception("batch sync failed", extra={"batch_job_id": str(job.id)})
    return synced


# --- savings measurement --------------------------------------------------------


def _latest_model_price(db: Session, model: str, provider: str, at: datetime) -> ModelPrice | None:
    return db.scalars(
        select(ModelPrice)
        .where(
            ModelPrice.model_key == model,
            ModelPrice.provider == provider,
            ModelPrice.effective_at <= at,
        )
        .order_by(ModelPrice.effective_at.desc())
        .limit(1)
    ).first()


def _parse_output_usage(output: bytes) -> tuple[dict[str, dict], int]:
    """Group token usage by model across the output .jsonl lines. Returns
    ({model: {input, output}}, request_count)."""
    by_model: dict[str, dict] = {}
    count = 0
    for line in output.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        body = ((row.get("response") or {}).get("body")) or {}
        usage = body.get("usage") or {}
        model = body.get("model")
        if not model:
            continue
        count += 1
        agg = by_model.setdefault(model, {"input": 0, "output": 0})
        agg["input"] += int(usage.get("prompt_tokens") or 0)
        agg["output"] += int(usage.get("completion_tokens") or 0)
    return by_model, count


def _measure_and_record(db: Session, project: Project, job: BatchJob, output: bytes, at: datetime) -> dict:
    """Price each model's tokens at batch vs sync rates and write a ledger row per
    model. Savings are recorded only where the catalog has batch pricing; an
    unpriced model is surfaced (saved=None), never fabricated."""
    by_model, count = _parse_output_usage(output)
    total_in = total_out = 0
    total_actual = Decimal("0")
    total_naive = Decimal("0")
    any_priced = False

    for model, agg in by_model.items():
        in_tok, out_tok = agg["input"], agg["output"]
        total_in += in_tok
        total_out += out_tok
        price = _latest_model_price(db, model, "openai", at)
        actual = naive = None
        if price is not None:
            naive = (in_tok * price.input_cost_per_token + out_tok * price.output_cost_per_token).quantize(_Q)
            if price.input_cost_per_token_batch is not None and price.output_cost_per_token_batch is not None:
                actual = (
                    in_tok * price.input_cost_per_token_batch + out_tok * price.output_cost_per_token_batch
                ).quantize(_Q)
            else:
                actual = naive  # no batch rate known: no measurable discount
        if actual is not None and naive is not None:
            any_priced = True
            total_actual += actual
            total_naive += naive
        record_batch_usage(
            db,
            project,
            job.api_key_id,
            model=model,
            input_tokens=in_tok,
            output_tokens=out_tok,
            actual_cost_usd=actual,
            naive_cost_usd=naive,
            request_count=count,
            now=at,
        )

    saved = (total_naive - total_actual) if any_priced else None
    return {
        "request_count": count,
        "input_tokens": total_in,
        "output_tokens": total_out,
        "actual_cost_usd": total_actual if any_priced else None,
        "naive_cost_usd": total_naive if any_priced else None,
        "saved_usd": saved,
    }
