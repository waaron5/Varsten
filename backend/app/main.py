from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import api_router
from app.core.config import settings
from app.core.logging import configure_logging
from app.core.observability import RequestContextMiddleware, init_sentry

configure_logging()
init_sentry()

app = FastAPI(title="Varsten", version="0.1.0")
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
