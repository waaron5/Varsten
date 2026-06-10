from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import api_router
from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.core.observability import RequestContextMiddleware, init_sentry
from app.scheduler import scheduler

configure_logging()
init_sentry()
logger = get_logger("varsten.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start the background scheduler (drift sweep + batch poller) when enabled.
    # Off by default so tests and one-off processes never spawn loops.
    if settings.scheduler_enabled:
        scheduler.start()
    try:
        yield
    finally:
        if settings.scheduler_enabled:
            await scheduler.stop()


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


@app.get("/health")
def health() -> dict:
    return {"ok": True}
