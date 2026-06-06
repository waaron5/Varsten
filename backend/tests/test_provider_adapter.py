"""Proof that the provider adapter seam is real: a brand-new provider can be added
with a registry entry alone, and the proxy router drives it unchanged.

The fake "echo" provider below has its OWN wire format (different request and
response shapes from OpenAI). It is registered, selected via the normal
proxy_default_provider setting, and a full request is driven through the real
proxy router. The client still receives an OpenAI-shaped completion (the drop-in
contract), the ledger records the fake provider and its tokens, and no router code
special-cases it. That is the whole guarantee of the seam.
"""

import json

import httpx
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models import UsageEvent
from app.proxy import circuit, providers
from app.proxy import router as proxy_router
from app.proxy.providers.base import LLMAdapter, StreamTranslator
from app.proxy.providers.canonical import CanonicalCompletion, CanonicalUsage

# --- a fake provider with a non-OpenAI wire format ----------------------------


class _EchoStreamTranslator(StreamTranslator):
    """Echo streams newline-delimited JSON deltas of shape {"piece": "..."} and a
    final {"done": true, "in": n, "out": m}. The translator turns each into OpenAI
    SSE for the client and assembles the canonical completion."""

    def __init__(self) -> None:
        self._buf = bytearray()
        self._parts: list[str] = []
        self._in = 0
        self._out = 0

    def push(self, upstream_chunk: bytes):
        self._buf.extend(upstream_chunk)
        for line in upstream_chunk.decode().splitlines():
            line = line.strip()
            if not line:
                continue
            ev = json.loads(line)
            if ev.get("piece"):
                self._parts.append(ev["piece"])
                chunk = {
                    "object": "chat.completion.chunk",
                    "model": "echo-1",
                    "choices": [{"index": 0, "delta": {"content": ev["piece"]}, "finish_reason": None}],
                }
                yield f"data: {json.dumps(chunk)}\n\n".encode()
            if ev.get("done"):
                self._in = ev.get("in", 0)
                self._out = ev.get("out", 0)
                last = {
                    "object": "chat.completion.chunk",
                    "model": "echo-1",
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                }
                yield f"data: {json.dumps(last)}\n\n".encode()
                yield b"data: [DONE]\n\n"

    def finish(self) -> CanonicalCompletion:
        return CanonicalCompletion(
            model="echo-1",
            content="".join(self._parts),
            finish_reason="stop",
            usage=CanonicalUsage(input_tokens=self._in, output_tokens=self._out),
        )


class EchoAdapter(LLMAdapter):
    """A minimal non-OpenAI provider. Native request shape {"prompt": ...}; native
    response shape {"text": ..., "tokens": {"in": n, "out": m}}."""

    provider = "echo"

    def endpoint(self) -> str:
        return "http://echo.test/generate"

    def headers(self, api_key: str) -> dict[str, str]:
        return {"X-Echo-Key": api_key}

    def prepare_request(self, body: dict, *, model: str, stream: bool) -> dict:
        prompt = " ".join(m.get("content", "") for m in body.get("messages", []))
        return {"prompt": prompt, "model": model, "stream": stream}

    def parse_completion(self, raw: dict) -> CanonicalCompletion:
        tokens = raw.get("tokens") or {}
        return CanonicalCompletion(
            model="echo-1",
            content=raw.get("text", ""),
            finish_reason="stop",
            usage=CanonicalUsage(input_tokens=tokens.get("in", 0), output_tokens=tokens.get("out", 0)),
        )

    def stream_translator(self) -> StreamTranslator:
        return _EchoStreamTranslator()


@pytest.fixture(autouse=True)
def reset_circuit():
    circuit.reset_all()
    yield
    circuit.reset_all()


@pytest.fixture
def echo_provider(monkeypatch):
    """Register the echo provider and make it the default. Exact-hash cache off so
    each call forwards to the (mocked) echo upstream."""
    providers.register(EchoAdapter())
    monkeypatch.setattr(settings, "proxy_default_provider", "echo")
    monkeypatch.setattr(settings, "proxy_cache_enabled", False)
    yield
    providers._REGISTRY.pop("echo", None)


def _mock_echo_upstream(monkeypatch, *, stream: bool):
    def handler(request: httpx.Request) -> httpx.Response:
        # The router must have sent the echo NATIVE wire shape, not OpenAI's.
        sent = json.loads(request.content)
        assert "prompt" in sent and "messages" not in sent
        assert request.headers.get("X-Echo-Key") == "sk-echo"
        if stream:
            body = '{"piece": "hello "}\n{"piece": "world"}\n{"done": true, "in": 5, "out": 2}\n'
            return httpx.Response(200, content=body.encode(), headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json={"text": "hello world", "tokens": {"in": 5, "out": 2}})

    real = httpx.AsyncClient
    monkeypatch.setattr(proxy_router.httpx, "AsyncClient", lambda *a, **k: real(transport=httpx.MockTransport(handler)))


def _b(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_new_provider_nonstream_needs_zero_router_changes(client, db_session, provision, echo_provider, monkeypatch):
    ws = provision(sub="auth0|echo", email="echo@example.com")
    monkeypatch.setattr(settings, "proxy_openai_keys", {ws["project_id"]: "sk-echo"})
    _mock_echo_upstream(monkeypatch, stream=False)

    res = client.post(
        "/v1/chat/completions",
        headers=_b(ws["api_key"]),
        json={"model": "echo-1", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert res.status_code == 200
    # The client gets the OpenAI dialect back even though the upstream was not OpenAI.
    msg = res.json()["choices"][0]["message"]
    assert msg["role"] == "assistant" and msg["content"] == "hello world"

    # The ledger recorded the fake provider and its tokens via the same code path.
    event = db_session.scalar(select(UsageEvent).where(UsageEvent.project_id == ws["project_id"]))
    assert event.provider == "echo"
    assert event.input_tokens == 5 and event.output_tokens == 2


def test_new_provider_stream_translates_to_openai_sse(client, db_session, provision, echo_provider, monkeypatch):
    ws = provision(sub="auth0|echo", email="echo@example.com")
    monkeypatch.setattr(settings, "proxy_openai_keys", {ws["project_id"]: "sk-echo"})
    _mock_echo_upstream(monkeypatch, stream=True)

    res = client.post(
        "/v1/chat/completions",
        headers=_b(ws["api_key"]),
        json={"model": "echo-1", "messages": [{"role": "user", "content": "hi"}], "stream": True},
    )
    assert res.status_code == 200
    # Echo's native newline-JSON stream was translated to OpenAI SSE for the client.
    assert "data: " in res.text and "[DONE]" in res.text
    events = [
        json.loads(line[len("data:") :].strip())
        for line in res.text.splitlines()
        if line.startswith("data:") and "[DONE]" not in line
    ]
    content = "".join(e["choices"][0]["delta"].get("content", "") for e in events)
    assert content == "hello world"

    event = db_session.scalar(select(UsageEvent).where(UsageEvent.project_id == ws["project_id"]))
    assert event.provider == "echo" and event.output_tokens == 2
