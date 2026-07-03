"""Background scheduler: cross-project sweeps and the loop lifecycle.

The per-project endpoints are tested elsewhere; here we cover the cross-project
entry points the scheduler drives (drift sweep + batch poll) and the loop's
start/stop and error-swallowing behaviour. OpenAI is mocked.
"""

import asyncio
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import httpx

import app.scheduler as scheduler_mod
from app.core.config import settings
from app.models import Project, ProxyPolicy, Recommendation, UsageEvent
from app.models.batch import STATUS_FINALIZED
from app.proxy import batch as batch_service
from app.proxy import drift as drift_mod
from app.proxy import openai_batch
from app.scheduler import Scheduler, _acquire_advisory_lock, _lock_key, _release_advisory_lock

INCUMBENT = "gpt-4o"
CANDIDATE = "gpt-4o-mini"


# --- cross-project drift sweep --------------------------------------------------


def _record_q(db, project, arm, model, ok):
    # Seed a ledger row via sync ORM (the drift sweep is sync and reads from the
    # same sync session; record_proxy_usage is async-only now).
    meta = {
        "proxy": True,
        "cache": "miss",
        "holdback": True,
        "arm": arm,
        "experiment_from": INCUMBENT,
        "experiment_to": CANDIDATE,
        "quality_ok": ok,
    }
    if arm == "treatment":
        meta.update({"routed": True, "routed_from": INCUMBENT, "routed_to": CANDIDATE, "saved_usd": "0.0107"})
    db.add(
        UsageEvent(
            project_id=project.id,
            organization_id=project.organization_id,
            api_key_id=None,
            provider="openai",
            model=model,
            operation="chat_completion",
            request_type="chat_completion",
            feature="proxy",
            environment="production",
            input_tokens=1000,
            output_tokens=500,
            cached_input_tokens=0,
            total_tokens=1500,
            cost_usd=Decimal("0.0018") if arm == "treatment" else Decimal("0.0125"),
            cost_source="catalog",
            pricing_status="priced",
            currency="USD",
            status="success",
            success=True,
            event_metadata=meta,
            occurred_at=datetime.now(UTC),
        )
    )


def test_sweep_all_projects_rolls_back_drift(client, provision, db_session, monkeypatch):
    monkeypatch.setattr(drift_mod, "MIN_ARM_SAMPLES", 4)
    ws = provision(sub="auth0|sched", email="sched@example.com")
    project = db_session.get(Project, uuid.UUID(ws["project_id"]))
    rec = Recommendation(
        organization_id=project.organization_id,
        project_id=project.id,
        dedupe_key=f"s-{uuid.uuid4()}",
        type="model_downshift",
        lever="model_downshift",
        title="x",
        description="x",
        risk_level="medium",
        confidence="medium",
        related_model=INCUMBENT,
        monthly_request_volume=100,
    )
    db_session.add(rec)
    policy = ProxyPolicy(
        organization_id=project.organization_id,
        project_id=project.id,
        lever="model_downshift",
        target_type="model",
        target_key=INCUMBENT,
        params={"candidate_model": CANDIDATE},
        enabled=True,
        holdback_percent=Decimal("0.1"),
        source_recommendation_id=rec.id,
    )
    db_session.add(policy)
    db_session.commit()

    # Peeking-safe rollback needs the confidence sequence for the quality drop to
    # clear the tolerance, so a maximal split still needs enough samples to confirm.
    for _ in range(15):
        _record_q(db_session, project, "control", INCUMBENT, True)
    for _ in range(15):
        _record_q(db_session, project, "treatment", CANDIDATE, False)
    db_session.commit()

    results = drift_mod.sweep_all_projects(db_session)
    assert str(project.id) in results
    db_session.refresh(policy)
    assert policy.enabled is False


# --- cross-project batch poll ---------------------------------------------------


def _mock_batch(monkeypatch, model=CANDIDATE):
    output = "\n".join(
        json.dumps(
            {
                "custom_id": c,
                "response": {
                    "status_code": 200,
                    "body": {"model": model, "usage": {"prompt_tokens": 1000, "completion_tokens": 500}},
                },
            }
        )
        for c in ("a", "b")
    ).encode()

    def handler(request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        if "/content" in path:
            return httpx.Response(200, content=output)
        if path.startswith("/v1/batches/") and method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": "batch-1",
                    "status": "completed",
                    "output_file_id": "file-out",
                    "request_counts": {"total": 2},
                },
            )
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
        # drift sweep + batch poll + cache purge + alert sweep + trial sweep
        # + learning promotion.
        assert len(sched._tasks) == 6
        # Starting again is idempotent.
        sched.start()
        assert len(sched._tasks) == 6
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


# --- advisory-lock coordination -------------------------------------------------


def test_lock_key_is_deterministic_and_distinct_per_job():
    assert _lock_key("drift-sweep") == _lock_key("drift-sweep")
    assert _lock_key("drift-sweep") != _lock_key("batch-poll")
    # Fits a Postgres signed bigint.
    assert -(2**63) <= _lock_key("drift-sweep") < 2**63


def test_advisory_lock_is_mutually_exclusive(db_session):
    """Real Postgres advisory lock: a second acquirer cannot take a lock another
    connection already holds, and it becomes available again after release."""
    got1, conn1 = _acquire_advisory_lock("drift-sweep")
    assert got1 is True and conn1 is not None
    try:
        got2, conn2 = _acquire_advisory_lock("drift-sweep")
        assert got2 is False  # held elsewhere -> a second instance must back off
        if conn2 is not None:
            _release_advisory_lock("drift-sweep", conn2)
    finally:
        _release_advisory_lock("drift-sweep", conn1)

    got3, conn3 = _acquire_advisory_lock("drift-sweep")
    assert got3 is True  # released -> available again
    _release_advisory_lock("drift-sweep", conn3)


def test_run_guarded_passes_through_when_disabled(monkeypatch):
    async def run():
        sched = Scheduler()
        monkeypatch.setattr(settings, "scheduler_advisory_lock_enabled", False)
        acquired = {"n": 0}

        def acquire_lock(name):
            acquired["n"] = 1
            return True, object()

        monkeypatch.setattr(scheduler_mod, "_acquire_advisory_lock", acquire_lock)
        calls = {"n": 0}

        async def job():
            calls["n"] += 1

        await sched._run_guarded("drift-sweep", job)
        assert calls["n"] == 1
        assert acquired["n"] == 0  # the lock path is never touched when disabled

    asyncio.run(run())


def test_run_guarded_runs_when_lock_acquired(monkeypatch):
    async def run():
        sched = Scheduler()
        monkeypatch.setattr(settings, "scheduler_advisory_lock_enabled", True)
        released = {"n": 0}
        monkeypatch.setattr(scheduler_mod, "_acquire_advisory_lock", lambda name: (True, object()))
        monkeypatch.setattr(
            scheduler_mod, "_release_advisory_lock", lambda name, conn: released.__setitem__("n", released["n"] + 1)
        )
        calls = {"n": 0}

        async def job():
            calls["n"] += 1

        await sched._run_guarded("drift-sweep", job)
        assert calls["n"] == 1
        assert released["n"] == 1  # lock always released after the tick

    asyncio.run(run())


def test_run_guarded_skips_when_lock_unavailable(monkeypatch):
    async def run():
        sched = Scheduler()
        monkeypatch.setattr(settings, "scheduler_advisory_lock_enabled", True)
        released = {"n": 0}
        # Lock held by another instance: acquired False but a live connection.
        monkeypatch.setattr(scheduler_mod, "_acquire_advisory_lock", lambda name: (False, object()))
        monkeypatch.setattr(
            scheduler_mod, "_release_advisory_lock", lambda name, conn: released.__setitem__("n", released["n"] + 1)
        )
        calls = {"n": 0}

        async def job():
            calls["n"] += 1

        await sched._run_guarded("drift-sweep", job)
        assert calls["n"] == 0  # another instance owns this tick
        assert released["n"] == 1  # the probe connection is still released

    asyncio.run(run())


def test_run_guarded_fails_open_on_lock_error(monkeypatch):
    async def run():
        sched = Scheduler()
        monkeypatch.setattr(settings, "scheduler_advisory_lock_enabled", True)
        # Lock infra error -> (False, None): run the job anyway, never drop a sweep.
        monkeypatch.setattr(scheduler_mod, "_acquire_advisory_lock", lambda name: (False, None))
        calls = {"n": 0}

        async def job():
            calls["n"] += 1

        await sched._run_guarded("drift-sweep", job)
        assert calls["n"] == 1

    asyncio.run(run())
