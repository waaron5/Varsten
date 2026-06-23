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


class _FakeRedis:
    """Minimal stand-in for redis.Redis: register_script runs the INCR semantics
    against an in-process dict so the backend logic is testable without a server."""

    def __init__(self) -> None:
        self.store: dict[str, int] = {}
        self.expired: list[str] = []

    def register_script(self, _lua: str):
        def run(keys=None, args=None):
            redis_key = keys[0]
            self.store[redis_key] = self.store.get(redis_key, 0) + 1
            if self.store[redis_key] == 1:
                self.expired.append(redis_key)  # records the EXPIRE-on-first-hit branch
            return self.store[redis_key]

        return run

    def scan_iter(self, _pattern: str):
        return list(self.store.keys())

    def delete(self, redis_key: str) -> None:
        self.store.pop(redis_key, None)


class _BoomRedis:
    """A client whose every operation fails, to exercise fail-open."""

    def register_script(self, _lua: str):
        raise ConnectionError("redis down")

    def scan_iter(self, _pattern: str):
        raise ConnectionError("redis down")


def test_redis_limiter_allows_then_blocks_within_window():
    limiter = ratelimit.RedisFixedWindow(_FakeRedis())
    assert limiter.allow("k", 2) is True
    assert limiter.allow("k", 2) is True
    assert limiter.allow("k", 2) is False  # third in the same window is blocked
    assert limiter.allow("other", 2) is True  # separate key has its own counter


def test_redis_limiter_sets_ttl_only_on_first_hit():
    client = _FakeRedis()
    limiter = ratelimit.RedisFixedWindow(client)
    limiter.allow("k", 5)
    limiter.allow("k", 5)
    limiter.allow("k", 5)
    # EXPIRE is set exactly once per window key (the count==1 branch).
    assert len(client.expired) == 1


def test_redis_limiter_zero_limit_is_unlimited():
    limiter = ratelimit.RedisFixedWindow(_FakeRedis())
    assert all(limiter.allow("z", 0) for _ in range(10))


def test_redis_limiter_fails_open_when_redis_errors():
    limiter = ratelimit.RedisFixedWindow(_BoomRedis())
    # An unreachable store must allow traffic, never block it.
    assert limiter.allow("k", 1) is True
    assert limiter.allow("k", 1) is True


def test_build_limiter_uses_redis_when_configured(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(settings, "rate_limit_backend", "redis")
    monkeypatch.setattr(settings, "rate_limit_redis_url", "redis://localhost:6379/0")
    monkeypatch.setattr(ratelimit, "_build_redis_client", lambda: fake)
    limiter = ratelimit.build_limiter()
    assert isinstance(limiter, ratelimit.RedisFixedWindow)


def test_build_limiter_falls_back_to_memory_without_url(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_backend", "redis")
    monkeypatch.setattr(settings, "rate_limit_redis_url", "")
    assert isinstance(ratelimit.build_limiter(), ratelimit.InMemoryFixedWindow)


def test_build_limiter_falls_back_to_memory_on_client_error(monkeypatch):
    def boom():
        raise RuntimeError("no redis package")

    monkeypatch.setattr(settings, "rate_limit_backend", "redis")
    monkeypatch.setattr(settings, "rate_limit_redis_url", "redis://localhost:6379/0")
    monkeypatch.setattr(ratelimit, "_build_redis_client", boom)
    assert isinstance(ratelimit.build_limiter(), ratelimit.InMemoryFixedWindow)


def test_module_allow_delegates_to_active_limiter(monkeypatch):
    # The public allow() routes through whatever limiter is installed; swapping in a
    # redis-backed one is transparent to callers.
    limiter = ratelimit.RedisFixedWindow(_FakeRedis())
    monkeypatch.setattr(ratelimit, "_limiter", limiter)
    assert ratelimit.allow("k", 1) is True
    assert ratelimit.allow("k", 1) is False


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
