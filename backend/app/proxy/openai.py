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
        data = line[len("data:"):].strip()
        if not data or data == "[DONE]":
            continue
        try:
            events.append(json.loads(data))
        except json.JSONDecodeError:
            continue
    return events


def assemble_stream(events: list[dict]) -> dict:
    """Reduce streamed chunks to {content, usage, model, finish_reason}."""
    parts: list[str] = []
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
            if choice.get("finish_reason"):
                finish_reason = choice["finish_reason"]
    return {
        "content": "".join(parts),
        "usage": usage,
        "model": model,
        "finish_reason": finish_reason or "stop",
    }


def build_completion_object(model: str, content: str, usage: dict, finish_reason: str) -> dict:
    """A chat.completion object built from an assembled stream, used as the cached
    payload and served verbatim on a non-streaming hit."""
    return {
        "id": f"chatcmpl-varsten-{int(time.time() * 1000)}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": finish_reason,
            }
        ],
        "usage": usage,
        "varsten": {"cache": "hit"},
    }


def completion_to_sse(payload: dict) -> Iterator[bytes]:
    """Serve a cached completion as a minimal OpenAI SSE stream: one content chunk,
    a final stop chunk, then [DONE]. Good enough for clients that expect streaming."""
    model = payload.get("model", "")
    content = payload["choices"][0]["message"]["content"]
    base = {"id": payload.get("id", ""), "object": "chat.completion.chunk", "created": payload.get("created", 0), "model": model}

    first = {**base, "choices": [{"index": 0, "delta": {"role": "assistant", "content": content}, "finish_reason": None}]}
    yield f"data: {json.dumps(first)}\n\n".encode()

    last = {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
    yield f"data: {json.dumps(last)}\n\n".encode()

    yield b"data: [DONE]\n\n"


def usage_tokens(usage: dict) -> tuple[int, int, int]:
    """(input_tokens, output_tokens, cached_input_tokens) from an OpenAI usage block."""
    prompt = int(usage.get("prompt_tokens") or 0)
    completion = int(usage.get("completion_tokens") or 0)
    cached = int((usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)
    return prompt, completion, cached
