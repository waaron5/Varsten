"""Client dialect request/response transforms.

Provider adapters own upstream provider wire. This module owns the client edge:
turn native SDK requests into Varsten's internal OpenAI-shaped request form, and
render canonical completions back into the caller's original SDK dialect.
"""

import json
import time
from collections.abc import Iterator
from typing import Any, Protocol

from app.proxy.client_dialects import ClientDialect, ParsedClientRequest
from app.proxy.providers import canonical
from app.proxy.providers.canonical import CanonicalCompletion, CanonicalUsage


def request_to_openai_shape(parsed: ParsedClientRequest) -> dict[str, Any]:
    if parsed.dialect == ClientDialect.OPENAI:
        return dict(parsed.body)
    if parsed.dialect == ClientDialect.ANTHROPIC:
        return _anthropic_request_to_openai(parsed.body)
    if parsed.dialect == ClientDialect.GEMINI_NATIVE:
        return _gemini_request_to_openai(parsed.body, parsed.model, stream=parsed.stream)
    raise ValueError(f"unsupported client dialect: {parsed.dialect}")


def render_completion_for_client(parsed: ParsedClientRequest, completion: CanonicalCompletion) -> dict[str, Any]:
    if parsed.dialect == ClientDialect.OPENAI:
        return canonical.completion_payload(completion)
    if parsed.dialect == ClientDialect.ANTHROPIC:
        return _completion_to_anthropic(completion)
    if parsed.dialect == ClientDialect.GEMINI_NATIVE:
        return _completion_to_gemini(completion)
    raise ValueError(f"unsupported client dialect: {parsed.dialect}")


class ClientStreamRenderer(Protocol):
    def push(self, openai_chunk: bytes) -> Iterator[bytes]:
        """Render an OpenAI-compatible stream chunk into the caller's SDK dialect."""
        ...

    def finish(self, completion: CanonicalCompletion) -> Iterator[bytes]:
        """Render final SDK-dialect stream events after canonical completion assembly."""
        ...


def stream_renderer_for_client(parsed: ParsedClientRequest) -> ClientStreamRenderer:
    if parsed.dialect == ClientDialect.OPENAI:
        return _OpenAIClientStreamRenderer()
    if parsed.dialect == ClientDialect.ANTHROPIC:
        return _AnthropicClientStreamRenderer(parsed)
    if parsed.dialect == ClientDialect.GEMINI_NATIVE:
        return _GeminiClientStreamRenderer(parsed)
    raise ValueError(f"unsupported client dialect: {parsed.dialect}")


class _OpenAIClientStreamRenderer:
    def push(self, openai_chunk: bytes) -> Iterator[bytes]:
        yield openai_chunk

    def finish(self, completion: CanonicalCompletion) -> Iterator[bytes]:
        return iter(())


class _OpenAISSEDecoder:
    def __init__(self) -> None:
        self._buffer = ""

    def feed(self, chunk: bytes) -> Iterator[dict[str, Any]]:
        self._buffer += chunk.decode("utf-8", errors="replace").replace("\r\n", "\n")
        blocks = self._buffer.split("\n\n")
        self._buffer = blocks.pop()
        for block in blocks:
            data_lines = _sse_data_lines(block)
            if not data_lines:
                continue
            try:
                payload = json.loads("\n".join(data_lines))
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                yield payload


def _sse_data_lines(block: str) -> list[str]:
    lines: list[str] = []
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue
        data = line[len("data:") :].strip()
        if not data or data == "[DONE]":
            continue
        lines.append(data)
    return lines


def _sse_json(payload: dict[str, Any], *, event: str | None = None) -> bytes:
    data = json.dumps(payload, separators=(",", ":"))
    if event:
        return f"event: {event}\ndata: {data}\n\n".encode()
    return f"data: {data}\n\n".encode()


class _AnthropicClientStreamRenderer:
    def __init__(self, parsed: ParsedClientRequest) -> None:
        self._decoder = _OpenAISSEDecoder()
        self._model = parsed.model or ""
        self._message_started = False
        self._content_started = False
        self._text_block_index: int | None = None
        self._next_block_index = 0
        self._tool_call_slots: dict[int, dict[str, Any]] = {}
        self._tool_block_indexes: dict[int, int] = {}
        self._open_tool_indexes: set[int] = set()
        self._finish_reason = "stop"
        self._closed = False

    def push(self, openai_chunk: bytes) -> Iterator[bytes]:
        for payload in self._decoder.feed(openai_chunk):
            self._model = payload.get("model") or self._model
            yield from self._handle_openai_payload(payload)

    def _handle_openai_payload(self, payload: dict[str, Any]) -> Iterator[bytes]:
        for choice in payload.get("choices") or []:
            if not isinstance(choice, dict):
                continue
            if choice.get("finish_reason"):
                self._finish_reason = str(choice["finish_reason"])
            delta = choice.get("delta") or {}
            if delta.get("role") == "assistant":
                yield from self._ensure_message_start(CanonicalUsage())
            content = delta.get("content")
            if content:
                yield from self._emit_text(str(content))
            tool_calls = delta.get("tool_calls")
            if isinstance(tool_calls, list) and tool_calls:
                yield from self._emit_tool_call_fragments(tool_calls)

    def finish(self, completion: CanonicalCompletion) -> Iterator[bytes]:
        if self._closed:
            return iter(())
        return self._finish_stream(completion)

    def _finish_stream(self, completion: CanonicalCompletion) -> Iterator[bytes]:
        self._closed = True
        self._model = completion.model or self._model
        yield from self._ensure_message_start(completion.usage)
        if not self._content_started and completion.content:
            yield from self._emit_text(completion.content)
        yield from self._close_text_block()
        yield from self._close_tool_blocks()
        if not self._tool_block_indexes:
            for call in completion.tool_calls or []:
                yield from _anthropic_tool_call_events(self._allocate_block_index(), call)
        stop_reason = _anthropic_stop_reason(completion.finish_reason or self._finish_reason, completion.tool_calls)
        yield _sse_json(
            {
                "type": "message_delta",
                "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                "usage": {"output_tokens": completion.usage.output_tokens},
            },
            event="message_delta",
        )
        yield _sse_json({"type": "message_stop"}, event="message_stop")

    def _emit_text(self, text: str) -> Iterator[bytes]:
        yield from self._ensure_message_start(CanonicalUsage())
        if self._text_block_index is None:
            self._text_block_index = self._allocate_block_index()
            self._content_started = True
            yield _sse_json(
                {
                    "type": "content_block_start",
                    "index": self._text_block_index,
                    "content_block": {"type": "text", "text": ""},
                },
                event="content_block_start",
            )
        yield _sse_json(
            {
                "type": "content_block_delta",
                "index": self._text_block_index,
                "delta": {"type": "text_delta", "text": text},
            },
            event="content_block_delta",
        )

    def _emit_tool_call_fragments(self, fragments: list[dict[str, Any]]) -> Iterator[bytes]:
        yield from self._ensure_message_start(CanonicalUsage())
        yield from self._close_text_block()
        for fragment in fragments:
            if not isinstance(fragment, dict):
                continue
            openai_index = _tool_call_fragment_index(fragment)
            slot = self._tool_call_slots.setdefault(openai_index, _empty_tool_call_slot())
            arguments_delta = _merge_tool_call_fragment(slot, fragment)
            block_index = self._tool_block_indexes.get(openai_index)
            if block_index is None:
                block_index = self._allocate_block_index()
                self._tool_block_indexes[openai_index] = block_index
                self._open_tool_indexes.add(openai_index)
                yield _anthropic_tool_call_start(block_index, slot)
            if arguments_delta:
                yield _sse_json(
                    {
                        "type": "content_block_delta",
                        "index": block_index,
                        "delta": {"type": "input_json_delta", "partial_json": arguments_delta},
                    },
                    event="content_block_delta",
                )

    def _close_text_block(self) -> Iterator[bytes]:
        if self._text_block_index is None:
            return iter(())
        index = self._text_block_index
        self._text_block_index = None
        return iter((_sse_json({"type": "content_block_stop", "index": index}, event="content_block_stop"),))

    def _close_tool_blocks(self) -> Iterator[bytes]:
        for openai_index in sorted(self._open_tool_indexes, key=lambda idx: self._tool_block_indexes[idx]):
            yield _anthropic_tool_call_stop(self._tool_block_indexes[openai_index])
        self._open_tool_indexes.clear()

    def _allocate_block_index(self) -> int:
        index = self._next_block_index
        self._next_block_index += 1
        return index

    def _ensure_message_start(self, usage: CanonicalUsage) -> Iterator[bytes]:
        if self._message_started:
            return iter(())
        self._message_started = True
        payload = {
            "type": "message_start",
            "message": {
                "id": f"msg_varsten_{int(time.time() * 1000)}",
                "type": "message",
                "role": "assistant",
                "content": [],
                "model": self._model,
                "stop_reason": None,
                "stop_sequence": None,
                "usage": _anthropic_usage(usage),
            },
        }
        return iter((_sse_json(payload, event="message_start"),))


def _anthropic_tool_call_events(index: int, call: dict[str, Any]) -> Iterator[bytes]:
    yield _anthropic_tool_call_start(index, call)
    yield _anthropic_tool_call_stop(index)


def _anthropic_tool_call_start(index: int, call: dict[str, Any]) -> bytes:
    function = call.get("function") or {}
    block = {
        "type": "tool_use",
        "id": call.get("id") or f"toolu_varsten_{int(time.time() * 1000)}",
        "name": function.get("name") or "",
        "input": _json_object(function.get("arguments")),
    }
    return _sse_json(
        {"type": "content_block_start", "index": index, "content_block": block},
        event="content_block_start",
    )


def _anthropic_tool_call_stop(index: int) -> bytes:
    return _sse_json({"type": "content_block_stop", "index": index}, event="content_block_stop")


class _GeminiClientStreamRenderer:
    def __init__(self, parsed: ParsedClientRequest) -> None:
        self._decoder = _OpenAISSEDecoder()
        self._model = parsed.model or ""
        self._finish_reason = "stop"
        self._emitted_content = False
        self._tool_call_slots: dict[int, dict[str, Any]] = {}
        self._closed = False

    def push(self, openai_chunk: bytes) -> Iterator[bytes]:
        for payload in self._decoder.feed(openai_chunk):
            self._model = payload.get("model") or self._model
            yield from self._handle_openai_payload(payload)

    def _handle_openai_payload(self, payload: dict[str, Any]) -> Iterator[bytes]:
        for choice in payload.get("choices") or []:
            if not isinstance(choice, dict):
                continue
            if choice.get("finish_reason"):
                self._finish_reason = str(choice["finish_reason"])
            delta = choice.get("delta") or {}
            content = delta.get("content")
            if content:
                self._emitted_content = True
                yield _gemini_sse([{"text": str(content)}], self._model)
            tool_calls = delta.get("tool_calls")
            if isinstance(tool_calls, list):
                for fragment in tool_calls:
                    if not isinstance(fragment, dict):
                        continue
                    slot = self._tool_call_slots.setdefault(
                        _tool_call_fragment_index(fragment), _empty_tool_call_slot()
                    )
                    _merge_tool_call_fragment(slot, fragment)

    def finish(self, completion: CanonicalCompletion) -> Iterator[bytes]:
        if self._closed:
            return
        self._closed = True
        self._model = completion.model or self._model
        parts: list[dict[str, Any]] = []
        if not self._emitted_content and completion.content:
            parts.append({"text": completion.content})
        tool_calls = completion.tool_calls or [self._tool_call_slots[i] for i in sorted(self._tool_call_slots)]
        parts.extend(_gemini_tool_parts(tool_calls))
        yield _gemini_sse(
            parts or [{"text": ""}],
            self._model,
            finish_reason=_gemini_finish_reason(completion.finish_reason or self._finish_reason),
            usage=completion.usage,
        )


def _gemini_sse(
    parts: list[dict[str, Any]],
    model: str,
    *,
    finish_reason: str | None = None,
    usage: CanonicalUsage | None = None,
) -> bytes:
    candidate: dict[str, Any] = {"content": {"role": "model", "parts": parts}, "index": 0}
    if finish_reason:
        candidate["finishReason"] = finish_reason
    payload: dict[str, Any] = {"candidates": [candidate], "modelVersion": model}
    if usage is not None:
        payload["usageMetadata"] = _gemini_usage(usage)
    return _sse_json(payload)


def _gemini_tool_parts(tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    for call in tool_calls:
        function = call.get("function") or {}
        parts.append(
            {
                "functionCall": {
                    "name": function.get("name") or "",
                    "args": _json_object(function.get("arguments")),
                }
            }
        )
    return parts


def _empty_tool_call_slot() -> dict[str, Any]:
    return {"id": None, "type": "function", "function": {"name": "", "arguments": ""}}


def _tool_call_fragment_index(fragment: dict[str, Any]) -> int:
    try:
        return int(fragment.get("index") or 0)
    except (TypeError, ValueError):
        return 0


def _merge_tool_call_fragment(slot: dict[str, Any], fragment: dict[str, Any]) -> str:
    if fragment.get("id"):
        slot["id"] = fragment["id"]
    if fragment.get("type"):
        slot["type"] = fragment["type"]
    function = fragment.get("function") or {}
    if function.get("name"):
        slot.setdefault("function", {}).setdefault("name", "")
        slot["function"]["name"] += str(function["name"])
    arguments_delta = function.get("arguments")
    if arguments_delta:
        slot.setdefault("function", {}).setdefault("arguments", "")
        slot["function"]["arguments"] += str(arguments_delta)
        return str(arguments_delta)
    return ""


def _anthropic_request_to_openai(body: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "model": body.get("model") or "",
        "messages": [],
        "stream": bool(body.get("stream")),
    }
    if "max_tokens" in body:
        out["max_tokens"] = body["max_tokens"]
    if "temperature" in body:
        out["temperature"] = body["temperature"]
    if body.get("system"):
        out["messages"].append({"role": "system", "content": _anthropic_content_text(body["system"])})

    for message in body.get("messages") or []:
        if not isinstance(message, dict):
            continue
        out["messages"].extend(_anthropic_message_to_openai(message))

    tools = _anthropic_tools_to_openai(body.get("tools") or [])
    if tools:
        out["tools"] = tools
    return out


def _anthropic_message_to_openai(message: dict[str, Any]) -> list[dict[str, Any]]:
    role = message.get("role")
    content = message.get("content")
    if role == "user" and _anthropic_content_has_type(content, "tool_result"):
        return _anthropic_tool_results_to_openai(content)
    if role == "assistant" and _anthropic_content_has_type(content, "tool_use"):
        return [_anthropic_assistant_tool_use_to_openai(content)]
    if role in {"user", "assistant"}:
        return [{"role": role, "content": _anthropic_content_to_openai(content)}]
    return []


def _anthropic_content_to_openai(content: Any) -> str | list[dict[str, str]]:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts = [
            {"type": "text", "text": str(block.get("text") or "")}
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        return text_parts if len(text_parts) != 1 else text_parts[0]["text"]
    return ""


def _anthropic_content_text(content: Any) -> str:
    converted = _anthropic_content_to_openai(content)
    if isinstance(converted, str):
        return converted
    return "".join(part.get("text", "") for part in converted)


def _anthropic_content_has_type(content: Any, block_type: str) -> bool:
    return isinstance(content, list) and any(
        isinstance(block, dict) and block.get("type") == block_type for block in content
    )


def _anthropic_tool_results_to_openai(content: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for block in content if isinstance(content, list) else []:
        if not isinstance(block, dict) or block.get("type") != "tool_result":
            continue
        out.append(
            {
                "role": "tool",
                "tool_call_id": block.get("tool_use_id") or "",
                "content": _anthropic_content_text(block.get("content")),
            }
        )
    return out


def _anthropic_assistant_tool_use_to_openai(content: Any) -> dict[str, Any]:
    text = _anthropic_content_text(content)
    tool_calls = []
    for block in content if isinstance(content, list) else []:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        tool_calls.append(
            {
                "id": block.get("id") or "",
                "type": "function",
                "function": {
                    "name": block.get("name") or "",
                    "arguments": json.dumps(block.get("input") or {}, separators=(",", ":")),
                },
            }
        )
    return {"role": "assistant", "content": text or None, "tool_calls": tool_calls}


def _anthropic_tools_to_openai(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict) or tool.get("type"):
            continue
        out.append(
            {
                "type": "function",
                "function": {
                    "name": tool.get("name") or "",
                    "description": tool.get("description") or "",
                    "parameters": tool.get("input_schema") or {"type": "object"},
                },
            }
        )
    return out


def _gemini_request_to_openai(body: dict[str, Any], model: str | None, *, stream: bool) -> dict[str, Any]:
    out: dict[str, Any] = {"model": model or "", "messages": [], "stream": stream}
    system = _gemini_system_text(body.get("systemInstruction"))
    if system:
        out["messages"].append({"role": "system", "content": system})
    for content in body.get("contents") or []:
        if isinstance(content, dict):
            out["messages"].extend(_gemini_content_to_openai(content))

    raw_generation = body.get("generationConfig")
    generation: dict[str, Any] = raw_generation if isinstance(raw_generation, dict) else {}
    if "temperature" in generation:
        out["temperature"] = generation["temperature"]
    if "maxOutputTokens" in generation:
        out["max_tokens"] = generation["maxOutputTokens"]
    tools = _gemini_tools_to_openai(body.get("tools") or [])
    if tools:
        out["tools"] = tools
    return out


def _gemini_system_text(system_instruction: Any) -> str:
    if not isinstance(system_instruction, dict):
        return ""
    return "".join(
        str(part.get("text") or "")
        for part in system_instruction.get("parts") or []
        if isinstance(part, dict) and part.get("text")
    )


def _gemini_content_to_openai(content: dict[str, Any]) -> list[dict[str, Any]]:
    role = "assistant" if content.get("role") == "model" else "user"
    text_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    tool_messages: list[dict[str, Any]] = []
    for part in content.get("parts") or []:
        if not isinstance(part, dict):
            continue
        if part.get("text"):
            text_parts.append(str(part["text"]))
        elif isinstance(part.get("functionCall"), dict):
            call = part["functionCall"]
            tool_calls.append(
                {
                    "id": f"call_{call.get('name') or 'gemini'}",
                    "type": "function",
                    "function": {
                        "name": call.get("name") or "",
                        "arguments": json.dumps(call.get("args") or {}, separators=(",", ":")),
                    },
                }
            )
        elif isinstance(part.get("functionResponse"), dict):
            response = part["functionResponse"]
            tool_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": f"call_{response.get('name') or 'gemini'}",
                    "content": json.dumps(response.get("response") or {}, separators=(",", ":")),
                }
            )
    if tool_messages:
        return tool_messages
    message: dict[str, Any] = {"role": role, "content": "".join(text_parts) or None}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return [message]


def _gemini_tools_to_openai(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        for declaration in tool.get("functionDeclarations") or []:
            if not isinstance(declaration, dict):
                continue
            out.append(
                {
                    "type": "function",
                    "function": {
                        "name": declaration.get("name") or "",
                        "description": declaration.get("description") or "",
                        "parameters": declaration.get("parameters") or {"type": "object"},
                    },
                }
            )
    return out


def _completion_to_anthropic(completion: CanonicalCompletion) -> dict[str, Any]:
    content: list[dict[str, Any]] = []
    if completion.content:
        content.append({"type": "text", "text": completion.content})
    for call in completion.tool_calls or []:
        function = call.get("function") or {}
        content.append(
            {
                "type": "tool_use",
                "id": call.get("id") or f"toolu_varsten_{int(time.time() * 1000)}",
                "name": function.get("name") or "",
                "input": _json_object(function.get("arguments")),
            }
        )
    return {
        "id": f"msg_varsten_{int(time.time() * 1000)}",
        "type": "message",
        "role": "assistant",
        "model": completion.model,
        "content": content or [{"type": "text", "text": ""}],
        "stop_reason": _anthropic_stop_reason(completion.finish_reason, completion.tool_calls),
        "stop_sequence": None,
        "usage": _anthropic_usage(completion.usage),
    }


def _anthropic_stop_reason(finish_reason: str | None, tool_calls: list[dict] | None) -> str:
    if tool_calls:
        return "tool_use"
    return {"length": "max_tokens", "stop": "end_turn"}.get(finish_reason or "stop", "end_turn")


def _anthropic_usage(usage: CanonicalUsage) -> dict[str, int]:
    return {
        "input_tokens": usage.input_tokens,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": usage.provider_cached_input_tokens,
        "output_tokens": usage.output_tokens,
    }


def _completion_to_gemini(completion: CanonicalCompletion) -> dict[str, Any]:
    parts: list[dict[str, Any]] = []
    if completion.content:
        parts.append({"text": completion.content})
    for call in completion.tool_calls or []:
        function = call.get("function") or {}
        parts.append(
            {
                "functionCall": {
                    "name": function.get("name") or "",
                    "args": _json_object(function.get("arguments")),
                }
            }
        )
    return {
        "candidates": [
            {
                "content": {"role": "model", "parts": parts or [{"text": ""}]},
                "finishReason": _gemini_finish_reason(completion.finish_reason),
                "index": 0,
            }
        ],
        "usageMetadata": _gemini_usage(completion.usage),
        "modelVersion": completion.model,
    }


def _gemini_finish_reason(finish_reason: str | None) -> str:
    return {"length": "MAX_TOKENS", "content_filter": "SAFETY"}.get(finish_reason or "stop", "STOP")


def _gemini_usage(usage: CanonicalUsage) -> dict[str, int]:
    metadata = {
        "promptTokenCount": usage.input_tokens,
        "candidatesTokenCount": usage.output_tokens,
        "totalTokenCount": usage.input_tokens + usage.output_tokens,
    }
    if usage.provider_cached_input_tokens:
        metadata["cachedContentTokenCount"] = usage.provider_cached_input_tokens
    return metadata


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
