"""Prompt embedding for semantic-cache matching.

Embeds the request's messages via OpenAI's embeddings API using the same project
key. Best-effort: any failure returns None so the caller degrades to a normal
cache miss and forwards (fail-open). Embedding the prompt is no new data boundary
since the prompt is already sent to OpenAI for the completion.
"""

from app.core.config import settings
from app.core.logging import get_logger
from app.proxy import http_client
from app.proxy.ledger import record_overhead_usage

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
                block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text"
            )
        parts.append(f"{role}: {content}")
    return "\n".join(parts).strip()


async def embed(text: str, client_key: str, *, db=None, project=None) -> list[float] | None:
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
        # Shared pooled client so the embedding call rides a warm connection.
        resp = await http_client.get_client().post(
            url, headers=headers, json=payload, timeout=settings.embedding_timeout_seconds
        )
        if resp.status_code != 200:
            logger.warning("embedding upstream non-200", extra={"status": resp.status_code})
            return None
        payload = resp.json()
        if db is not None and project is not None:
            usage = payload.get("usage") or {}
            input_tokens = int(usage.get("prompt_tokens") or usage.get("total_tokens") or 0)
            await record_overhead_usage(
                db,
                project,
                provider="openai",
                model=settings.embedding_model,
                operation="embedding",
                input_tokens=input_tokens,
                output_tokens=0,
                overhead="embedding",
            )
        return payload["data"][0]["embedding"]
    except Exception:
        # Fail-open: a failed embedding just means no semantic match this request.
        logger.exception("embedding failed")
        return None
