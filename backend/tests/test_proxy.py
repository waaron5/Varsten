"""Phase 1 inline proxy: auth, key vaulting, streaming pass-through, cache
hit/miss, and metadata-only ledger capture. OpenAI is mocked via an httpx
MockTransport so no real key or network is needed.

The proxy runs on the async DB stack, so these tests drive it with an httpx
AsyncClient over ASGI and provision + assert on the same savepoint-isolated async
session (async_provision / async_db_session). The one pure control-plane test
(toggle tenant scoping) stays on the sync session/client.
"""

import asyncio
import json
import time
import uuid
from time import perf_counter
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.models import Project, ProxyCacheEntry, UsageEvent
from app.proxy import cache as proxy_cache
from app.proxy import circuit, http_client
from app.proxy import router as proxy_router


@pytest.fixture(autouse=True)
def reset_circuit():
    circuit.reset_all()
    yield
    circuit.reset_all()


CHAT = "gpt-4o-mini"

NONSTREAM_RESPONSE = {
    "id": "chatcmpl-mock",
    "object": "chat.completion",
    "model": CHAT,
    "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hello world"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
}

STREAM_BODY = (
    'data: {"id":"x","object":"chat.completion.chunk","model":"gpt-4o-mini","choices":[{"index":0,"delta":{"role":"assistant","content":"Hello"},"finish_reason":null}]}\n\n'
    'data: {"id":"x","object":"chat.completion.chunk","model":"gpt-4o-mini","choices":[{"index":0,"delta":{"content":" world"},"finish_reason":"stop"}]}\n\n'
    'data: {"id":"x","object":"chat.completion.chunk","model":"gpt-4o-mini","choices":[],"usage":{"prompt_tokens":10,"completion_tokens":2,"total_tokens":12}}\n\n'
    "data: [DONE]\n\n"
)


DIM = 1536


def _fake_embedding(text: str) -> list[float]:
    """Deterministic, keyword-seeded unit vector. Same keyword -> same vector
    (cosine distance 0, a hit); different keyword -> orthogonal (distance 1, miss)."""
    vec = [0.0] * DIM
    t = text.lower()
    if "weather" in t:
        vec[0] = 1.0
    elif "stock" in t:
        vec[1] = 1.0
    elif "capital" in t:
        vec[2] = 1.0
    else:
        vec[3] = 1.0
    return vec


def _embeddings_response(request: httpx.Request) -> httpx.Response:
    payload = json.loads(request.content)
    return httpx.Response(200, json={"data": [{"embedding": _fake_embedding(payload["input"])}]})


@pytest.fixture
def mock_openai(monkeypatch):
    """Mock OpenAI (completions + embeddings) via MockTransport, counting each
    endpoint separately."""
    calls = {"completions": 0, "embeddings": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/embeddings"):
            calls["embeddings"] += 1
            return _embeddings_response(request)
        calls["completions"] += 1
        payload = json.loads(request.content)
        if payload.get("stream"):
            return httpx.Response(200, content=STREAM_BODY.encode(), headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json=NONSTREAM_RESPONSE)

    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(http_client, "_client", real_async_client(transport=httpx.MockTransport(handler)))
    return calls


@pytest.fixture
def controllable_openai(monkeypatch):
    """A mock upstream whose completion behavior can be flipped mid-test:
    ok | fail_503 | fail_400 | raise. Embeddings always succeed. Counts
    completions so tests can assert short-circuiting."""
    state: dict[str, Any] = {"completions": 0, "embeddings": 0, "mode": "ok"}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/embeddings"):
            state["embeddings"] += 1
            return _embeddings_response(request)
        state["completions"] += 1
        if state["mode"] == "raise":
            raise httpx.ConnectError("upstream unreachable")
        if state["mode"] == "fail_503":
            return httpx.Response(503, json={"error": "overloaded"})
        if state["mode"] == "fail_400":
            return httpx.Response(400, json={"error": "bad request"})
        payload = json.loads(request.content)
        if payload.get("stream"):
            return httpx.Response(200, content=STREAM_BODY.encode(), headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json=NONSTREAM_RESPONSE)

    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(http_client, "_client", real_async_client(transport=httpx.MockTransport(handler)))
    return state


def _configure_key(monkeypatch, project_id: str):
    monkeypatch.setattr(settings, "proxy_openai_keys", {project_id: "sk-test"})


def _b(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _msg(content="hi"):
    return {"model": CHAT, "messages": [{"role": "user", "content": content}]}


@pytest.mark.anyio
async def test_missing_provider_key_is_rejected(async_client, async_provision, mock_openai, monkeypatch):
    ws = await async_provision(sub="auth0|p", email="p@example.com")
    # No key configured for this project.
    monkeypatch.setattr(settings, "proxy_openai_keys", {})
    res = await async_client.post(
        "/v1/chat/completions",
        headers=_b(ws["api_key"]),
        json={"model": CHAT, "messages": [{"role": "user", "content": "hi"}]},
    )
    assert res.status_code == 502
    assert mock_openai["completions"] == 0


@pytest.mark.anyio
async def test_unauthenticated_proxy_rejected(async_client, mock_openai):
    res = await async_client.post("/v1/chat/completions", json={"model": CHAT, "messages": []})
    assert res.status_code == 401


@pytest.mark.anyio
async def test_nonstream_miss_forwards_and_records(
    async_client, async_db_session, async_provision, mock_openai, monkeypatch
):
    ws = await async_provision(sub="auth0|p", email="p@example.com")
    _configure_key(monkeypatch, ws["project_id"])
    body = {"model": CHAT, "messages": [{"role": "user", "content": "hi"}]}

    res = await async_client.post("/v1/chat/completions", headers=_b(ws["api_key"]), json=body)
    assert res.status_code == 200
    assert res.json()["choices"][0]["message"]["content"] == "Hello world"
    assert mock_openai["completions"] == 1

    events = (await async_db_session.scalars(select(UsageEvent).where(UsageEvent.project_id == ws["project_id"]))).all()
    assert len(events) == 1
    assert events[0].event_metadata["cache"] == "miss"
    assert events[0].input_tokens == 10 and events[0].output_tokens == 2
    # The miss was cached.
    cached = await async_db_session.scalar(
        select(func.count()).select_from(ProxyCacheEntry).where(ProxyCacheEntry.project_id == ws["project_id"])
    )
    assert cached == 1


@pytest.mark.anyio
async def test_streaming_miss_passes_through_and_records(
    async_client, async_db_session, async_provision, mock_openai, monkeypatch
):
    ws = await async_provision(sub="auth0|p", email="p@example.com")
    _configure_key(monkeypatch, ws["project_id"])
    body = {"model": CHAT, "messages": [{"role": "user", "content": "hi"}], "stream": True}

    res = await async_client.post("/v1/chat/completions", headers=_b(ws["api_key"]), json=body)
    assert res.status_code == 200
    # SSE passed through verbatim, content present.
    assert "Hello" in res.text and "[DONE]" in res.text
    assert mock_openai["completions"] == 1

    events = (await async_db_session.scalars(select(UsageEvent).where(UsageEvent.project_id == ws["project_id"]))).all()
    assert len(events) == 1
    assert events[0].output_tokens == 2


@pytest.mark.anyio
async def test_cache_hit_served_without_upstream(
    async_client, async_db_session, async_provision, mock_openai, monkeypatch
):
    ws = await async_provision(sub="auth0|p", email="p@example.com")
    _configure_key(monkeypatch, ws["project_id"])
    body = {"model": CHAT, "messages": [{"role": "user", "content": "hi"}]}

    first = await async_client.post("/v1/chat/completions", headers=_b(ws["api_key"]), json=body)
    assert first.status_code == 200
    assert mock_openai["completions"] == 1

    second = await async_client.post("/v1/chat/completions", headers=_b(ws["api_key"]), json=body)
    assert second.status_code == 200
    assert second.json()["choices"][0]["message"]["content"] == "Hello world"
    # No second upstream call: served from cache.
    assert mock_openai["completions"] == 1

    # Two ledger rows: one miss (real cost) and one hit ($0, naive cost recorded).
    events = (
        await async_db_session.scalars(
            select(UsageEvent).where(UsageEvent.project_id == ws["project_id"]).order_by(UsageEvent.received_at.asc())
        )
    ).all()
    assert len(events) == 2
    sources = {e.event_metadata["cache"] for e in events}
    assert sources == {"miss", "hit"}
    hit = next(e for e in events if e.event_metadata["cache"] == "hit")
    assert hit.cost_usd == 0


@pytest.mark.anyio
async def test_global_kill_switch_bypasses_optimization(
    async_client, async_db_session, async_provision, mock_openai, monkeypatch
):
    ws = await async_provision(sub="auth0|p", email="p@example.com")
    _configure_key(monkeypatch, ws["project_id"])
    monkeypatch.setattr(settings, "proxy_kill_switch", True)
    body = {"model": CHAT, "messages": [{"role": "user", "content": "hi"}]}

    first = await async_client.post("/v1/chat/completions", headers=_b(ws["api_key"]), json=body)
    second = await async_client.post("/v1/chat/completions", headers=_b(ws["api_key"]), json=body)

    assert first.status_code == 200 and second.status_code == 200
    assert first.headers["x-varsten-mode"] == "bypass"
    # Both forwarded: no cache serve, no cache store.
    assert mock_openai["completions"] == 2
    cached = await async_db_session.scalar(
        select(func.count()).select_from(ProxyCacheEntry).where(ProxyCacheEntry.project_id == ws["project_id"])
    )
    assert cached == 0


@pytest.mark.anyio
async def test_per_project_kill_switch_bypasses(
    async_client, async_db_session, async_provision, mock_openai, monkeypatch
):
    ws = await async_provision(sub="auth0|p", email="p@example.com")
    _configure_key(monkeypatch, ws["project_id"])

    # Set the project's bypass flag directly on the async session (the sync toggle
    # endpoint runs on a different connection this route can't see; its tenant
    # scoping is covered separately by test_toggle_is_tenant_scoped).
    project = await async_db_session.get(Project, uuid.UUID(ws["project_id"]))
    project.proxy_bypass_enabled = True
    await async_db_session.flush()

    body = {"model": CHAT, "messages": [{"role": "user", "content": "hi"}]}
    first = await async_client.post("/v1/chat/completions", headers=_b(ws["api_key"]), json=body)
    second = await async_client.post("/v1/chat/completions", headers=_b(ws["api_key"]), json=body)

    assert first.headers["x-varsten-mode"] == "bypass"
    assert second.headers["x-varsten-mode"] == "bypass"
    assert mock_openai["completions"] == 2  # bypassed, never served from cache


def test_toggle_is_tenant_scoped(client, provision):
    ws = provision(sub="auth0|a", email="a@example.com")
    provision(sub="auth0|b", email="b@example.com")

    # Unauthenticated and cross-tenant are both refused.
    assert (
        client.patch(f"/v1/projects/{ws['project_id']}/proxy-config", json={"bypass_enabled": True}).status_code == 401
    )
    assert (
        client.patch(
            f"/v1/projects/{ws['project_id']}/proxy-config",
            headers=_b("auth0|b"),
            json={"bypass_enabled": True},
        ).status_code
        == 403
    )


@pytest.mark.anyio
async def test_fail_open_when_cache_lookup_breaks(async_client, async_provision, mock_openai, monkeypatch, caplog):
    ws = await async_provision(sub="auth0|p", email="p@example.com")
    _configure_key(monkeypatch, ws["project_id"])

    def boom(*args, **kwargs):
        raise RuntimeError("cache backend down")

    monkeypatch.setattr(proxy_cache, "get_cached", boom)

    body = {"model": CHAT, "messages": [{"role": "user", "content": "hi"}]}
    with caplog.at_level("ERROR", logger="varsten.proxy"):
        res = await async_client.post("/v1/chat/completions", headers=_b(ws["api_key"]), json=body)

    # A broken cache must never break the client's call: it forwards anyway.
    assert res.status_code == 200
    assert res.json()["choices"][0]["message"]["content"] == "Hello world"
    assert mock_openai["completions"] == 1
    # And the failure is now visible, not silently swallowed.
    assert any("cache lookup failed" in r.message for r in caplog.records)


@pytest.mark.anyio
async def test_circuit_opens_and_fails_fast(async_client, async_provision, controllable_openai, monkeypatch):
    ws = await async_provision(sub="auth0|cb", email="cb@example.com")
    _configure_key(monkeypatch, ws["project_id"])
    monkeypatch.setattr(settings, "circuit_breaker_fail_threshold", 2)
    controllable_openai["mode"] = "fail_503"
    hdr = _b(ws["api_key"])

    # Two upstream failures are forwarded (and trip the breaker).
    assert (await async_client.post("/v1/chat/completions", headers=hdr, json=_msg())).status_code == 503
    assert (await async_client.post("/v1/chat/completions", headers=hdr, json=_msg("b"))).status_code == 503
    assert controllable_openai["completions"] == 2

    # Breaker now open: the next request short-circuits without touching upstream.
    res = await async_client.post("/v1/chat/completions", headers=hdr, json=_msg("c"))
    assert res.status_code == 503
    assert res.headers.get("x-varsten-circuit") == "open"
    assert res.json()["error"]["type"] == "varsten_circuit_open"
    assert controllable_openai["completions"] == 2  # not called


@pytest.mark.anyio
async def test_circuit_recovers_via_half_open(async_client, async_provision, controllable_openai, monkeypatch):
    ws = await async_provision(sub="auth0|cb", email="cb@example.com")
    _configure_key(monkeypatch, ws["project_id"])
    monkeypatch.setattr(settings, "circuit_breaker_fail_threshold", 1)
    monkeypatch.setattr(settings, "circuit_breaker_reset_seconds", 0.0)
    hdr = _b(ws["api_key"])

    controllable_openai["mode"] = "fail_503"
    await async_client.post("/v1/chat/completions", headers=hdr, json=_msg())  # opens

    # Reset window is zero, so the next request half-opens and probes. Upstream is
    # healthy again, so the probe succeeds and the breaker closes.
    controllable_openai["mode"] = "ok"
    res = await async_client.post("/v1/chat/completions", headers=hdr, json=_msg("again"))
    assert res.status_code == 200
    assert res.json()["choices"][0]["message"]["content"] == "Hello world"


@pytest.mark.anyio
async def test_client_error_does_not_trip_circuit(async_client, async_provision, controllable_openai, monkeypatch):
    ws = await async_provision(sub="auth0|cb", email="cb@example.com")
    _configure_key(monkeypatch, ws["project_id"])
    monkeypatch.setattr(settings, "circuit_breaker_fail_threshold", 1)
    controllable_openai["mode"] = "fail_400"
    hdr = _b(ws["api_key"])

    # A 4xx is the client's mistake; every call reaches upstream, breaker stays shut.
    for _ in range(3):
        assert (await async_client.post("/v1/chat/completions", headers=hdr, json=_msg())).status_code == 400
    assert controllable_openai["completions"] == 3


@pytest.mark.anyio
async def test_cache_hit_served_while_circuit_open(async_client, async_provision, controllable_openai, monkeypatch):
    ws = await async_provision(sub="auth0|cb", email="cb@example.com")
    _configure_key(monkeypatch, ws["project_id"])
    hdr = _b(ws["api_key"])
    body = _msg()

    # Prime the cache with a successful call.
    assert (await async_client.post("/v1/chat/completions", headers=hdr, json=body)).status_code == 200
    primed_calls = controllable_openai["completions"]

    # Force the breaker open.
    breaker = circuit.get_breaker(ws["project_id"])
    breaker.state = "open"
    breaker.opened_at = time.monotonic()

    # The identical request is a cache hit, served even though the circuit is open.
    res = await async_client.post("/v1/chat/completions", headers=hdr, json=body)
    assert res.status_code == 200
    assert res.headers["x-varsten-cache"] == "hit"
    assert controllable_openai["completions"] == primed_calls  # upstream never touched


# --- semantic cache ---


@pytest.mark.anyio
async def test_semantic_hit_on_near_duplicate(async_client, async_provision, mock_openai, monkeypatch):
    ws = await async_provision(sub="auth0|s", email="s@example.com")
    _configure_key(monkeypatch, ws["project_id"])
    hdr = _b(ws["api_key"])
    monkeypatch.setattr(settings, "semantic_cache_enabled", True)

    # First phrasing: a miss, forwarded, embedded, and cached.
    first = await async_client.post("/v1/chat/completions", headers=hdr, json=_msg("what is the weather today?"))
    assert first.status_code == 200
    assert first.headers["x-varsten-cache"] == "miss"

    # Different wording, same meaning (same embedding keyword) -> semantic hit, no
    # second upstream completion.
    second = await async_client.post("/v1/chat/completions", headers=hdr, json=_msg("tell me about the weather please"))
    assert second.status_code == 200
    assert second.headers["x-varsten-cache"] == "semantic"
    assert second.json()["choices"][0]["message"]["content"] == "Hello world"
    assert mock_openai["completions"] == 1  # only the first call reached OpenAI


@pytest.mark.anyio
async def test_semantic_miss_below_threshold(async_client, async_provision, mock_openai, monkeypatch):
    ws = await async_provision(sub="auth0|s", email="s@example.com")
    _configure_key(monkeypatch, ws["project_id"])
    hdr = _b(ws["api_key"])
    monkeypatch.setattr(settings, "semantic_cache_enabled", True)

    # Unrelated prompts embed to orthogonal vectors -> no match, both forwarded.
    await async_client.post("/v1/chat/completions", headers=hdr, json=_msg("what is the weather?"))
    res = await async_client.post("/v1/chat/completions", headers=hdr, json=_msg("what is the stock price?"))
    assert res.headers["x-varsten-cache"] == "miss"
    assert mock_openai["completions"] == 2


@pytest.mark.anyio
async def test_exact_repeat_skips_embedding(async_client, async_provision, mock_openai, monkeypatch):
    ws = await async_provision(sub="auth0|s", email="s@example.com")
    _configure_key(monkeypatch, ws["project_id"])
    hdr = _b(ws["api_key"])
    monkeypatch.setattr(settings, "semantic_cache_enabled", True)
    body = _msg("what is the weather?")

    await async_client.post("/v1/chat/completions", headers=hdr, json=body)  # miss: 1 embed + 1 completion
    res = await async_client.post("/v1/chat/completions", headers=hdr, json=body)  # exact hit: no embed

    assert res.headers["x-varsten-cache"] == "hit"
    assert mock_openai["completions"] == 1
    assert mock_openai["embeddings"] == 1  # the exact repeat did not embed again


@pytest.mark.anyio
async def test_embedding_failure_fails_open(async_client, async_provision, mock_openai, monkeypatch):
    ws = await async_provision(sub="auth0|s", email="s@example.com")
    _configure_key(monkeypatch, ws["project_id"])
    hdr = _b(ws["api_key"])
    monkeypatch.setattr(settings, "semantic_cache_enabled", True)

    async def no_embedding(text, client_key):
        return None

    monkeypatch.setattr(proxy_router, "embed", no_embedding)

    # Embedding is down: semantic lookup is skipped and the request forwards.
    first = await async_client.post("/v1/chat/completions", headers=hdr, json=_msg("what is the weather?"))
    assert first.status_code == 200
    assert first.headers["x-varsten-cache"] == "miss"


# --- hardening: stream-hang protection + cache-hit TTFB -------------------------


class _HangingStream:
    status_code = 200

    async def aiter_bytes(self):
        await asyncio.sleep(30)  # never delivers within the test's tiny total cap
        yield b""

    async def aread(self):
        return b""


class _HangingClient:
    """Stand-in httpx.AsyncClient whose streamed response never sends bytes, to
    simulate an upstream that connects then hangs mid-stream."""

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def stream(self, *a, **k):
        class _CM:
            async def __aenter__(self):
                return _HangingStream()

            async def __aexit__(self, *a):
                return False

        return _CM()


@pytest.mark.anyio
async def test_streaming_upstream_hang_is_cut_by_timeout(async_client, async_provision, monkeypatch):
    ws = await async_provision(sub="auth0|hang", email="hang@example.com")
    _configure_key(monkeypatch, ws["project_id"])
    monkeypatch.setattr(settings, "proxy_cache_enabled", False)
    # Tiny total cap so the hang is cut fast instead of pinning the slot.
    monkeypatch.setattr(settings, "proxy_stream_total_timeout_seconds", 0.2)
    monkeypatch.setattr(http_client, "_client", _HangingClient())

    start = perf_counter()
    res = await async_client.post(
        "/v1/chat/completions",
        headers=_b(ws["api_key"]),
        json={"model": CHAT, "messages": [{"role": "user", "content": "hi"}], "stream": True},
    )
    elapsed = perf_counter() - start
    # The hung stream was cut well before its 30s sleep: a clean SSE error, not a hang.
    assert res.status_code == 200
    assert "varsten_upstream_error" in res.text and "[DONE]" in res.text
    assert elapsed < 5  # nowhere near the 30s upstream sleep


@pytest.mark.anyio
async def test_latency_ms_is_captured(async_client, async_db_session, async_provision, mock_openai, monkeypatch):
    ws = await async_provision(sub="auth0|lat", email="lat@example.com")
    _configure_key(monkeypatch, ws["project_id"])
    body = _msg("latency probe")

    # Miss: latency = receipt -> upstream response.
    await async_client.post("/v1/chat/completions", headers=_b(ws["api_key"]), json=body)
    # Hit: latency = receipt -> cached payload ready (recorded by the background task).
    await async_client.post("/v1/chat/completions", headers=_b(ws["api_key"]), json=body)

    events = (
        await async_db_session.scalars(
            select(UsageEvent).where(UsageEvent.project_id == ws["project_id"]).order_by(UsageEvent.received_at.asc())
        )
    ).all()
    assert len(events) == 2
    # Both the miss and the hit now carry a real latency, not NULL.
    assert all(e.latency_ms is not None and e.latency_ms >= 0 for e in events)


@pytest.mark.anyio
async def test_cache_hit_ttfb_lower_than_miss(async_client, async_provision, mock_openai, monkeypatch):
    ws = await async_provision(sub="auth0|ttfb", email="ttfb@example.com")
    _configure_key(monkeypatch, ws["project_id"])
    hdr = _b(ws["api_key"])
    body = _msg("ttfb probe")

    t0 = perf_counter()
    miss = await async_client.post("/v1/chat/completions", headers=hdr, json=body)
    miss_ms = (perf_counter() - t0) * 1000
    assert miss.status_code == 200 and miss.headers["x-varsten-cache"] == "miss"

    t0 = perf_counter()
    hit = await async_client.post("/v1/chat/completions", headers=hdr, json=body)
    hit_ms = (perf_counter() - t0) * 1000
    assert hit.headers["x-varsten-cache"] == "hit"

    print(f"\nTTFB  miss={miss_ms:.2f}ms  hit={hit_ms:.2f}ms")
    # The hit avoids the upstream call AND defers all metering to a background task,
    # so it returns faster than the miss.
    assert hit_ms < miss_ms
