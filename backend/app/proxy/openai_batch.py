"""OpenAI Batch API client for the batching lever.

All of this runs off the request hot path (in the batch submit/sync endpoints and
the poller), never inline. It mirrors the real OpenAI flow: upload the input
.jsonl to the Files API, create a batch over it, poll the batch, and download the
output file when it completes. httpx is used the same way as the chat proxy, so
tests mock it with MockTransport.
"""
import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.proxy import openai

logger = get_logger("varsten.proxy.openai_batch")

# OpenAI batch statuses that mean the job is done (no more polling).
TERMINAL_STATUSES = {"completed", "failed", "expired", "cancelled"}


def _base() -> str:
    return settings.openai_base_url.rstrip("/")


async def upload_input_file(content: bytes, filename: str, key: str) -> str:
    """Upload the batch input .jsonl to the Files API (purpose=batch). Returns the
    OpenAI file id."""
    async with httpx.AsyncClient(timeout=settings.proxy_upstream_timeout_seconds) as client:
        resp = await client.post(
            f"{_base()}/v1/files",
            headers={"Authorization": f"Bearer {key}"},
            files={"file": (filename, content, "application/jsonl")},
            data={"purpose": "batch"},
        )
    resp.raise_for_status()
    return resp.json()["id"]


async def create_batch(input_file_id: str, endpoint: str, completion_window: str, key: str) -> dict:
    """Create a batch over an uploaded input file. Returns the batch object."""
    async with httpx.AsyncClient(timeout=settings.proxy_upstream_timeout_seconds) as client:
        resp = await client.post(
            f"{_base()}/v1/batches",
            headers={**openai.upstream_headers(key)},
            json={
                "input_file_id": input_file_id,
                "endpoint": endpoint,
                "completion_window": completion_window,
            },
        )
    resp.raise_for_status()
    return resp.json()


async def get_batch(batch_id: str, key: str) -> dict:
    """Fetch a batch's current state."""
    async with httpx.AsyncClient(timeout=settings.proxy_upstream_timeout_seconds) as client:
        resp = await client.get(
            f"{_base()}/v1/batches/{batch_id}",
            headers=openai.upstream_headers(key),
        )
    resp.raise_for_status()
    return resp.json()


async def download_file(file_id: str, key: str) -> bytes:
    """Download a file's content (the batch output or error file)."""
    async with httpx.AsyncClient(timeout=settings.proxy_upstream_timeout_seconds) as client:
        resp = await client.get(
            f"{_base()}/v1/files/{file_id}/content",
            headers={"Authorization": f"Bearer {key}"},
        )
    resp.raise_for_status()
    return resp.content
