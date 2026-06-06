"""OpenAI upstream helpers for the Phase 1 proxy: URL/headers, SSE parsing, and
building/serving cached completions.

Nothing here writes content to disk. Assembling a streamed completion happens in
volatile memory so the response can be billed and (optionally) cached.
"""

import json
import time
from collections.abc import Iterator

from app.core.config import settings

CHAT_COMPLETIONS_PATH = "/v1/chat/completions"


def upstream_url() -> str:
    return f"{settings.openai_base_url.rstrip('/')}{CHAT_COMPLETIONS_PATH}"


def upstream_headers(client_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {client_key}",
        "Content-Type": "application/json",
    }


def parse_sse_events(raw: str) -> list[dict]:
    """Extract the JSON objects from an OpenAI SSE stream body, skipping [DONE]."""
    events: list[dict] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line[len("data:") :].strip()
        if not data or data == "[DONE]":
            continue
        try:
            events.append(json.loads(data))
        except json.JSONDecodeError:
            continue
    return events


def _accumulate_tool_calls(slots: dict[int, dict], deltas: list[dict]) -> None:
    """Fold a chunk's delta.tool_calls fragments into per-index accumulators.

    OpenAI streams tool calls as partial fragments keyed by `index`: the first
    fragment for an index carries id/type/function.name, later fragments append
    string pieces of function.arguments. Parallel tool calls arrive interleaved on
    distinct indices, so accumulate by index and concatenate the argument string."""
    for frag in deltas:
        idx = frag.get("index", 0)
        slot = slots.setdefault(idx, {"id": None, "type": "function", "function": {"name": "", "arguments": ""}})
        if frag.get("id"):
            slot["id"] = frag["id"]
        if frag.get("type"):
            slot["type"] = frag["type"]
        fn = frag.get("function") or {}
        if fn.get("name"):
            slot["function"]["name"] += fn["name"]
        if fn.get("arguments"):
            slot["function"]["arguments"] += fn["arguments"]


def assemble_stream(events: list[dict]) -> dict:
    """Reduce streamed chunks to {content, tool_calls, usage, model, finish_reason}.

    Both content and tool_calls are reconstructed: a tool-calling completion streams
    its calls as delta.tool_calls fragments that must be reassembled, or the cached
    and metered copy would silently drop the calls (the agent workload's whole
    payload). content is "" and tool_calls is None when the respective channel is
    absent."""
    parts: list[str] = []
    tool_call_slots: dict[int, dict] = {}
    usage: dict = {}
    model = ""
    finish_reason = None
    for ev in events:
        model = ev.get("model") or model
        if ev.get("usage"):
            usage = ev["usage"]
        for choice in ev.get("choices", []):
            delta = choice.get("delta") or {}
            if delta.get("content"):
                parts.append(delta["content"])
            if delta.get("tool_calls"):
                _accumulate_tool_calls(tool_call_slots, delta["tool_calls"])
            if choice.get("finish_reason"):
                finish_reason = choice["finish_reason"]
    tool_calls = [tool_call_slots[i] for i in sorted(tool_call_slots)] or None
    return {
        "content": "".join(parts),
        "tool_calls": tool_calls,
        "usage": usage,
        "model": model,
        "finish_reason": finish_reason or "stop",
    }


def build_completion_object(
    model: str,
    content: str,
    usage: dict,
    finish_reason: str,
    tool_calls: list[dict] | None = None,
) -> dict:
    """A chat.completion object built from an assembled stream, used as the cached
    payload and served verbatim on a non-streaming hit.

    Mirrors OpenAI's shape: content is null when the assistant only returned tool
    calls, and tool_calls is included only when present, so a cached tool-calling
    response round-trips faithfully."""
    message: dict = {"role": "assistant", "content": content or None}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {
        "id": f"chatcmpl-varsten-{int(time.time() * 1000)}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": finish_reason,
            }
        ],
        "usage": usage,
        "varsten": {"cache": "hit"},
    }


def completion_to_sse(payload: dict) -> Iterator[bytes]:
    """Serve a cached completion as a minimal OpenAI SSE stream: one delta chunk,
    a final chunk carrying the stored finish_reason, then [DONE].

    The delta carries whichever channels the cached message holds (content and/or
    tool_calls), so a cached tool-calling response served over the streaming path
    keeps its tool_calls instead of being flattened to content-only."""
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


def usage_tokens(usage: dict) -> tuple[int, int, int]:
    """(input_tokens, output_tokens, cached_input_tokens) from an OpenAI usage block."""
    prompt = int(usage.get("prompt_tokens") or 0)
    completion = int(usage.get("completion_tokens") or 0)
    cached = int((usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)
    return prompt, completion, cached
