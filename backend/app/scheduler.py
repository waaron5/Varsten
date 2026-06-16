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
(scheduler_enabled); production turns it on. With more than one app instance, run
it on a single leader or move to external cron so sweeps do not overlap.
"""

import asyncio

from app import alerts as alerts_mod
from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.proxy import batch as batch_service
from app.proxy import cache as cache_mod
from app.proxy import drift as drift_mod

logger = get_logger("varsten.scheduler")


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
        ]
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
            await self._run_safe(name, fn)

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
