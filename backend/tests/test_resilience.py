"""Upstream retries and fallback (slice C1).

A transient provider failure (connect error, 429, 5xx) is retried before the
client sees it, and when retries are exhausted the request falls back to a
configured degradation model. Retries never happen after bytes have streamed, and
a 4xx (the client's own bad request) is relayed unchanged with no retry.
"""

import json

import httpx
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models import RequestDecisionEvent
from app.proxy import http_client, resilience

CHAT = "gpt-4o-mini"
FALLBACK = "gpt-4o-fallback"

NONSTREAM = {
    "id": "chatcmpl-mock",
    "object": "chat.completion",
    "model": CHAT,
    "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hello world"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
}
STREAM_BODY = (
    'data: {"id":"x","object":"chat.completion.chunk","model":"gpt-4o-mini",'
    '"choices":[{"index":0,"delta":{"role":"assistant","content":"Hello"},"finish_reason":"stop"}]}\n\n'
    'data: {"id":"x","object":"chat.completion.chunk","model":"gpt-4o-mini",'
    '"choices":[],"usage":{"prompt_tokens":10,"completion_tokens":2,"total_tokens":12}}\n\n'
    "data: [DONE]\n\n"
)


def _b(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _configure_key(monkeypatch, project_id: str):
    monkeypatch.setattr(settings, "proxy_openai_keys", {project_id: "sk-test"})


def _fast_retries(monkeypatch):
    monkeypatch.setattr(settings, "proxy_retry_base_delay_seconds", 0.0)
    monkeypatch.setattr(settings, "proxy_retry_max_delay_seconds", 0.0)


def _msg(content="hi"):
    return {"model": CHAT, "messages": [{"role": "user", "content": content}]}


def _embeddings(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={"data": [{"embedding": [0.1] * 1536, "index": 0}], "model": "text-embedding-3-small", "usage": {}},
    )


def _install(monkeypatch, handler):
    monkeypatch.setattr(http_client, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))


# --- pure policy ---------------------------------------------------------------


def test_backoff_delays_count_and_cap(monkeypatch):
    monkeypatch.setattr(settings, "proxy_retry_enabled", True)
    monkeypatch.setattr(settings, "proxy_retry_max_attempts", 3)
    monkeypatch.setattr(settings, "proxy_retry_base_delay_seconds", 0.1)
    monkeypatch.setattr(settings, "proxy_retry_max_delay_seconds", 0.2)
    delays = resilience.backoff_delays()
    assert len(delays) == 3
    assert all(0.0 <= d <= 0.2 for d in delays)


def test_backoff_disabled_is_empty(monkeypatch):
    monkeypatch.setattr(settings, "proxy_retry_enabled", False)
    assert resilience.backoff_delays() == []


def test_retry_after_parsing(monkeypatch):
    monkeypatch.setattr(settings, "proxy_retry_max_delay_seconds", 5.0)
    assert resilience.retry_after_seconds("2", default=0.5) == 2.0
    assert resilience.retry_after_seconds("999", default=0.5) == 5.0  # capped
    assert resilience.retry_after_seconds(None, default=0.5) == 0.5
    assert resilience.retry_after_seconds("garbage", default=0.5) == 0.5


def test_fallback_model_resolution(monkeypatch):
    monkeypatch.setattr(settings, "proxy_fallback_enabled", True)
    monkeypatch.setattr(settings, "proxy_fallback_models", {"proj": "m2"})
    assert resilience.fallback_model("proj", "m1") == "m2"
    assert resilience.fallback_model("proj", "m2") is None  # never the model we failed on
    assert resilience.fallback_model("other", "m1") is None
    monkeypatch.setattr(settings, "proxy_fallback_enabled", False)
    assert resilience.fallback_model("proj", "m1") is None


# --- non-streaming retries -----------------------------------------------------


@pytest.mark.anyio
async def test_nonstream_retries_then_succeeds(async_client, async_provision, monkeypatch):
    ws = await async_provision(sub="auth0|r1", email="r1@example.com")
    _configure_key(monkeypatch, ws["project_id"])
    _fast_retries(monkeypatch)
    calls = {"n": 0}

    def handler(request):
        if request.url.path.endswith("/embeddings"):
            return _embeddings(request)
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, json={"error": "overloaded"})
        return httpx.Response(200, json=NONSTREAM)

    _install(monkeypatch, handler)
    res = await async_client.post("/v1/chat/completions", headers=_b(ws["api_key"]), json=_msg())
    assert res.status_code == 200
    assert res.json()["choices"][0]["message"]["content"] == "Hello world"
    assert calls["n"] == 2  # one retry after the 503


@pytest.mark.anyio
async def test_nonstream_retries_exhausted_relays_error(async_client, async_provision, monkeypatch):
    ws = await async_provision(sub="auth0|r2", email="r2@example.com")
    _configure_key(monkeypatch, ws["project_id"])
    _fast_retries(monkeypatch)
    monkeypatch.setattr(settings, "proxy_retry_max_attempts", 2)
    calls = {"n": 0}

    def handler(request):
        if request.url.path.endswith("/embeddings"):
            return _embeddings(request)
        calls["n"] += 1
        return httpx.Response(503, json={"error": "overloaded"})

    _install(monkeypatch, handler)
    res = await async_client.post("/v1/chat/completions", headers=_b(ws["api_key"]), json=_msg())
    assert res.status_code == 503
    assert calls["n"] == 3  # initial + 2 retries


@pytest.mark.anyio
async def test_nonstream_connect_error_retried(async_client, async_provision, monkeypatch):
    ws = await async_provision(sub="auth0|r3", email="r3@example.com")
    _configure_key(monkeypatch, ws["project_id"])
    _fast_retries(monkeypatch)
    calls = {"n": 0}

    def handler(request):
        if request.url.path.endswith("/embeddings"):
            return _embeddings(request)
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("upstream unreachable")
        return httpx.Response(200, json=NONSTREAM)

    _install(monkeypatch, handler)
    res = await async_client.post("/v1/chat/completions", headers=_b(ws["api_key"]), json=_msg())
    assert res.status_code == 200
    assert calls["n"] == 2


@pytest.mark.anyio
async def test_client_error_not_retried(async_client, async_provision, monkeypatch):
    ws = await async_provision(sub="auth0|r4", email="r4@example.com")
    _configure_key(monkeypatch, ws["project_id"])
    _fast_retries(monkeypatch)
    calls = {"n": 0}

    def handler(request):
        if request.url.path.endswith("/embeddings"):
            return _embeddings(request)
        calls["n"] += 1
        return httpx.Response(400, json={"error": "bad request"})

    _install(monkeypatch, handler)
    res = await async_client.post("/v1/chat/completions", headers=_b(ws["api_key"]), json=_msg())
    assert res.status_code == 400
    assert calls["n"] == 1  # a 4xx is the client's mistake: no retry


# --- streaming retries ---------------------------------------------------------


@pytest.mark.anyio
async def test_stream_retries_then_succeeds(async_client, async_provision, monkeypatch):
    ws = await async_provision(sub="auth0|r5", email="r5@example.com")
    _configure_key(monkeypatch, ws["project_id"])
    _fast_retries(monkeypatch)
    calls = {"n": 0}

    def handler(request):
        if request.url.path.endswith("/embeddings"):
            return _embeddings(request)
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, json={"error": "overloaded"})
        return httpx.Response(200, content=STREAM_BODY.encode(), headers={"content-type": "text/event-stream"})

    _install(monkeypatch, handler)
    res = await async_client.post("/v1/chat/completions", headers=_b(ws["api_key"]), json={**_msg(), "stream": True})
    assert res.status_code == 200
    assert "Hello" in res.text
    assert calls["n"] == 2


# --- fallback ------------------------------------------------------------------


@pytest.mark.anyio
async def test_fallback_serves_when_primary_fails(async_client, async_provision, async_db_session, monkeypatch):
    ws = await async_provision(sub="auth0|r6", email="r6@example.com")
    _configure_key(monkeypatch, ws["project_id"])
    _fast_retries(monkeypatch)
    monkeypatch.setattr(settings, "proxy_fallback_enabled", True)
    monkeypatch.setattr(settings, "proxy_fallback_models", {ws["project_id"]: FALLBACK})

    def handler(request):
        if request.url.path.endswith("/embeddings"):
            return _embeddings(request)
        body = json.loads(request.content)
        if body.get("model") == FALLBACK:
            return httpx.Response(200, json={**NONSTREAM, "model": FALLBACK})
        return httpx.Response(503, json={"error": "overloaded"})

    _install(monkeypatch, handler)
    res = await async_client.post("/v1/chat/completions", headers=_b(ws["api_key"]), json=_msg())
    assert res.status_code == 200
    assert res.headers.get("x-varsten-fallback") == FALLBACK

    decision = await async_db_session.scalar(
        select(RequestDecisionEvent).where(RequestDecisionEvent.project_id == ws["project_id"])
    )
    assert decision is not None
    assert decision.fallback_used is True
    assert decision.fallback_reason == "upstream_failure"
    # Reliability, not optimization: no savings claimed.
    assert not decision.optimization_applied


@pytest.mark.anyio
async def test_no_fallback_relays_error(async_client, async_provision, monkeypatch):
    ws = await async_provision(sub="auth0|r7", email="r7@example.com")
    _configure_key(monkeypatch, ws["project_id"])
    _fast_retries(monkeypatch)
    monkeypatch.setattr(settings, "proxy_fallback_models", {})  # none configured

    def handler(request):
        if request.url.path.endswith("/embeddings"):
            return _embeddings(request)
        return httpx.Response(503, json={"error": "overloaded"})

    _install(monkeypatch, handler)
    res = await async_client.post("/v1/chat/completions", headers=_b(ws["api_key"]), json=_msg())
    assert res.status_code == 503
