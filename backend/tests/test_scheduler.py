"""Background scheduler: cross-project sweeps and the loop lifecycle.

The per-project endpoints are tested elsewhere; here we cover the cross-project
entry points the scheduler drives (drift sweep + batch poll) and the loop's
start/stop and error-swallowing behaviour. OpenAI is mocked.
"""
import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest

from app.core.config import settings
from app.models import ModelPrice, Project, ProxyPolicy, Recommendation
from app.models.batch import STATUS_FINALIZED
from app.proxy import batch as batch_service
from app.proxy import drift as drift_mod
from app.proxy import openai_batch
from app.proxy.ledger import record_proxy_usage
from app.scheduler import Scheduler

INCUMBENT = "gpt-4o"
CANDIDATE = "gpt-4o-mini"


# --- cross-project drift sweep --------------------------------------------------

def _record_q(db, project, arm, model, ok):
    record_proxy_usage(
        db, project, None, model=model, input_tokens=1000, output_tokens=500,
        cached_input_tokens=0, cache_hit=False,
        naive_model=INCUMBENT if arm == "treatment" else None,
        arm=arm, experiment_from=INCUMBENT, experiment_to=CANDIDATE, quality_ok=ok,
    )


def test_sweep_all_projects_rolls_back_drift(client, provision, db_session, monkeypatch):
    monkeypatch.setattr(drift_mod, "MIN_ARM_SAMPLES", 4)
    ws = provision(sub="auth0|sched", email="sched@example.com")
    project = db_session.get(Project, uuid.UUID(ws["project_id"]))
    rec = Recommendation(
        organization_id=project.organization_id, project_id=project.id,
        dedupe_key=f"s-{uuid.uuid4()}", type="cheaper_model", lever="cheaper_model",
        title="x", description="x", risk_level="medium", confidence="medium",
        related_model=INCUMBENT, monthly_request_volume=100,
    )
    db_session.add(rec)
    policy = ProxyPolicy(
        organization_id=project.organization_id, project_id=project.id,
        lever="cheaper_model", target_type="model", target_key=INCUMBENT,
        params={"candidate_model": CANDIDATE}, enabled=True,
        holdback_percent=Decimal("0.1"), source_recommendation_id=rec.id,
    )
    db_session.add(policy)
    db_session.commit()

    for _ in range(5):
        _record_q(db_session, project, "control", INCUMBENT, True)
    for _ in range(5):
        _record_q(db_session, project, "treatment", CANDIDATE, False)
    db_session.commit()

    results = drift_mod.sweep_all_projects(db_session)
    assert str(project.id) in results
    db_session.refresh(policy)
    assert policy.enabled is False


# --- cross-project batch poll ---------------------------------------------------

def _mock_batch(monkeypatch, model=CANDIDATE):
    output = "\n".join(json.dumps({
        "custom_id": c, "response": {"status_code": 200, "body": {
            "model": model, "usage": {"prompt_tokens": 1000, "completion_tokens": 500}}}})
        for c in ("a", "b")).encode()

    def handler(request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        if "/content" in path:
            return httpx.Response(200, content=output)
        if path.startswith("/v1/batches/") and method == "GET":
            return httpx.Response(200, json={
                "id": "batch-1", "status": "completed",
                "output_file_id": "file-out", "request_counts": {"total": 2}})
        return httpx.Response(404)

    real = httpx.AsyncClient
    monkeypatch.setattr(openai_batch.httpx, "AsyncClient", lambda *a, **k: real(transport=httpx.MockTransport(handler)))


def test_poll_all_projects_finalizes_jobs(tmp_path, client, provision, db_session, monkeypatch):
    monkeypatch.setattr(settings, "batch_storage_backend", "local")
    monkeypatch.setattr(settings, "batch_local_storage_dir", str(tmp_path / "b"))
    ws = provision(sub="auth0|sched2", email="sched2@example.com")
    project = db_session.get(Project, uuid.UUID(ws["project_id"]))
    monkeypatch.setattr(settings, "proxy_openai_keys", {str(project.id): "sk-test"})

    job = batch_service.stage_input_job(
        db_session, project, None, endpoint="/v1/chat/completions", completion_window="24h"
    )
    job.provider_batch_id = "batch-1"
    job.status = "in_progress"
    db_session.commit()

    _mock_batch(monkeypatch)
    out = asyncio.run(batch_service.poll_all_projects(db_session))
    assert out.get(str(project.id)) == 1
    db_session.refresh(job)
    assert job.status == STATUS_FINALIZED


# --- loop lifecycle -------------------------------------------------------------

def test_scheduler_start_stop_lifecycle():
    async def run():
        sched = Scheduler()
        sched.start()
        assert len(sched._tasks) == 2
        # Starting again is idempotent.
        sched.start()
        assert len(sched._tasks) == 2
        await sched.stop()
        assert sched._tasks == []

    asyncio.run(run())


def test_run_safe_swallows_exceptions():
    async def run():
        sched = Scheduler()

        async def boom():
            raise RuntimeError("kaboom")

        # Must not raise: a failing job can never kill the loop.
        await sched._run_safe("test", boom)

    asyncio.run(run())


def test_loop_runs_job_then_stops(monkeypatch):
    async def run():
        sched = Scheduler()
        calls = {"n": 0}

        async def job():
            calls["n"] += 1

        # Tiny interval so the loop ticks quickly, then stop.
        task = asyncio.create_task(sched._loop("fast", 0.01, job))
        await asyncio.sleep(0.05)
        sched._stop.set()
        await task
        assert calls["n"] >= 1

    asyncio.run(run())
