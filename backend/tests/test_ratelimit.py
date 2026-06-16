"""Rate limiting: the in-memory limiter and proxy enforcement (429 over the cap)."""

import json

import httpx
import pytest

from app.core import ratelimit
from app.core.config import settings
from app.proxy import circuit, http_client

CHAT = "gpt-4o-mini"


def test_limiter_allows_then_blocks():
    ratelimit.reset_all()
    assert ratelimit.allow("k", 2) is True
    assert ratelimit.allow("k", 2) is True
    assert ratelimit.allow("k", 2) is False  # third in the window is blocked
    assert ratelimit.allow("other", 2) is True  # separate key has its own window


def test_limiter_zero_limit_is_unlimited():
    ratelimit.reset_all()
    assert all(ratelimit.allow("z", 0) for _ in range(10))


@pytest.fixture(autouse=True)
def _reset_circuit():
    circuit.reset_all()
    yield
    circuit.reset_all()


@pytest.fixture
def mock_openai(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "x",
                "object": "chat.completion",
                "model": CHAT,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
            },
        )

    monkeypatch.setattr(http_client, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))


@pytest.mark.anyio
async def test_proxy_rate_limited(async_client, async_provision, monkeypatch, mock_openai):
    p = await async_provision()
    monkeypatch.setattr(settings, "proxy_openai_keys", {p["project_id"]: "sk-test"})
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "proxy_rate_limit_per_minute", 2)
    ratelimit.reset_all()

    body = {"model": CHAT, "messages": [{"role": "user", "content": "hi"}]}
    headers = {"Authorization": f"Bearer {p['api_key']}"}

    r1 = await async_client.post("/v1/chat/completions", headers=headers, json=body)
    r2 = await async_client.post("/v1/chat/completions", headers=headers, json=body)
    r3 = await async_client.post("/v1/chat/completions", headers=headers, json=body)

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r3.status_code == 429
    assert r3.headers.get("Retry-After") == "60"
    assert json.loads(r3.content)["error"]["type"] == "varsten_rate_limited"
