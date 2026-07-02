"""Tool-call fidelity through the proxy assembly and serialization layer.

The target ICP is agent/tool-heavy traffic, so a tool-calling completion must
survive streaming reassembly and JSON/SSE rendering without losing its
tool_calls. Runtime proxy caching intentionally skips tool-dependent traffic; the
pure serialization test still pins cached replay shape for migration/backfill
compatibility. Pure-function tests need no DB; the end-to-end tests drive the
real proxy with a MockTransport upstream.
"""

import json

import httpx
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models import ProxyCacheEntry, UsageEvent
from app.proxy import circuit, http_client
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
    assert calls is not None
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
    assert assembled.tool_calls is not None
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
    monkeypatch.setattr(http_client, "_client", real_async_client(transport=httpx.MockTransport(handler)))
    return calls


def _b(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _low_risk_headers(token: str) -> dict:
    return {
        **_b(token),
        "X-Varsten-Metadata": json.dumps({"task_type": "agent.lookup", "task_confidence": 0.95, "risk_level": "low"}),
    }


@pytest.fixture(autouse=True)
def exact_hash_only(monkeypatch):
    """Exact-hash cache available, semantic off (no embedding latency)."""
    monkeypatch.setattr(settings, "semantic_cache_enabled", False)


@pytest.mark.anyio
async def test_streaming_tool_call_miss_records_without_caching(
    async_client, async_db_session, async_provision, mock_tool_openai, monkeypatch
):
    ws = await async_provision(sub="auth0|tool", email="tool@example.com")
    monkeypatch.setattr(settings, "proxy_openai_keys", {ws["project_id"]: "sk-test"})
    body = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "Look up Paris with the available tool."}],
        "tools": [{"type": "function", "function": {"name": "get_weather"}}],
        "stream": True,
    }

    res = await async_client.post("/v1/chat/completions", headers=_low_risk_headers(ws["api_key"]), json=body)
    assert res.status_code == 200
    assert res.headers["x-varsten-cache"] == "miss"
    # The tool call streamed through to the client verbatim.
    assert "get_weather" in res.text and "[DONE]" in res.text

    # The call was metered (not dropped), but tool-dependent traffic is no longer
    # stored for exact-cache replay.
    events = (await async_db_session.scalars(select(UsageEvent).where(UsageEvent.project_id == ws["project_id"]))).all()
    assert len(events) == 1 and events[0].output_tokens == 8
    entry = await async_db_session.scalar(select(ProxyCacheEntry).where(ProxyCacheEntry.project_id == ws["project_id"]))
    assert entry is None


@pytest.mark.anyio
async def test_tool_call_requests_forward_each_time_instead_of_cache_hits(
    async_client, async_db_session, async_provision, mock_tool_openai, monkeypatch
):
    ws = await async_provision(sub="auth0|tool", email="tool@example.com")
    monkeypatch.setattr(settings, "proxy_openai_keys", {ws["project_id"]: "sk-test"})
    base = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "Look up Paris with the available tool."}],
        "tools": [{"type": "function", "function": {"name": "get_weather"}}],
    }
    headers = _low_risk_headers(ws["api_key"])

    # First non-streaming request forwards and preserves tool_calls.
    first = await async_client.post("/v1/chat/completions", headers=headers, json=base)
    assert first.status_code == 200
    assert first.headers["x-varsten-cache"] == "miss"
    assert first.json()["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "get_weather"
    assert mock_tool_openai["completions"] == 1

    # Identical tool request still forwards; no exact-cache hit is served.
    second = await async_client.post("/v1/chat/completions", headers=headers, json=base)
    assert second.status_code == 200
    assert second.headers["x-varsten-cache"] == "miss"
    assert second.json()["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] == '{"city":"Paris"}'
    assert mock_tool_openai["completions"] == 2

    # Streaming follows the same policy while preserving the SSE tool-call shape.
    stream = await async_client.post("/v1/chat/completions", headers=headers, json={**base, "stream": True})
    assert stream.status_code == 200
    assert stream.headers["x-varsten-cache"] == "miss"
    assert "get_weather" in stream.text
    sse = openai_ops.parse_sse_events(stream.text)
    assert sse[0]["choices"][0]["delta"]["tool_calls"][0]["function"]["name"] == "get_weather"
    assert mock_tool_openai["completions"] == 3

    entry = await async_db_session.scalar(select(ProxyCacheEntry).where(ProxyCacheEntry.project_id == ws["project_id"]))
    assert entry is None
