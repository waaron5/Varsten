"""Cache content retention: stored responses get an expiry, lookups skip lapsed
entries, and the purge sweep deletes them. The cache is the documented exception
to the metadata-only ledger, so this is the retention control that exception
requires.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models import ProxyCacheEntry
from app.proxy import cache as proxy_cache


@pytest.mark.anyio
async def test_store_sets_expiry_and_lookup_skips_expired(async_db_session, async_provision, monkeypatch):
    p = await async_provision()
    project_id = uuid.UUID(p["project_id"])
    monkeypatch.setattr(settings, "proxy_cache_ttl_seconds", 3600)

    entry = await proxy_cache.store(async_db_session, project_id, "k1", "gpt-4o-mini", {"choices": []}, 10, 5)
    assert entry.expires_at is not None
    assert await proxy_cache.get_cached(async_db_session, project_id, "k1") is not None

    # Past its deadline, the same key is no longer served.
    entry.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await async_db_session.flush()
    assert await proxy_cache.get_cached(async_db_session, project_id, "k1") is None


@pytest.mark.anyio
async def test_semantic_search_skips_expired(async_db_session, async_provision):
    p = await async_provision()
    project_id = uuid.UUID(p["project_id"])
    embedding = [0.0] * settings.embedding_dimensions
    embedding[0] = 1.0
    async_db_session.add(
        ProxyCacheEntry(
            project_id=project_id,
            cache_key="sem",
            model="gpt-4o-mini",
            response_payload={"choices": []},
            input_tokens=1,
            output_tokens=1,
            embedding=embedding,
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
    )
    await async_db_session.flush()
    hit = await proxy_cache.semantic_search(async_db_session, project_id, "gpt-4o-mini", embedding, 0.1)
    assert hit is None


def test_purge_deletes_only_expired(client, db_session, provision):
    p = provision(sub="auth0|purge", email="purge@example.com")
    project_id = uuid.UUID(p["project_id"])
    now = datetime.now(UTC)
    db_session.add(
        ProxyCacheEntry(
            project_id=project_id,
            cache_key="live",
            model="m",
            response_payload={},
            input_tokens=1,
            output_tokens=1,
            expires_at=now + timedelta(hours=1),
        )
    )
    db_session.add(
        ProxyCacheEntry(
            project_id=project_id,
            cache_key="dead",
            model="m",
            response_payload={},
            input_tokens=1,
            output_tokens=1,
            expires_at=now - timedelta(hours=1),
        )
    )
    db_session.commit()

    deleted = proxy_cache.purge_expired(db_session, now=now)
    assert deleted == 1
    remaining = db_session.scalars(select(ProxyCacheEntry).where(ProxyCacheEntry.project_id == project_id)).all()
    assert {e.cache_key for e in remaining} == {"live"}
