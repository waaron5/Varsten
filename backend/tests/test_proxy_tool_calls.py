"""Tool-call fidelity through the proxy assembly, cache, and serialization layer.

The target ICP is agent/tool-heavy traffic, so a tool-calling completion must
survive streaming reassembly, exact-hash caching, and being served back over both
the JSON and SSE paths without losing its tool_calls. These tests pin that
round-trip. Pure-function tests need no DB; the end-to-end tests drive the real
proxy with a MockTransport upstream.
"""

import json

import httpx
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models import ProxyCacheEntry, UsageEvent
from app.proxy import circuit
from app.proxy import router as proxy_router
from app.proxy.providers import canonical
from app.proxy.providers import openai as openai_ops


@pytest.fixture(autouse=True)
def reset_circuit():
    circuit.reset_all()
    yield
    circuit.reset_all()


# A realistic tool-call stream: the first fragment carries id/type/name, later
# fragments append argument-string pieces, then a tool_calls finish and a usage
# chunk. Arguments concatenate to {"city":"Paris"}.
TOOL_STREAM_BODY = (
    'data: {"id":"x","object":"chat.completion.chunk","model":"gpt-4o","choices":[{"index":0,'
    '"delta":{"role":"assistant","content":null,"tool_calls":[{"index":0,"id":"call_1","type":"function",'
    '"function":{"name":"get_weather","arguments":""}}]},"finish_reason":null}]}\n\n'
    'data: {"id":"x","object":"chat.completion.chunk","model":"gpt-4o","choices":[{"index":0,'
    '"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\\"city\\":"}}]},"finish_reason":null}]}\n\n'
    'data: {"id":"x","object":"chat.completion.chunk","model":"gpt-4o","choices":[{"index":0,'
    '"delta":{"tool_calls":[{"index":0,"function":{"arguments":"\\"Paris\\"}"}}]},"finish_reason":null}]}\n\n'
    'data: {"id":"x","object":"chat.completion.chunk","model":"gpt-4o","choices":[{"index":0,'
    '"delta":{},"finish_reason":"tool_calls"}]}\n\n'
    'data: {"id":"x","object":"chat.completion.chunk","model":"gpt-4o","choices":[],'
    '"usage":{"prompt_tokens":20,"completion_tokens":8,"total_tokens":28}}\n\n'
    "data: [DONE]\n\n"
)

TOOL_NONSTREAM_RESPONSE = {
    "id": "chatcmpl-tool",
    "object": "chat.completion",
    "model": "gpt-4o",
    "choices": [
        {
            "index": 0,
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "get_weather", "arguments": '{"city":"Paris"}'},
                    }
                ],
            },
            "finish_reason": "tool_calls",
        }
    ],
    "usage": {"prompt_tokens": 20, "completion_tokens": 8, "total_tokens": 28},
}


# --- pure assembly / serialization --------------------------------------------


def test_assemble_stream_reconstructs_fragmented_tool_call():
    events = openai_ops.parse_sse_events(TOOL_STREAM_BODY)
    assembled = openai_ops.assemble_stream(events)

    assert assembled.content == ""
    assert assembled.finish_reason == "tool_calls"
    assert assembled.tool_calls is not None
    assert len(assembled.tool_calls) == 1
    call = assembled.tool_calls[0]
    assert call["id"] == "call_1"
    assert call["type"] == "function"
    assert call["function"]["name"] == "get_weather"
    # The fragmented argument string is concatenated back to valid JSON.
    assert json.loads(call["function"]["arguments"]) == {"city": "Paris"}
    # Usage is carried in canonical form.
    assert assembled.usage.input_tokens == 20 and assembled.usage.output_tokens == 8


def test_assemble_stream_reconstructs_parallel_tool_calls():
    body = (
        'data: {"choices":[{"index":0,"delta":{"tool_calls":['
        '{"index":0,"id":"a","type":"function","function":{"name":"f0","arguments":"{}"}},'
        '{"index":1,"id":"b","type":"function","function":{"name":"f1","arguments":"{}"}}'
        ']},"finish_reason":null}]}\n\n'
        'data: {"choices":[{"index":0,"delta":{},"finish_reason":"tool_calls"}]}\n\n'
        "data: [DONE]\n\n"
    )
    assembled = openai_ops.assemble_stream(openai_ops.parse_sse_events(body))
    calls = assembled.tool_calls
    assert [c["id"] for c in calls] == ["a", "b"]  # ordered by index
    assert [c["function"]["name"] for c in calls] == ["f0", "f1"]


def test_assemble_stream_handles_mixed_content_and_tool_calls():
    body = (
        'data: {"model":"gpt-4o","choices":[{"index":0,"delta":{"content":"Let me check. "},"finish_reason":null}]}\n\n'
        'data: {"choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"id":"c","type":"function",'
        '"function":{"name":"lookup","arguments":"{}"}}]},"finish_reason":"tool_calls"}]}\n\n'
        "data: [DONE]\n\n"
    )
    assembled = openai_ops.assemble_stream(openai_ops.parse_sse_events(body))
    assert assembled.content == "Let me check. "
    assert assembled.tool_calls[0]["function"]["name"] == "lookup"


def test_assemble_stream_plain_content_has_no_tool_calls():
    body = (
        'data: {"model":"gpt-4o","choices":[{"index":0,"delta":{"content":"hi"},"finish_reason":"stop"}]}\n\n'
        "data: [DONE]\n\n"
    )
    assembled = openai_ops.assemble_stream(openai_ops.parse_sse_events(body))
    assert assembled.content == "hi"
    assert assembled.tool_calls is None


def test_completion_payload_carries_tool_calls_and_null_content():
    assembled = openai_ops.assemble_stream(openai_ops.parse_sse_events(TOOL_STREAM_BODY))
    obj = canonical.completion_payload(assembled)
    msg = obj["choices"][0]["message"]
    assert msg["content"] is None
    assert msg["tool_calls"][0]["function"]["name"] == "get_weather"
    assert obj["choices"][0]["finish_reason"] == "tool_calls"


def test_to_openai_sse_emits_tool_calls_and_preserves_finish_reason():
    chunks = list(canonical.to_openai_sse(TOOL_NONSTREAM_RESPONSE))
    events = openai_ops.parse_sse_events(b"".join(chunks).decode())
    # First event carries the tool_calls delta.
    delta = events[0]["choices"][0]["delta"]
    assert delta["tool_calls"][0]["function"]["name"] == "get_weather"
    assert "content" not in delta  # tool-only response: no content key
    # Final event carries the stored finish_reason, not a hardcoded "stop".
    assert events[-1]["choices"][0]["finish_reason"] == "tool_calls"


def test_full_round_trip_stream_to_cache_to_sse_preserves_tool_calls():
    assembled = openai_ops.assemble_stream(openai_ops.parse_sse_events(TOOL_STREAM_BODY))
    cached = canonical.completion_payload(assembled)
    replayed = openai_ops.parse_sse_events(b"".join(canonical.to_openai_sse(cached)).decode())
    call = replayed[0]["choices"][0]["delta"]["tool_calls"][0]
    assert json.loads(call["function"]["arguments"]) == {"city": "Paris"}


# --- end-to-end through the proxy (exact-hash cache, the Day One posture) ------


@pytest.fixture
def mock_tool_openai(monkeypatch):
    """Upstream that returns a tool-call completion (stream or non-stream)."""
    calls = {"completions": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["completions"] += 1
        payload = json.loads(request.content)
        if payload.get("stream"):
            return httpx.Response(200, content=TOOL_STREAM_BODY.encode(), headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json=TOOL_NONSTREAM_RESPONSE)

    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        proxy_router.httpx, "AsyncClient", lambda *a, **k: real_async_client(transport=httpx.MockTransport(handler))
    )
    return calls


def _b(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def exact_hash_only(monkeypatch):
    """Day One posture: exact-hash cache, semantic off (no embedding latency)."""
    monkeypatch.setattr(settings, "semantic_cache_enabled", False)


def test_streaming_tool_call_miss_caches_with_tool_calls(client, db_session, provision, mock_tool_openai, monkeypatch):
    ws = provision(sub="auth0|tool", email="tool@example.com")
    monkeypatch.setattr(settings, "proxy_openai_keys", {ws["project_id"]: "sk-test"})
    body = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "weather in Paris?"}],
        "tools": [{"type": "function", "function": {"name": "get_weather"}}],
        "stream": True,
    }

    res = client.post("/v1/chat/completions", headers=_b(ws["api_key"]), json=body)
    assert res.status_code == 200
    # The tool call streamed through to the client verbatim.
    assert "get_weather" in res.text and "[DONE]" in res.text

    # The call was metered (not dropped) ...
    events = db_session.scalars(select(UsageEvent).where(UsageEvent.project_id == ws["project_id"])).all()
    assert len(events) == 1 and events[0].output_tokens == 8
    # ... and cached, with the tool_calls intact in the stored payload.
    entry = db_session.scalar(select(ProxyCacheEntry).where(ProxyCacheEntry.project_id == ws["project_id"]))
    assert entry is not None
    stored_call = entry.response_payload["choices"][0]["message"]["tool_calls"][0]
    assert stored_call["function"]["name"] == "get_weather"
    assert json.loads(stored_call["function"]["arguments"]) == {"city": "Paris"}


def test_cached_tool_call_served_nonstream_and_stream(client, db_session, provision, mock_tool_openai, monkeypatch):
    ws = provision(sub="auth0|tool", email="tool@example.com")
    monkeypatch.setattr(settings, "proxy_openai_keys", {ws["project_id"]: "sk-test"})
    base = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "weather in Paris?"}],
        "tools": [{"type": "function", "function": {"name": "get_weather"}}],
    }

    # Prime the cache with a non-streaming miss.
    first = client.post("/v1/chat/completions", headers=_b(ws["api_key"]), json=base)
    assert first.status_code == 200
    assert first.json()["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "get_weather"
    assert mock_tool_openai["completions"] == 1

    # Non-streaming hit: tool_calls preserved, no upstream call.
    hit = client.post("/v1/chat/completions", headers=_b(ws["api_key"]), json=base)
    assert hit.status_code == 200
    assert hit.json()["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] == '{"city":"Paris"}'
    assert mock_tool_openai["completions"] == 1

    # Streaming hit on the same cached entry: tool_calls survive the SSE path.
    stream_hit = client.post("/v1/chat/completions", headers=_b(ws["api_key"]), json={**base, "stream": True})
    assert stream_hit.status_code == 200
    assert "get_weather" in stream_hit.text
    sse = openai_ops.parse_sse_events(stream_hit.text)
    assert sse[0]["choices"][0]["delta"]["tool_calls"][0]["function"]["name"] == "get_weather"
    assert mock_tool_openai["completions"] == 1
