"""Phase 2 fail-open server contract.

These lock the server side the fallback SDK depends on:

- X-Varsten-Origin on every response (the keystone: varsten vs provider).
- The structured error schema (origin + stable code) for Varsten-originated failures.
- A relayed provider error keeps origin=provider so the SDK never falls back on a
  provider outage (which would double-bill and hit the same sick provider).
- /v1/health liveness with no auth and no DB.
- The fallback telemetry endpoint: authed, content-rejecting, best-effort.
- The in-process API-key cache that keeps a known key serving through a DB blip.

Frozen in docs/design/SDK_FAILOPEN_DESIGN_FREEZE.md.
"""

from typing import Any

import httpx
import pytest
from fastapi import HTTPException

from app.api import deps
from app.core.config import settings
from app.proxy import circuit, http_client, origin

CHAT = "gpt-4o-mini"

NONSTREAM_RESPONSE = {
    "id": "chatcmpl-mock",
    "object": "chat.completion",
    "model": CHAT,
    "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hello world"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
}


@pytest.fixture(autouse=True)
def reset_circuit():
    circuit.reset_all()
    yield
    circuit.reset_all()


@pytest.fixture
def mock_openai(monkeypatch):
    """Healthy upstream: completions + embeddings always succeed."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/embeddings"):
            return httpx.Response(200, json={"data": [{"embedding": [0.0] * 1536}]})
        return httpx.Response(200, json=NONSTREAM_RESPONSE)

    monkeypatch.setattr(http_client, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))


@pytest.fixture
def controllable_openai(monkeypatch):
    """Upstream whose completion behaviour flips: ok | fail_503 | fail_400 | raise."""
    state: dict[str, Any] = {"mode": "ok", "completions": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/embeddings"):
            return httpx.Response(200, json={"data": [{"embedding": [0.0] * 1536}]})
        state["completions"] += 1
        if state["mode"] == "raise":
            raise httpx.ConnectError("upstream unreachable")
        if state["mode"] == "fail_503":
            return httpx.Response(503, json={"error": "overloaded"})
        if state["mode"] == "fail_400":
            return httpx.Response(400, json={"error": "bad request"})
        return httpx.Response(200, json=NONSTREAM_RESPONSE)

    monkeypatch.setattr(http_client, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return state


def _b(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _body(content="hi"):
    return {"model": CHAT, "messages": [{"role": "user", "content": content}]}


def _configure_key(monkeypatch, project_id: str):
    monkeypatch.setattr(settings, "proxy_openai_keys", {project_id: "sk-test"})


# --- origin on the happy path -------------------------------------------------


@pytest.mark.anyio
async def test_success_is_tagged_provider_origin(async_client, async_provision, mock_openai, monkeypatch):
    ws = await async_provision(sub="auth0|o", email="o@example.com")
    _configure_key(monkeypatch, ws["project_id"])
    res = await async_client.post("/v1/chat/completions", headers=_b(ws["api_key"]), json=_body())
    assert res.status_code == 200
    assert res.headers[origin.ORIGIN_HEADER] == origin.ORIGIN_PROVIDER


@pytest.mark.anyio
async def test_cache_hit_is_tagged_varsten_origin(async_client, async_provision, mock_openai, monkeypatch):
    ws = await async_provision(sub="auth0|o", email="o@example.com")
    _configure_key(monkeypatch, ws["project_id"])
    await async_client.post("/v1/chat/completions", headers=_b(ws["api_key"]), json=_body())
    hit = await async_client.post("/v1/chat/completions", headers=_b(ws["api_key"]), json=_body())
    assert hit.status_code == 200
    assert hit.headers["x-varsten-cache"] == "hit"
    assert hit.headers[origin.ORIGIN_HEADER] == origin.ORIGIN_VARSTEN


# --- Varsten-originated failures (fallback-eligible) --------------------------


@pytest.mark.anyio
async def test_no_provider_key_is_varsten_origin(async_client, async_provision, mock_openai, monkeypatch):
    ws = await async_provision(sub="auth0|o", email="o@example.com")
    monkeypatch.setattr(settings, "proxy_openai_keys", {})
    res = await async_client.post("/v1/chat/completions", headers=_b(ws["api_key"]), json=_body())
    assert res.status_code == 502
    assert res.headers[origin.ORIGIN_HEADER] == origin.ORIGIN_VARSTEN
    assert res.json()["error"]["code"] == origin.CODE_NO_PROVIDER_KEY


@pytest.mark.anyio
async def test_upstream_unreachable_is_varsten_origin(async_client, async_provision, controllable_openai, monkeypatch):
    ws = await async_provision(sub="auth0|o", email="o@example.com")
    _configure_key(monkeypatch, ws["project_id"])
    controllable_openai["mode"] = "raise"
    res = await async_client.post("/v1/chat/completions", headers=_b(ws["api_key"]), json=_body())
    assert res.status_code == 502
    assert res.headers[origin.ORIGIN_HEADER] == origin.ORIGIN_VARSTEN
    assert res.json()["error"]["code"] == origin.CODE_UPSTREAM_UNREACHABLE


@pytest.mark.anyio
async def test_circuit_open_is_varsten_origin(async_client, async_provision, controllable_openai, monkeypatch):
    ws = await async_provision(sub="auth0|o", email="o@example.com")
    _configure_key(monkeypatch, ws["project_id"])
    monkeypatch.setattr(settings, "circuit_breaker_fail_threshold", 1)
    controllable_openai["mode"] = "raise"
    # First request trips the breaker (returns a 502 upstream error).
    first = await async_client.post("/v1/chat/completions", headers=_b(ws["api_key"]), json=_body("a"))
    assert first.status_code == 502
    # Next request short-circuits on the open breaker.
    second = await async_client.post("/v1/chat/completions", headers=_b(ws["api_key"]), json=_body("b"))
    assert second.status_code == 503
    assert second.headers[origin.ORIGIN_HEADER] == origin.ORIGIN_VARSTEN
    assert second.json()["error"]["code"] == origin.CODE_CIRCUIT_OPEN


@pytest.mark.anyio
async def test_rate_limited_is_varsten_origin(async_client, async_provision, mock_openai, monkeypatch):
    ws = await async_provision(sub="auth0|o", email="o@example.com")
    _configure_key(monkeypatch, ws["project_id"])
    monkeypatch.setattr(settings, "proxy_rate_limit_per_minute", 1)
    await async_client.post("/v1/chat/completions", headers=_b(ws["api_key"]), json=_body("a"))
    limited = await async_client.post("/v1/chat/completions", headers=_b(ws["api_key"]), json=_body("b"))
    assert limited.status_code == 429
    assert limited.headers[origin.ORIGIN_HEADER] == origin.ORIGIN_VARSTEN
    assert limited.json()["error"]["code"] == origin.CODE_RATE_LIMITED


# --- relayed provider errors (NOT fallback-eligible) -------------------------


@pytest.mark.anyio
async def test_provider_400_is_relayed_provider_origin(async_client, async_provision, controllable_openai, monkeypatch):
    ws = await async_provision(sub="auth0|o", email="o@example.com")
    _configure_key(monkeypatch, ws["project_id"])
    controllable_openai["mode"] = "fail_400"
    res = await async_client.post("/v1/chat/completions", headers=_b(ws["api_key"]), json=_body())
    assert res.status_code == 400
    assert res.headers[origin.ORIGIN_HEADER] == origin.ORIGIN_PROVIDER


@pytest.mark.anyio
async def test_provider_503_is_relayed_provider_origin(async_client, async_provision, controllable_openai, monkeypatch):
    # The critical case: a provider 5xx must say provider, or the SDK's
    # "header-less 5xx -> fall back" rule would double-call a sick provider.
    ws = await async_provision(sub="auth0|o", email="o@example.com")
    _configure_key(monkeypatch, ws["project_id"])
    controllable_openai["mode"] = "fail_503"
    res = await async_client.post("/v1/chat/completions", headers=_b(ws["api_key"]), json=_body())
    assert res.status_code == 503
    assert res.headers[origin.ORIGIN_HEADER] == origin.ORIGIN_PROVIDER


# --- health -------------------------------------------------------------------


@pytest.mark.anyio
async def test_proxy_health_is_unauthenticated_and_dbless(async_client):
    res = await async_client.get("/v1/health")
    assert res.status_code == 200
    assert res.json() == {"ok": True}


# --- telemetry ----------------------------------------------------------------


@pytest.mark.anyio
async def test_fallback_telemetry_accepts_allowlisted_marker(async_client, async_provision):
    ws = await async_provision(sub="auth0|o", email="o@example.com")
    payload = {"events": [{"reason_code": "connect_timeout", "phase": "pre-request", "model": CHAT, "latency_ms": 12}]}
    res = await async_client.post("/v1/telemetry/fallback", headers=_b(ws["api_key"]), json=payload)
    assert res.status_code == 202
    assert res.json() == {"accepted": 1}


@pytest.mark.anyio
async def test_fallback_telemetry_rejects_content(async_client, async_provision):
    ws = await async_provision(sub="auth0|o", email="o@example.com")
    # A client that tries to smuggle prompt content gets a 422, never silent storage.
    payload = {"events": [{"reason_code": "x", "phase": "pre-request", "messages": [{"role": "user", "content": "secret"}]}]}
    res = await async_client.post("/v1/telemetry/fallback", headers=_b(ws["api_key"]), json=payload)
    assert res.status_code == 422


@pytest.mark.anyio
async def test_fallback_telemetry_requires_auth(async_client):
    res = await async_client.post("/v1/telemetry/fallback", json={"events": []})
    assert res.status_code == 401


# --- in-process API-key cache (DB-blip fail-open) ----------------------------


class _BrokenDB:
    """A DB session whose every call raises, to simulate Postgres being down."""

    async def scalar(self, *a, **k):
        raise RuntimeError("db down")

    async def get(self, *a, **k):
        raise RuntimeError("db down")

    async def commit(self):
        raise RuntimeError("db down")


@pytest.mark.anyio
async def test_known_key_served_from_cache_on_db_error(async_db_session, async_provision):
    ws = await async_provision(sub="auth0|o", email="o@example.com")
    token = ws["api_key"]
    # A real resolve seeds the cache.
    ctx = await deps._api_key_context_async(token, async_db_session)
    assert str(ctx.project.id) == ws["project_id"]
    # The database now errors; the known key still resolves (degraded).
    ctx2 = await deps._api_key_context_async(token, _BrokenDB())
    assert str(ctx2.project.id) == ws["project_id"]


@pytest.mark.anyio
async def test_unknown_key_fails_closed_on_db_error():
    # An unknown key was never cached, so a DB error does not become a forward.
    with pytest.raises(RuntimeError):
        await deps._api_key_context_async("vk_never_seen_unknown", _BrokenDB())


@pytest.mark.anyio
async def test_revoked_key_fails_closed_not_cached(async_db_session, async_provision, monkeypatch):
    from datetime import UTC, datetime

    from sqlalchemy import select

    from app.models import ApiKey

    ws = await async_provision(sub="auth0|o", email="o@example.com")
    token = ws["api_key"]
    # Seed the cache with a valid resolve, then revoke the key.
    await deps._api_key_context_async(token, async_db_session)
    api_key = await async_db_session.scalar(select(ApiKey).where(ApiKey.id == ws["api_key_id"]))
    api_key.revoked_at = datetime.now(UTC)
    await async_db_session.flush()
    # A healthy DB now rejects it (401) even though a cache entry exists: auth
    # rejections fail closed and never serve cache.
    with pytest.raises(HTTPException) as ei:
        await deps._api_key_context_async(token, async_db_session)
    assert ei.value.status_code == 401


# --- idempotency key propagation (Phase 3) ----------------------------------


@pytest.fixture
def capturing_openai(monkeypatch):
    """Mock upstream that records the Idempotency-Key it receives."""
    seen: dict[str, str | None] = {"idempotency_key": "UNSET"}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/embeddings"):
            return httpx.Response(200, json={"data": [{"embedding": [0.0] * 1536}]})
        seen["idempotency_key"] = request.headers.get("idempotency-key")
        return httpx.Response(200, json=NONSTREAM_RESPONSE)

    monkeypatch.setattr(http_client, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return seen


@pytest.mark.anyio
async def test_idempotency_key_propagated_on_verbatim_forward(async_client, async_provision, capturing_openai, monkeypatch):
    ws = await async_provision(sub="auth0|o", email="o@example.com")
    _configure_key(monkeypatch, ws["project_id"])
    headers = {**_b(ws["api_key"]), "Idempotency-Key": "varsten-abc123"}
    res = await async_client.post("/v1/chat/completions", headers=headers, json=_body())
    assert res.status_code == 200
    # The proxy forwarded the request verbatim, so the client's key reaches upstream
    # and the provider can dedupe a direct SDK fallback retry against it.
    assert capturing_openai["idempotency_key"] == "varsten-abc123"


@pytest.mark.anyio
async def test_no_idempotency_header_means_none_upstream(async_client, async_provision, capturing_openai, monkeypatch):
    ws = await async_provision(sub="auth0|o", email="o@example.com")
    _configure_key(monkeypatch, ws["project_id"])
    res = await async_client.post("/v1/chat/completions", headers=_b(ws["api_key"]), json=_body())
    assert res.status_code == 200
    assert capturing_openai["idempotency_key"] is None
