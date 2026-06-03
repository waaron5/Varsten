"""Phase 1 inline proxy: auth, key vaulting, streaming pass-through, cache
hit/miss, and metadata-only ledger capture. OpenAI is mocked via an httpx
MockTransport so no real key or network is needed."""
import json

import httpx
import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.models import ProxyCacheEntry, UsageEvent
from app.proxy import cache as proxy_cache
from app.proxy import router as proxy_router

CHAT = "gpt-4o-mini"

NONSTREAM_RESPONSE = {
    "id": "chatcmpl-mock",
    "object": "chat.completion",
    "model": CHAT,
    "choices": [
        {"index": 0, "message": {"role": "assistant", "content": "Hello world"}, "finish_reason": "stop"}
    ],
    "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
}

STREAM_BODY = (
    'data: {"id":"x","object":"chat.completion.chunk","model":"gpt-4o-mini","choices":[{"index":0,"delta":{"role":"assistant","content":"Hello"},"finish_reason":null}]}\n\n'
    'data: {"id":"x","object":"chat.completion.chunk","model":"gpt-4o-mini","choices":[{"index":0,"delta":{"content":" world"},"finish_reason":"stop"}]}\n\n'
    'data: {"id":"x","object":"chat.completion.chunk","model":"gpt-4o-mini","choices":[],"usage":{"prompt_tokens":10,"completion_tokens":2,"total_tokens":12}}\n\n'
    "data: [DONE]\n\n"
)


@pytest.fixture
def mock_openai(monkeypatch):
    """Replace the upstream OpenAI client with a counting MockTransport."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        payload = json.loads(request.content)
        if payload.get("stream"):
            return httpx.Response(
                200, content=STREAM_BODY.encode(), headers={"content-type": "text/event-stream"}
            )
        return httpx.Response(200, json=NONSTREAM_RESPONSE)

    real_async_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        return real_async_client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(proxy_router.httpx, "AsyncClient", factory)
    return calls


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
    assert mock_openai["n"] == 0


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
    assert mock_openai["n"] == 1

    events = db_session.scalars(
        select(UsageEvent).where(UsageEvent.project_id == ws["project_id"])
    ).all()
    assert len(events) == 1
    assert events[0].event_metadata["cache"] == "miss"
    assert events[0].input_tokens == 10 and events[0].output_tokens == 2
    # The miss was cached.
    cached = db_session.scalar(
        select(func.count()).select_from(ProxyCacheEntry).where(
            ProxyCacheEntry.project_id == ws["project_id"]
        )
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
    assert mock_openai["n"] == 1

    events = db_session.scalars(
        select(UsageEvent).where(UsageEvent.project_id == ws["project_id"])
    ).all()
    assert len(events) == 1
    assert events[0].output_tokens == 2


def test_cache_hit_served_without_upstream(client, db_session, provision, mock_openai, monkeypatch):
    ws = provision(sub="auth0|p", email="p@example.com")
    _configure_key(monkeypatch, ws["project_id"])
    body = {"model": CHAT, "messages": [{"role": "user", "content": "hi"}]}

    first = client.post("/v1/chat/completions", headers=_b(ws["api_key"]), json=body)
    assert first.status_code == 200
    assert mock_openai["n"] == 1

    second = client.post("/v1/chat/completions", headers=_b(ws["api_key"]), json=body)
    assert second.status_code == 200
    assert second.json()["choices"][0]["message"]["content"] == "Hello world"
    # No second upstream call: served from cache.
    assert mock_openai["n"] == 1

    # Two ledger rows: one miss (real cost) and one hit ($0, naive cost recorded).
    events = db_session.scalars(
        select(UsageEvent)
        .where(UsageEvent.project_id == ws["project_id"])
        .order_by(UsageEvent.received_at.asc())
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
    assert mock_openai["n"] == 2
    cached = db_session.scalar(
        select(func.count()).select_from(ProxyCacheEntry).where(
            ProxyCacheEntry.project_id == ws["project_id"]
        )
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
    assert mock_openai["n"] == 2  # bypassed, never served from cache


def test_toggle_is_tenant_scoped(client, provision):
    ws = provision(sub="auth0|a", email="a@example.com")
    provision(sub="auth0|b", email="b@example.com")

    # Unauthenticated and cross-tenant are both refused.
    assert client.patch(
        f"/v1/projects/{ws['project_id']}/proxy-config", json={"bypass_enabled": True}
    ).status_code == 401
    assert client.patch(
        f"/v1/projects/{ws['project_id']}/proxy-config",
        headers=_b("auth0|b"),
        json={"bypass_enabled": True},
    ).status_code == 403


def test_fail_open_when_cache_lookup_breaks(client, provision, mock_openai, monkeypatch):
    ws = provision(sub="auth0|p", email="p@example.com")
    _configure_key(monkeypatch, ws["project_id"])

    def boom(*args, **kwargs):
        raise RuntimeError("cache backend down")

    monkeypatch.setattr(proxy_cache, "get_cached", boom)

    body = {"model": CHAT, "messages": [{"role": "user", "content": "hi"}]}
    res = client.post("/v1/chat/completions", headers=_b(ws["api_key"]), json=body)

    # A broken cache must never break the client's call: it forwards anyway.
    assert res.status_code == 200
    assert res.json()["choices"][0]["message"]["content"] == "Hello world"
    assert mock_openai["n"] == 1
