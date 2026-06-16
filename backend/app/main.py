from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import api_router
from app.core.config import assert_production_ready, settings
from app.core.logging import configure_logging, get_logger
from app.core.observability import RequestContextMiddleware, init_sentry
from app.db.session import get_async_db
from app.proxy import http_client
from app.proxy.router import beta_router as proxy_beta_router
from app.scheduler import scheduler

configure_logging()
init_sentry()
logger = get_logger("varsten.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail loudly at boot if APP_ENV=production but the config is dev-unsafe (no
    # auth, env-vaulted keys, localhost CORS). A no-op outside production.
    assert_production_ready(settings)
    # Warm the shared upstream HTTP pool so the first proxied request does not
    # pay the client construction cost, and close it cleanly on shutdown.
    http_client.get_client()
    # Start the background scheduler (drift sweep + batch poller) when enabled.
    # Off by default so tests and one-off processes never spawn loops.
    if settings.scheduler_enabled:
        scheduler.start()
    try:
        yield
    finally:
        if settings.scheduler_enabled:
            await scheduler.stop()
        await http_client.aclose()


app = FastAPI(title="Varsten", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Added last so it is the outermost middleware: it sets the request id before any
# other layer runs and access-logs the final status after everything else.
app.add_middleware(RequestContextMiddleware)
app.include_router(api_router)
app.include_router(proxy_beta_router)


@app.get("/health")
def health() -> dict:
    """Liveness: the process is up and serving. No dependencies touched, so a load
    balancer keeps the instance in rotation even during a brief DB blip."""
    return {"ok": True}


@app.get("/health/ready")
async def health_ready(db: AsyncSession = Depends(get_async_db)) -> JSONResponse:
    """Readiness: the instance can actually serve requests, i.e. the database is
    reachable. Returns 503 when it is not, so orchestration holds traffic off a
    pod that cannot reach Postgres instead of serving errors."""
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        logger.exception("readiness check failed: database unreachable")
        return JSONResponse({"ok": False, "database": "unreachable"}, status_code=503)
    return JSONResponse({"ok": True, "database": "ok"})
