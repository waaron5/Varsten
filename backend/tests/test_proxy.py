"""Phase 1 inline proxy: auth, key vaulting, streaming pass-through, cache
hit/miss, and metadata-only ledger capture. OpenAI is mocked via an httpx
MockTransport so no real key or network is needed."""

import json
import time
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.models import ProxyCacheEntry, UsageEvent
from app.proxy import cache as proxy_cache
from app.proxy import circuit
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

    def factory(*args, **kwargs):
        return real_async_client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(proxy_router.httpx, "AsyncClient", factory)
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

    def factory(*args, **kwargs):
        return real_async_client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(proxy_router.httpx, "AsyncClient", factory)
    return state


def _configure_key(monkeypatch, project_id: str):
    monkeypatch.setattr(settings, "proxy_openai_keys", {project_id: "sk-test"})


def _b(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_missing_provider_key_is_rejected(client, provision, mock_openai, monkeypatch):
    ws = provision(sub="auth0|p", email="p@example.com")
    # No key configured for this project.
    monkeypatch.setattr(settings, "proxy_openai_keys", {})
    res = client.post(
        "/v1/chat/completions",
        headers=_b(ws["api_key"]),
        json={"model": CHAT, "messages": [{"role": "user", "content": "hi"}]},
    )
    assert res.status_code == 502
    assert mock_openai["completions"] == 0


def test_unauthenticated_proxy_rejected(client, mock_openai):
    res = client.post("/v1/chat/completions", json={"model": CHAT, "messages": []})
    assert res.status_code == 401


def test_nonstream_miss_forwards_and_records(client, db_session, provision, mock_openai, monkeypatch):
    ws = provision(sub="auth0|p", email="p@example.com")
    _configure_key(monkeypatch, ws["project_id"])
    body = {"model": CHAT, "messages": [{"role": "user", "content": "hi"}]}

    res = client.post("/v1/chat/completions", headers=_b(ws["api_key"]), json=body)
    assert res.status_code == 200
    assert res.json()["choices"][0]["message"]["content"] == "Hello world"
    assert mock_openai["completions"] == 1

    events = db_session.scalars(select(UsageEvent).where(UsageEvent.project_id == ws["project_id"])).all()
    assert len(events) == 1
    assert events[0].event_metadata["cache"] == "miss"
    assert events[0].input_tokens == 10 and events[0].output_tokens == 2
    # The miss was cached.
    cached = db_session.scalar(
        select(func.count()).select_from(ProxyCacheEntry).where(ProxyCacheEntry.project_id == ws["project_id"])
    )
    assert cached == 1


def test_streaming_miss_passes_through_and_records(client, db_session, provision, mock_openai, monkeypatch):
    ws = provision(sub="auth0|p", email="p@example.com")
    _configure_key(monkeypatch, ws["project_id"])
    body = {"model": CHAT, "messages": [{"role": "user", "content": "hi"}], "stream": True}

    res = client.post("/v1/chat/completions", headers=_b(ws["api_key"]), json=body)
    assert res.status_code == 200
    # SSE passed through verbatim, content present.
    assert "Hello" in res.text and "[DONE]" in res.text
    assert mock_openai["completions"] == 1

    events = db_session.scalars(select(UsageEvent).where(UsageEvent.project_id == ws["project_id"])).all()
    assert len(events) == 1
    assert events[0].output_tokens == 2


def test_cache_hit_served_without_upstream(client, db_session, provision, mock_openai, monkeypatch):
    ws = provision(sub="auth0|p", email="p@example.com")
    _configure_key(monkeypatch, ws["project_id"])
    body = {"model": CHAT, "messages": [{"role": "user", "content": "hi"}]}

    first = client.post("/v1/chat/completions", headers=_b(ws["api_key"]), json=body)
    assert first.status_code == 200
    assert mock_openai["completions"] == 1

    second = client.post("/v1/chat/completions", headers=_b(ws["api_key"]), json=body)
    assert second.status_code == 200
    assert second.json()["choices"][0]["message"]["content"] == "Hello world"
    # No second upstream call: served from cache.
    assert mock_openai["completions"] == 1

    # Two ledger rows: one miss (real cost) and one hit ($0, naive cost recorded).
    events = db_session.scalars(
        select(UsageEvent).where(UsageEvent.project_id == ws["project_id"]).order_by(UsageEvent.received_at.asc())
    ).all()
    assert len(events) == 2
    sources = {e.event_metadata["cache"] for e in events}
    assert sources == {"miss", "hit"}
    hit = next(e for e in events if e.event_metadata["cache"] == "hit")
    assert hit.cost_usd == 0


def test_global_kill_switch_bypasses_optimization(client, db_session, provision, mock_openai, monkeypatch):
    ws = provision(sub="auth0|p", email="p@example.com")
    _configure_key(monkeypatch, ws["project_id"])
    monkeypatch.setattr(settings, "proxy_kill_switch", True)
    body = {"model": CHAT, "messages": [{"role": "user", "content": "hi"}]}

    first = client.post("/v1/chat/completions", headers=_b(ws["api_key"]), json=body)
    second = client.post("/v1/chat/completions", headers=_b(ws["api_key"]), json=body)

    assert first.status_code == 200 and second.status_code == 200
    assert first.headers["x-varsten-mode"] == "bypass"
    # Both forwarded: no cache serve, no cache store.
    assert mock_openai["completions"] == 2
    cached = db_session.scalar(
        select(func.count()).select_from(ProxyCacheEntry).where(ProxyCacheEntry.project_id == ws["project_id"])
    )
    assert cached == 0


def test_per_project_kill_switch_via_toggle(client, db_session, provision, mock_openai, monkeypatch):
    ws = provision(sub="auth0|p", email="p@example.com")
    _configure_key(monkeypatch, ws["project_id"])

    # Flip the project's kill switch through the authenticated toggle endpoint.
    toggled = client.patch(
        f"/v1/projects/{ws['project_id']}/proxy-config",
        headers=_b(ws["sub"]),
        json={"bypass_enabled": True},
    )
    assert toggled.status_code == 200
    assert toggled.json()["proxy_bypass_enabled"] is True

    body = {"model": CHAT, "messages": [{"role": "user", "content": "hi"}]}
    first = client.post("/v1/chat/completions", headers=_b(ws["api_key"]), json=body)
    second = client.post("/v1/chat/completions", headers=_b(ws["api_key"]), json=body)

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


def test_fail_open_when_cache_lookup_breaks(client, provision, mock_openai, monkeypatch, caplog):
    ws = provision(sub="auth0|p", email="p@example.com")
    _configure_key(monkeypatch, ws["project_id"])

    def boom(*args, **kwargs):
        raise RuntimeError("cache backend down")

    monkeypatch.setattr(proxy_cache, "get_cached", boom)

    body = {"model": CHAT, "messages": [{"role": "user", "content": "hi"}]}
    with caplog.at_level("ERROR", logger="varsten.proxy"):
        res = client.post("/v1/chat/completions", headers=_b(ws["api_key"]), json=body)

    # A broken cache must never break the client's call: it forwards anyway.
    assert res.status_code == 200
    assert res.json()["choices"][0]["message"]["content"] == "Hello world"
    assert mock_openai["completions"] == 1
    # And the failure is now visible, not silently swallowed.
    assert any("cache lookup failed" in r.message for r in caplog.records)


def _msg(content="hi"):
    return {"model": CHAT, "messages": [{"role": "user", "content": content}]}


def test_circuit_opens_and_fails_fast(client, provision, controllable_openai, monkeypatch):
    ws = provision(sub="auth0|cb", email="cb@example.com")
    _configure_key(monkeypatch, ws["project_id"])
    monkeypatch.setattr(settings, "circuit_breaker_fail_threshold", 2)
    controllable_openai["mode"] = "fail_503"
    hdr = _b(ws["api_key"])

    # Two upstream failures are forwarded (and trip the breaker).
    assert client.post("/v1/chat/completions", headers=hdr, json=_msg()).status_code == 503
    assert client.post("/v1/chat/completions", headers=hdr, json=_msg("b")).status_code == 503
    assert controllable_openai["completions"] == 2

    # Breaker now open: the next request short-circuits without touching upstream.
    res = client.post("/v1/chat/completions", headers=hdr, json=_msg("c"))
    assert res.status_code == 503
    assert res.headers.get("x-varsten-circuit") == "open"
    assert res.json()["error"]["type"] == "varsten_circuit_open"
    assert controllable_openai["completions"] == 2  # not called


def test_circuit_recovers_via_half_open(client, provision, controllable_openai, monkeypatch):
    ws = provision(sub="auth0|cb", email="cb@example.com")
    _configure_key(monkeypatch, ws["project_id"])
    monkeypatch.setattr(settings, "circuit_breaker_fail_threshold", 1)
    monkeypatch.setattr(settings, "circuit_breaker_reset_seconds", 0.0)
    hdr = _b(ws["api_key"])

    controllable_openai["mode"] = "fail_503"
    client.post("/v1/chat/completions", headers=hdr, json=_msg())  # opens

    # Reset window is zero, so the next request half-opens and probes. Upstream is
    # healthy again, so the probe succeeds and the breaker closes.
    controllable_openai["mode"] = "ok"
    res = client.post("/v1/chat/completions", headers=hdr, json=_msg("again"))
    assert res.status_code == 200
    assert res.json()["choices"][0]["message"]["content"] == "Hello world"


def test_client_error_does_not_trip_circuit(client, provision, controllable_openai, monkeypatch):
    ws = provision(sub="auth0|cb", email="cb@example.com")
    _configure_key(monkeypatch, ws["project_id"])
    monkeypatch.setattr(settings, "circuit_breaker_fail_threshold", 1)
    controllable_openai["mode"] = "fail_400"
    hdr = _b(ws["api_key"])

    # A 4xx is the client's mistake; every call reaches upstream, breaker stays shut.
    for _ in range(3):
        assert client.post("/v1/chat/completions", headers=hdr, json=_msg()).status_code == 400
    assert controllable_openai["completions"] == 3


def test_cache_hit_served_while_circuit_open(client, provision, controllable_openai, monkeypatch):
    ws = provision(sub="auth0|cb", email="cb@example.com")
    _configure_key(monkeypatch, ws["project_id"])
    hdr = _b(ws["api_key"])
    body = _msg()

    # Prime the cache with a successful call.
    assert client.post("/v1/chat/completions", headers=hdr, json=body).status_code == 200
    primed_calls = controllable_openai["completions"]

    # Force the breaker open.
    breaker = circuit.get_breaker(ws["project_id"])
    breaker.state = "open"
    breaker.opened_at = time.monotonic()

    # The identical request is a cache hit, served even though the circuit is open.
    res = client.post("/v1/chat/completions", headers=hdr, json=body)
    assert res.status_code == 200
    assert res.headers["x-varsten-cache"] == "hit"
    assert controllable_openai["completions"] == primed_calls  # upstream never touched


# --- semantic cache ---


def test_semantic_hit_on_near_duplicate(client, db_session, provision, mock_openai, monkeypatch):
    ws = provision(sub="auth0|s", email="s@example.com")
    _configure_key(monkeypatch, ws["project_id"])
    hdr = _b(ws["api_key"])
    monkeypatch.setattr(settings, "semantic_cache_enabled", True)

    # First phrasing: a miss, forwarded, embedded, and cached.
    first = client.post("/v1/chat/completions", headers=hdr, json=_msg("what is the weather today?"))
    assert first.status_code == 200
    assert first.headers["x-varsten-cache"] == "miss"

    # Different wording, same meaning (same embedding keyword) -> semantic hit, no
    # second upstream completion.
    second = client.post("/v1/chat/completions", headers=hdr, json=_msg("tell me about the weather please"))
    assert second.status_code == 200
    assert second.headers["x-varsten-cache"] == "semantic"
    assert second.json()["choices"][0]["message"]["content"] == "Hello world"
    assert mock_openai["completions"] == 1  # only the first call reached OpenAI


def test_semantic_miss_below_threshold(client, provision, mock_openai, monkeypatch):
    ws = provision(sub="auth0|s", email="s@example.com")
    _configure_key(monkeypatch, ws["project_id"])
    hdr = _b(ws["api_key"])
    monkeypatch.setattr(settings, "semantic_cache_enabled", True)

    # Unrelated prompts embed to orthogonal vectors -> no match, both forwarded.
    client.post("/v1/chat/completions", headers=hdr, json=_msg("what is the weather?"))
    res = client.post("/v1/chat/completions", headers=hdr, json=_msg("what is the stock price?"))
    assert res.headers["x-varsten-cache"] == "miss"
    assert mock_openai["completions"] == 2


def test_exact_repeat_skips_embedding(client, provision, mock_openai, monkeypatch):
    ws = provision(sub="auth0|s", email="s@example.com")
    _configure_key(monkeypatch, ws["project_id"])
    hdr = _b(ws["api_key"])
    monkeypatch.setattr(settings, "semantic_cache_enabled", True)
    body = _msg("what is the weather?")

    client.post("/v1/chat/completions", headers=hdr, json=body)  # miss: 1 embed + 1 completion
    res = client.post("/v1/chat/completions", headers=hdr, json=body)  # exact hit: no embed

    assert res.headers["x-varsten-cache"] == "hit"
    assert mock_openai["completions"] == 1
    assert mock_openai["embeddings"] == 1  # the exact repeat did not embed again


def test_embedding_failure_fails_open(client, provision, mock_openai, monkeypatch):
    ws = provision(sub="auth0|s", email="s@example.com")
    _configure_key(monkeypatch, ws["project_id"])
    hdr = _b(ws["api_key"])
    monkeypatch.setattr(settings, "semantic_cache_enabled", True)

    async def no_embedding(text, client_key):
        return None

    monkeypatch.setattr(proxy_router, "embed", no_embedding)

    # Embedding is down: semantic lookup is skipped and the request forwards.
    first = client.post("/v1/chat/completions", headers=hdr, json=_msg("what is the weather?"))
    assert first.status_code == 200
    assert first.headers["x-varsten-cache"] == "miss"
    # A near-duplicate cannot match (nothing was embedded), so it forwards too.
    second = client.post("/v1/chat/completions", headers=hdr, json=_msg("how is the weather now?"))
    assert second.status_code == 200
    assert mock_openai["completions"] == 2
