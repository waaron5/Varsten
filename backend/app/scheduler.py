"""In-process periodic scheduler for the engine's background safety work.

Two jobs that must run without a client request:
- the quality-drift sweep, which auto-rolls-back a routed/trimmed arm that has
  degraded against its live control arm;
- the batch poller, which advances in-flight batch jobs and finalizes completed
  ones (downloading output, measuring savings).

Both already exist as per-project endpoints (cron-callable); this runs them across
all projects on an interval so production does not depend on an external cron.

Dependency-free: a cancellable asyncio loop per job, each tick on a fresh DB
session and wrapped so one failure never kills the loop. Off by default
(scheduler_enabled); production turns it on.

Multi-instance safety: with app_max_instances > 1, every instance would otherwise
run every sweep, overlapping the work. Set scheduler_advisory_lock_enabled=true and
each job tick takes a per-job Postgres advisory lock (pg_try_advisory_lock) for the
duration of that tick; an instance that cannot take the lock skips the tick, so a
given sweep never runs concurrently. The lock is session-scoped on a dedicated
connection and released (or dropped when the instance dies), so leadership fails
over automatically with no external coordinator. Lock acquisition fails open: if
the lock infrastructure errors, the job still runs (the sweeps are idempotent, and
silently dropping a safety sweep is worse than running it twice).
"""

import asyncio
import hashlib
from typing import Any

from sqlalchemy import text

from app import alerts as alerts_mod
from app import billing_lifecycle
from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import SessionLocal, engine
from app.engine import promotion as promotion_mod
from app.proxy import batch as batch_service
from app.proxy import cache as cache_mod
from app.proxy import drift as drift_mod

logger = get_logger("varsten.scheduler")

# Namespaced so our advisory keys never collide with any other use of Postgres
# advisory locks in the same database.
_ADVISORY_NAMESPACE = "varsten.scheduler:"


def _lock_key(name: str) -> int:
    """A deterministic signed 64-bit key for a job's advisory lock.

    Postgres advisory locks take a bigint; derive one from the job name so every
    instance computes the same key for the same job (and distinct jobs get distinct
    keys, letting different instances run different sweeps while never doubling up on
    the same one)."""
    digest = hashlib.blake2b((_ADVISORY_NAMESPACE + name).encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big", signed=True)


def _acquire_advisory_lock(name: str) -> tuple[bool, Any]:
    """Try to take the per-job advisory lock on a dedicated connection.

    Returns (acquired, connection). The connection is held open while the job runs
    so the session-scoped lock persists for the whole tick. On any error returns
    (False, None) so the caller can fail open."""
    try:
        conn = engine.connect()
    except Exception:
        logger.exception("advisory lock connection failed; running without lock", extra={"job": name})
        return False, None
    try:
        acquired = bool(conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": _lock_key(name)}).scalar())
        return acquired, conn
    except Exception:
        logger.exception("advisory lock acquisition failed; running without lock", extra={"job": name})
        conn.close()
        return False, None


def _release_advisory_lock(name: str, conn: Any) -> None:
    """Release the per-job lock and close its connection. Best-effort."""
    try:
        conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _lock_key(name)})
    except Exception:
        logger.exception("advisory unlock failed", extra={"job": name})
    finally:
        conn.close()


class Scheduler:
    def __init__(self) -> None:
        self._tasks: list[asyncio.Task] = []
        self._stop = asyncio.Event()

    def start(self) -> None:
        if self._tasks:
            return
        self._stop = asyncio.Event()
        self._tasks = [
            asyncio.create_task(self._loop("drift-sweep", settings.drift_sweep_interval_seconds, self._run_drift)),
            asyncio.create_task(self._loop("batch-poll", settings.batch_poll_interval_seconds, self._run_batch)),
            asyncio.create_task(
                self._loop("cache-purge", settings.cache_purge_interval_seconds, self._run_cache_purge)
            ),
            asyncio.create_task(
                self._loop("alert-sweep", settings.alert_sweep_interval_seconds, self._run_alert_sweep)
            ),
            asyncio.create_task(
                self._loop("trial-sweep", settings.trial_sweep_interval_seconds, self._run_trial_sweep)
            ),
        ]
        if settings.learning_promotion_interval_seconds > 0:
            self._tasks.append(
                asyncio.create_task(
                    self._loop(
                        "learning-promotion",
                        settings.learning_promotion_interval_seconds,
                        self._run_learning_promotion,
                    )
                )
            )
        logger.info("scheduler started", extra={"jobs": len(self._tasks)})

    async def stop(self) -> None:
        self._stop.set()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        logger.info("scheduler stopped")

    async def _loop(self, name: str, interval: float, fn) -> None:
        # Wait up to `interval`; if stop is signalled meanwhile, exit promptly.
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
                break  # stop signalled
            except TimeoutError:
                pass
            await self._run_guarded(name, fn)

    async def _run_guarded(self, name: str, fn) -> None:
        """Run this tick under the per-job advisory lock when multi-instance
        coordination is enabled; otherwise run it directly. An instance that cannot
        take the lock skips the tick (another instance is running it). A lock
        infrastructure error fails open and runs the job anyway."""
        if not settings.scheduler_advisory_lock_enabled:
            await self._run_safe(name, fn)
            return
        acquired, conn = await asyncio.to_thread(_acquire_advisory_lock, name)
        if conn is None:
            # Fail open: lock infra is unavailable, so run rather than drop a sweep.
            await self._run_safe(name, fn)
            return
        try:
            if not acquired:
                logger.debug("advisory lock held by another instance; skipping tick", extra={"job": name})
                return
            await self._run_safe(name, fn)
        finally:
            await asyncio.to_thread(_release_advisory_lock, name, conn)

    async def _run_safe(self, name: str, fn) -> None:
        try:
            await fn()
        except Exception:
            logger.exception("scheduled job failed", extra={"job": name})

    async def _run_drift(self) -> None:
        # The drift sweep is synchronous DB work; run it off the event loop.
        def work() -> dict:
            db = SessionLocal()
            try:
                return drift_mod.sweep_all_projects(db)
            finally:
                db.close()

        rolled = await asyncio.to_thread(work)
        if rolled:
            logger.warning("drift sweep rolled back routes", extra={"projects": list(rolled)})

    async def _run_batch(self) -> None:
        db = SessionLocal()
        try:
            await batch_service.poll_all_projects(db)
        finally:
            db.close()

        # Delete staged batch content (input/output .jsonl) past its TTL. Sync DB +
        # storage work, so run it off the event loop like the cache purge.
        def purge() -> int:
            pdb = SessionLocal()
            try:
                return batch_service.purge_expired_objects(pdb)
            finally:
                pdb.close()

        purged = await asyncio.to_thread(purge)
        if purged:
            logger.info("batch object purge removed expired content", extra={"jobs": purged})

    async def _run_cache_purge(self) -> None:
        # Deleting past-due cache content (the retention sweep) is synchronous DB
        # work; run it off the event loop like the drift sweep.
        def work() -> int:
            db = SessionLocal()
            try:
                return cache_mod.purge_expired(db)
            finally:
                db.close()

        deleted = await asyncio.to_thread(work)
        if deleted:
            logger.info("cache purge removed expired entries", extra={"deleted": deleted})

    async def _run_trial_sweep(self) -> None:
        # Downgrade unpaid, elapsed Performance trials to Free observe-only. Pure DB
        # work; run it off the event loop. Never touches traffic or the proxy.
        def work() -> list:
            db = SessionLocal()
            try:
                return billing_lifecycle.sweep_expired_trials(db)
            finally:
                db.close()

        expired = await asyncio.to_thread(work)
        if expired:
            logger.info("trial sweep downgraded expired trials", extra={"organizations": [str(o) for o in expired]})

    async def _run_learning_promotion(self) -> None:
        # Learning promotion and adaptive holdback management are pure DB work;
        # run them off the event loop. They never apply a new optimization, so a
        # failure here only delays a proposal or measurement-cost adjustment.
        def work() -> dict:
            db = SessionLocal()
            try:
                return promotion_mod.sweep_all_projects(db)
            finally:
                db.close()

        results = await asyncio.to_thread(work)
        if results:
            logger.info("learning promotion sweep updated projects", extra={"projects": list(results)})

    async def _run_alert_sweep(self) -> None:
        # Budget/alert evaluation + delivery is synchronous DB + I/O work; run it off
        # the event loop. Delivery is best-effort and never raises into the sweep.
        def work() -> int:
            db = SessionLocal()
            try:
                return alerts_mod.sweep_all_projects(db)
            finally:
                db.close()

        delivered = await asyncio.to_thread(work)
        if delivered:
            logger.info("alert sweep delivered notifications", extra={"delivered": delivered})


scheduler = Scheduler()
