"""Anthropic upstream adapter.

The streaming translator updates its canonical usage ledger from Anthropic's
`message_start` and cumulative `message_delta` events before yielding translated
OpenAI-compatible SSE chunks. That ordering is the important financial invariant:
post-stream bookkeeping can always read the last known provider usage, even when
the terminal event carries no usage block.
"""

import json
import time
from collections.abc import Iterator
from typing import Any

from app.core.config import settings
from app.proxy.providers.base import LLMAdapter, StreamTranslator
from app.proxy.providers.canonical import CanonicalCompletion, CanonicalUsage


def _usage_from_anthropic(usage: dict[str, Any] | None, previous: CanonicalUsage | None = None) -> CanonicalUsage:
    previous = previous or CanonicalUsage()
    if not usage:
        return previous

    cache_read = int(usage.get("cache_read_input_tokens") or previous.provider_cached_input_tokens or 0)
    cache_creation = int(usage.get("cache_creation_input_tokens") or 0)
    input_tokens = previous.input_tokens
    if "input_tokens" in usage:
        input_tokens = int(usage.get("input_tokens") or 0) + cache_creation + cache_read

    output_tokens = previous.output_tokens
    if "output_tokens" in usage:
        output_tokens = int(usage.get("output_tokens") or 0)

    return CanonicalUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        provider_cached_input_tokens=cache_read,
    )


def _openai_finish_reason(stop_reason: str | None) -> str:
    return {
        "end_turn": "stop",
        "stop_sequence": "stop",
        "max_tokens": "length",
        "tool_use": "tool_calls",
    }.get(stop_reason or "", stop_reason or "stop")


class _SSEDecoder:
    def __init__(self) -> None:
        self._buffer = ""

    def feed(self, chunk: bytes) -> Iterator[tuple[str | None, str]]:
        self._buffer += chunk.decode("utf-8", errors="replace").replace("\r\n", "\n")
        blocks = self._buffer.split("\n\n")
        self._buffer = blocks.pop()
        for block in blocks:
            event = None
            data_lines: list[str] = []
            for raw_line in block.splitlines():
                line = raw_line.strip()
                if line.startswith("event:"):
                    event = line[len("event:") :].strip()
                elif line.startswith("data:"):
                    data_lines.append(line[len("data:") :].strip())
            if data_lines:
                yield event, "\n".join(data_lines)


def _sse_chunk(model: str, delta: dict[str, Any], finish_reason: str | None = None) -> bytes:
    payload = {
        "id": f"chatcmpl-varsten-{int(time.time() * 1000)}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n".encode()


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text"
        )
    return ""


def _json_object_or_empty(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _openai_tool_call(block: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": block.get("id") or "",
        "type": "function",
        "function": {
            "name": block.get("name") or "",
            "arguments": json.dumps(block.get("input") or {}, separators=(",", ":")),
        },
    }


class AnthropicStreamTranslator(StreamTranslator):
    def __init__(self) -> None:
        self._decoder = _SSEDecoder()
        self._parts: list[str] = []
        self._tool_blocks: dict[int, dict[str, Any]] = {}
        self._tool_calls: list[dict[str, Any]] = []
        self._model = ""
        self._finish_reason = "stop"
        self.current_usage = CanonicalUsage()

    def push(self, upstream_chunk: bytes) -> Iterator[bytes]:
        for _, data in self._decoder.feed(upstream_chunk):
            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                continue
            yield from self._handle_event(payload)

    def _handle_event(self, payload: dict[str, Any]) -> Iterator[bytes]:
        event_type = payload.get("type")
        if event_type == "message_start":
            yield from self._handle_message_start(payload)
        if event_type == "content_block_start":
            yield from self._handle_content_block_start(payload)
        if event_type == "content_block_delta":
            yield from self._handle_content_block_delta(payload)
        if event_type == "content_block_stop":
            yield from self._handle_content_block_stop(payload)
        if event_type == "message_delta":
            self._handle_message_delta(payload)
        if event_type == "message_stop":
            yield _sse_chunk(self._model, {}, self._finish_reason)
            yield b"data: [DONE]\n\n"

    def _handle_message_start(self, payload: dict[str, Any]) -> Iterator[bytes]:
        message = payload.get("message") or {}
        self._model = message.get("model") or self._model
        self.current_usage = _usage_from_anthropic(message.get("usage"), self.current_usage)
        yield _sse_chunk(self._model, {"role": "assistant"})

    def _handle_content_block_start(self, payload: dict[str, Any]) -> Iterator[bytes]:
        index = int(payload.get("index") or 0)
        block = payload.get("content_block") or {}
        if block.get("type") == "text" and block.get("text"):
            text = str(block["text"])
            self._parts.append(text)
            yield _sse_chunk(self._model, {"content": text})
        elif block.get("type") == "tool_use":
            self._tool_blocks[index] = {**block, "_partial_json": ""}

    def _handle_content_block_delta(self, payload: dict[str, Any]) -> Iterator[bytes]:
        index = int(payload.get("index") or 0)
        delta = payload.get("delta") or {}
        if delta.get("type") == "text_delta" and delta.get("text"):
            text = str(delta["text"])
            self._parts.append(text)
            yield _sse_chunk(self._model, {"content": text})
        elif delta.get("type") == "input_json_delta":
            block = self._tool_blocks.setdefault(index, {"type": "tool_use", "_partial_json": ""})
            block["_partial_json"] += str(delta.get("partial_json") or "")

    def _handle_content_block_stop(self, payload: dict[str, Any]) -> Iterator[bytes]:
        index = int(payload.get("index") or 0)
        block = self._tool_blocks.pop(index, None)
        if block is None:
            return
        partial_json = block.pop("_partial_json", "")
        if partial_json and not block.get("input"):
            block["input"] = _json_object_or_empty(partial_json)
        tool_call = _openai_tool_call(block)
        self._tool_calls.append(tool_call)
        yield _sse_chunk(self._model, {"tool_calls": [{"index": len(self._tool_calls) - 1, **tool_call}]})

    def _handle_message_delta(self, payload: dict[str, Any]) -> None:
        self.current_usage = _usage_from_anthropic(payload.get("usage"), self.current_usage)
        delta = payload.get("delta") or {}
        self._finish_reason = _openai_finish_reason(delta.get("stop_reason")) if delta.get("stop_reason") else "stop"

    def finish(self) -> CanonicalCompletion:
        return CanonicalCompletion(
            model=self._model,
            content="".join(self._parts),
            tool_calls=self._tool_calls or None,
            finish_reason=self._finish_reason,
            usage=self.current_usage,
        )


class AnthropicAdapter(LLMAdapter):
    provider = "anthropic"

    def endpoint(self) -> str:
        return f"{settings.anthropic_base_url.rstrip('/')}/v1/messages"

    def headers(self, api_key: str) -> dict[str, str]:
        return {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

    def prepare_request(self, body: dict, *, model: str, stream: bool) -> dict:
        messages, system = _anthropic_messages_from_openai(body.get("messages") or [])
        wire: dict[str, Any] = {
            "model": model,
            "max_tokens": int(body.get("max_tokens") or body.get("max_completion_tokens") or 1024),
            "messages": messages,
            "stream": stream,
        }
        if system:
            wire["system"] = system
        if "temperature" in body:
            wire["temperature"] = body["temperature"]
        tools = _anthropic_tools_from_openai(body.get("tools") or [])
        if tools:
            wire["tools"] = tools
        return wire

    def parse_completion(self, raw: dict) -> CanonicalCompletion:
        parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        for block in raw.get("content") or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
            elif block.get("type") == "tool_use":
                tool_calls.append(_openai_tool_call(block))
        return CanonicalCompletion(
            model=raw.get("model") or "",
            content="".join(parts),
            tool_calls=tool_calls or None,
            finish_reason=_openai_finish_reason(raw.get("stop_reason")),
            usage=_usage_from_anthropic(raw.get("usage")),
            raw=None,
        )

    def stream_translator(self) -> StreamTranslator:
        return AnthropicStreamTranslator()


def _anthropic_messages_from_openai(messages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str | None]:
    system_parts: list[str] = []
    out: list[dict[str, Any]] = []
    for message in messages:
        role = message.get("role")
        if role == "system":
            text = _content_text(message.get("content"))
            if text:
                system_parts.append(text)
            continue
        if role == "tool":
            out.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": message.get("tool_call_id") or "",
                            "content": _content_text(message.get("content")),
                        }
                    ],
                }
            )
            continue

        content = message.get("content")
        if isinstance(content, str):
            anthropic_content: str | list[dict[str, Any]] = content
        else:
            anthropic_content = [
                {"type": "text", "text": part.get("text", "")}
                for part in content or []
                if isinstance(part, dict) and part.get("type") == "text"
            ]
        tool_calls = message.get("tool_calls") or []
        if tool_calls:
            blocks = (
                anthropic_content
                if isinstance(anthropic_content, list)
                else [{"type": "text", "text": anthropic_content}]
            )
            for call in tool_calls:
                function = call.get("function") or {}
                try:
                    input_payload = json.loads(function.get("arguments") or "{}")
                except json.JSONDecodeError:
                    input_payload = {}
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": call.get("id") or "",
                        "name": function.get("name") or "",
                        "input": input_payload,
                    }
                )
            anthropic_content = blocks
        if role in {"user", "assistant"}:
            out.append({"role": role, "content": anthropic_content})
    return out, "\n\n".join(system_parts) or None


def _anthropic_tools_from_openai(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for tool in tools:
        function = tool.get("function") if isinstance(tool, dict) else None
        if not isinstance(function, dict):
            continue
        out.append(
            {
                "name": function.get("name") or "",
                "description": function.get("description") or "",
                "input_schema": function.get("parameters") or {"type": "object"},
            }
        )
    return out
