"""Phase 1 semantic cache: exact-match on a normalized request hash.

The cache_key is a hash of the request fields that determine the answer. Phase 1
matches exactly; real vector similarity replaces compute_cache_key later while the
rest of this module (lookup, store, hit accounting) stays the same.
"""
import hashlib
import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ProxyCacheEntry

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


def get_cached(
    db: Session, project_id: uuid.UUID, cache_key: str
) -> ProxyCacheEntry | None:
    return db.scalar(
        select(ProxyCacheEntry).where(
            ProxyCacheEntry.project_id == project_id,
            ProxyCacheEntry.cache_key == cache_key,
        )
    )


def record_hit(db: Session, entry: ProxyCacheEntry) -> None:
    entry.hit_count += 1
    entry.last_hit_at = datetime.now(timezone.utc)
    db.commit()


def store(
    db: Session,
    project_id: uuid.UUID,
    cache_key: str,
    model: str,
    response_payload: dict,
    input_tokens: int,
    output_tokens: int,
) -> ProxyCacheEntry:
    existing = get_cached(db, project_id, cache_key)
    if existing is not None:
        return existing
    entry = ProxyCacheEntry(
        project_id=project_id,
        cache_key=cache_key,
        model=model,
        response_payload=response_payload,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    db.add(entry)
    db.commit()
    return entry
