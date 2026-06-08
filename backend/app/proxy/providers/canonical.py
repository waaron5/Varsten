"""Varsten's canonical completion form and the client-facing (OpenAI) renderers.

The client dialect is permanently OpenAI: Client #1 points the OpenAI SDK at us,
so requests arrive OpenAI-shaped and responses must leave OpenAI-shaped no matter
which provider served them. So egress rendering is a fixed, provider-agnostic
concern and lives here, not in any provider adapter. Adapters translate the
UPSTREAM side into the canonical form below; this module renders that form back
out to the client and into the cache.
"""

import json
import time
from collections.abc import Iterator
from dataclasses import dataclass, field


@dataclass(frozen=True)
class CanonicalUsage:
    """Token accounting in provider-neutral terms.

    provider_cached_input_tokens is the PROVIDER's own prompt-cache discount (e.g.
    OpenAI's cached prompt tokens). It is never a Varsten lever and must never be
    counted as Varsten savings, so it is tracked as its own field and surfaced in
    the ledger under a distinct label. This keeps the Proof page unassailable."""

    input_tokens: int = 0
    output_tokens: int = 0
    provider_cached_input_tokens: int = 0


@dataclass
class CanonicalCompletion:
    """A completion in Varsten's internal form. Adapters produce this from their
    upstream wire format; the router meters and caches on it; this module renders
    it back to the OpenAI client dialect.

    raw holds the provider's full response payload when we have it (non-streaming),
    so an OpenAI upstream is served byte-faithfully with no re-render."""

    model: str
    content: str = ""
    tool_calls: list[dict] | None = None
    finish_reason: str = "stop"
    usage: CanonicalUsage = field(default_factory=CanonicalUsage)
    raw: dict | None = None


def _usage_dict(u: CanonicalUsage) -> dict[str, object]:
    d: dict[str, object] = {
        "prompt_tokens": u.input_tokens,
        "completion_tokens": u.output_tokens,
        "total_tokens": u.input_tokens + u.output_tokens,
    }
    if u.provider_cached_input_tokens:
        d["prompt_tokens_details"] = {"cached_tokens": u.provider_cached_input_tokens}
    return d


def completion_payload(c: CanonicalCompletion) -> dict:
    """Render canonical -> an OpenAI chat.completion dict, for cache storage and
    for serving a non-streaming response to the client. When the upstream was
    OpenAI we already hold the exact payload (raw) and reuse it verbatim; otherwise
    we synthesize the OpenAI shape from the canonical fields."""
    if c.raw is not None:
        return c.raw
    message: dict = {"role": "assistant", "content": c.content or None}
    if c.tool_calls:
        message["tool_calls"] = c.tool_calls
    return {
        "id": f"chatcmpl-varsten-{int(time.time() * 1000)}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": c.model,
        "choices": [{"index": 0, "message": message, "finish_reason": c.finish_reason}],
        "usage": _usage_dict(c.usage),
        "varsten": {"cache": "hit"},
    }


def to_openai_sse(payload: dict) -> Iterator[bytes]:
    """Serve a stored OpenAI completion dict as a minimal OpenAI SSE stream: one
    delta chunk carrying whichever channels are present (content and/or
    tool_calls), a final chunk with the stored finish_reason, then [DONE]. Used to
    serve a cache hit over the streaming path without losing tool calls."""
    choice = payload["choices"][0]
    message = choice.get("message") or {}
    content = message.get("content")
    tool_calls = message.get("tool_calls")
    finish_reason = choice.get("finish_reason") or ("tool_calls" if tool_calls else "stop")
    base = {
        "id": payload.get("id", ""),
        "object": "chat.completion.chunk",
        "created": payload.get("created", 0),
        "model": payload.get("model", ""),
    }

    delta: dict = {"role": "assistant"}
    if content:
        delta["content"] = content
    if tool_calls:
        delta["tool_calls"] = tool_calls
    first = {**base, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]}
    yield f"data: {json.dumps(first)}\n\n".encode()

    last = {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": finish_reason}]}
    yield f"data: {json.dumps(last)}\n\n".encode()

    yield b"data: [DONE]\n\n"
