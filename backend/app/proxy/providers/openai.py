"""OpenAI upstream adapter.

The Phase 1 provider. Because the client dialect is also OpenAI, this adapter is
near-identity: prepare_request just applies the model/stream flags, the streaming
translator passes bytes through untouched (zero added latency), and parse_completion
reuses the raw payload. The SSE parsing and tool-call-faithful assembly live here
because they are OpenAI-wire concerns; a different provider's adapter parses its
own wire format into the same canonical form.
"""

import json
from collections.abc import Iterator

from app.core.config import settings
from app.proxy.providers.base import LLMAdapter, StreamTranslator
from app.proxy.providers.canonical import CanonicalCompletion, CanonicalUsage

CHAT_COMPLETIONS_PATH = "/v1/chat/completions"


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
    fragment carries id/type/function.name, later fragments append string pieces of
    function.arguments. Parallel calls arrive interleaved on distinct indices, so
    accumulate by index and concatenate the argument string."""
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


def usage_from(usage: dict) -> CanonicalUsage:
    """OpenAI usage block -> canonical usage. prompt_tokens_details.cached_tokens is
    OpenAI's native prompt-cache discount and is tracked as provider_cached, never
    as a Varsten lever."""
    details = usage.get("prompt_tokens_details") or {}
    return CanonicalUsage(
        input_tokens=int(usage.get("prompt_tokens") or 0),
        output_tokens=int(usage.get("completion_tokens") or 0),
        provider_cached_input_tokens=int(details.get("cached_tokens") or 0),
    )


def _message_content(message: dict) -> str:
    content = message.get("content")
    if isinstance(content, list):
        return " ".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return content or ""


def assemble_stream(events: list[dict]) -> CanonicalCompletion:
    """Reduce OpenAI streamed chunks to a canonical completion. Reconstructs both
    content and tool_calls, so a tool-calling completion is metered and cached with
    its calls intact instead of being flattened to content-only."""
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
    return CanonicalCompletion(
        model=model,
        content="".join(parts),
        tool_calls=tool_calls,
        finish_reason=finish_reason or "stop",
        usage=usage_from(usage),
    )


class OpenAIStreamTranslator(StreamTranslator):
    """Passthrough translator: the upstream wire is already the client wire, so
    chunks are yielded untouched (no buffering before delivery, no per-chunk
    transform). A copy is accumulated to assemble the canonical completion once the
    stream ends, for metering and caching."""

    def __init__(self) -> None:
        self._buffer = bytearray()

    def push(self, upstream_chunk: bytes) -> Iterator[bytes]:
        self._buffer.extend(upstream_chunk)
        yield upstream_chunk

    def finish(self) -> CanonicalCompletion:
        return assemble_stream(parse_sse_events(self._buffer.decode("utf-8", errors="replace")))


class OpenAIAdapter(LLMAdapter):
    provider = "openai"

    def endpoint(self) -> str:
        return f"{settings.openai_base_url.rstrip('/')}{CHAT_COMPLETIONS_PATH}"

    def headers(self, api_key: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    def prepare_request(self, body: dict, *, model: str, stream: bool) -> dict:
        wire = {**body, "model": model, "stream": stream}
        if stream:
            # Ask for the usage block on the final chunk so streamed calls meter.
            wire["stream_options"] = {"include_usage": True}
        return wire

    def parse_completion(self, raw: dict) -> CanonicalCompletion:
        choice = (raw.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        return CanonicalCompletion(
            model=raw.get("model") or "",
            content=_message_content(message),
            tool_calls=message.get("tool_calls"),
            finish_reason=choice.get("finish_reason") or "stop",
            usage=usage_from(raw.get("usage") or {}),
            raw=raw,
        )

    def stream_translator(self) -> StreamTranslator:
        return OpenAIStreamTranslator()
