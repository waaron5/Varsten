"""Phase 1 semantic cache: exact-match on a normalized request hash.

The cache_key is a hash of the request fields that determine the answer. Phase 1
matches exactly; real vector similarity replaces compute_cache_key later while the
rest of this module (lookup, store, hit accounting) stays the same.
"""

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import ProxyCacheEntry


def _live(now: datetime):
    """A cache row is servable when it has no expiry (legacy) or has not lapsed."""
    return or_(ProxyCacheEntry.expires_at.is_(None), ProxyCacheEntry.expires_at > now)


# Request fields that determine the completion. Anything affecting the output must
# be here so two different requests never collide on one cache entry.
_KEYED_FIELDS = (
    "model",
    "messages",
    "temperature",
    "top_p",
    "max_tokens",
    "max_completion_tokens",
    "tools",
    "tool_choice",
    "response_format",
    "seed",
    "stop",
    "n",
)


def compute_cache_key(body: dict) -> str:
    keyed = {k: body[k] for k in _KEYED_FIELDS if k in body}
    blob = json.dumps(keyed, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


async def get_cached(db: AsyncSession, project_id: uuid.UUID, cache_key: str) -> ProxyCacheEntry | None:
    return await db.scalar(
        select(ProxyCacheEntry).where(
            ProxyCacheEntry.project_id == project_id,
            ProxyCacheEntry.cache_key == cache_key,
            _live(datetime.now(UTC)),
        )
    )


async def semantic_search(
    db: AsyncSession,
    project_id: uuid.UUID,
    model: str,
    embedding: list[float] | None,
    threshold: float,
) -> ProxyCacheEntry | None:
    """The nearest cached entry for this project+model within the cosine-distance
    threshold, or None. Scoped to the same model so we never serve one model's
    answer for another's request."""
    if embedding is None:
        return None
    distance = ProxyCacheEntry.embedding.cosine_distance(embedding).label("distance")
    row = (
        await db.execute(
            select(ProxyCacheEntry, distance)
            .where(
                ProxyCacheEntry.project_id == project_id,
                ProxyCacheEntry.model == model,
                ProxyCacheEntry.embedding.is_not(None),
                _live(datetime.now(UTC)),
            )
            .order_by(distance)
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    entry, dist = row
    if dist is not None and dist <= threshold:
        return entry
    return None


async def record_hit(db: AsyncSession, entry: ProxyCacheEntry) -> None:
    entry.hit_count += 1
    entry.last_hit_at = datetime.now(UTC)
    await db.commit()


async def store(
    db: AsyncSession,
    project_id: uuid.UUID,
    cache_key: str,
    model: str,
    response_payload: dict,
    input_tokens: int,
    output_tokens: int,
    embedding: list[float] | None = None,
) -> ProxyCacheEntry:
    existing = await get_cached(db, project_id, cache_key)
    if existing is not None:
        return existing
    now = datetime.now(UTC)
    entry = ProxyCacheEntry(
        project_id=project_id,
        cache_key=cache_key,
        model=model,
        response_payload=response_payload,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        embedding=embedding,
        # Stored content carries a retention deadline from the moment it is written.
        expires_at=now + timedelta(seconds=settings.proxy_cache_ttl_seconds),
    )
    db.add(entry)
    await db.commit()
    return entry


def purge_expired(db: Session, now: datetime | None = None) -> int:
    """Delete cache entries past their retention deadline. Sync (the scheduler runs
    it off the event loop, like the drift sweep). Returns the number deleted."""
    at = now or datetime.now(UTC)
    result = db.execute(
        delete(ProxyCacheEntry).where(
            ProxyCacheEntry.expires_at.is_not(None),
            ProxyCacheEntry.expires_at <= at,
        )
    )
    db.commit()
    return result.rowcount or 0
