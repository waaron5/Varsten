"""Prompt embedding for semantic-cache matching.

Embeds the request's messages via OpenAI's embeddings API using the same project
key. Best-effort: any failure returns None so the caller degrades to a normal
cache miss and forwards (fail-open). Embedding the prompt is no new data boundary
since the prompt is already sent to OpenAI for the completion.
"""
import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("varsten.embedding")

EMBEDDINGS_PATH = "/v1/embeddings"


def embedding_input(body: dict) -> str:
    """Canonical text of the chat messages, what we embed for similarity."""
    parts: list[str] = []
    for message in body.get("messages", []):
        role = message.get("role", "")
        content = message.get("content", "")
        if isinstance(content, list):
            # Multimodal content blocks: keep the text parts.
            content = " ".join(
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            )
        parts.append(f"{role}: {content}")
    return "\n".join(parts).strip()


async def embed(text: str, client_key: str) -> list[float] | None:
    if not text:
        return None
    url = f"{settings.openai_base_url.rstrip('/')}{EMBEDDINGS_PATH}"
    payload = {
        "model": settings.embedding_model,
        "input": text,
        "dimensions": settings.embedding_dimensions,
    }
    headers = {"Authorization": f"Bearer {client_key}", "Content-Type": "application/json"}
    try:
        # Tightly bounded: this is on the cache-miss hot path. A slow embedding
        # must fail open to a normal forward, never add seconds to the request.
        async with httpx.AsyncClient(timeout=settings.embedding_timeout_seconds) as client:
            resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code != 200:
            logger.warning("embedding upstream non-200", extra={"status": resp.status_code})
            return None
        return resp.json()["data"][0]["embedding"]
    except Exception:
        # Fail-open: a failed embedding just means no semantic match this request.
        logger.exception("embedding failed")
        return None
