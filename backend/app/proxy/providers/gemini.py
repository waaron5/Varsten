"""Gemini native upstream adapter."""

import json
import time
from collections.abc import Iterator
from typing import Any

from app.core.config import settings
from app.proxy.providers.base import LLMAdapter, StreamTranslator
from app.proxy.providers.canonical import CanonicalCompletion, CanonicalUsage


class _SSEDecoder:
    def __init__(self) -> None:
        self._buffer = ""

    def feed(self, chunk: bytes) -> Iterator[str]:
        self._buffer += chunk.decode("utf-8", errors="replace").replace("\r\n", "\n")
        blocks = self._buffer.split("\n\n")
        self._buffer = blocks.pop()
        for block in blocks:
            data_lines: list[str] = []
            for raw_line in block.splitlines():
                line = raw_line.strip()
                if line.startswith("data:"):
                    data = line[len("data:") :].strip()
                    if data == "[DONE]":
                        continue
                    data_lines.append(data)
            if data_lines:
                yield "\n".join(data_lines)


def _usage_from_metadata(metadata: dict[str, Any] | None, previous: CanonicalUsage | None = None) -> CanonicalUsage:
    previous = previous or CanonicalUsage()
    if not metadata:
        return previous
    cached_input = int(metadata.get("cachedContentTokenCount") or previous.provider_cached_input_tokens or 0)
    return CanonicalUsage(
        input_tokens=int(metadata.get("promptTokenCount") or previous.input_tokens or 0),
        output_tokens=int(metadata.get("candidatesTokenCount") or previous.output_tokens or 0),
        provider_cached_input_tokens=cached_input,
    )


def _finish_reason(reason: str | None) -> str:
    return {
        "STOP": "stop",
        "MAX_TOKENS": "length",
        "SAFETY": "content_filter",
        "RECITATION": "content_filter",
    }.get(reason or "", "stop")


def _openai_chunk(model: str, delta: dict[str, Any], finish_reason: str | None = None) -> bytes:
    payload = {
        "id": f"chatcmpl-varsten-{int(time.time() * 1000)}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n".encode()


def _model_name(raw: str | None) -> str:
    return (raw or "").removeprefix("models/")


def _gemini_tool_call(function_call: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": f"call_{function_call.get('name') or 'gemini'}",
        "type": "function",
        "function": {
            "name": function_call.get("name") or "",
            "arguments": json.dumps(function_call.get("args") or {}, separators=(",", ":")),
        },
    }


class GeminiStreamTranslator(StreamTranslator):
    def __init__(self) -> None:
        self._decoder = _SSEDecoder()
        self._parts: list[str] = []
        self._tool_calls: list[dict[str, Any]] = []
        self._model = ""
        self._finish_reason = "stop"
        self.current_usage = CanonicalUsage()

    def push(self, upstream_chunk: bytes) -> Iterator[bytes]:
        for data in self._decoder.feed(upstream_chunk):
            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                continue
            yield from self._handle_payload(payload)

    def _handle_payload(self, payload: dict[str, Any]) -> Iterator[bytes]:
        self._model = _model_name(payload.get("modelVersion")) or self._model
        self.current_usage = _usage_from_metadata(payload.get("usageMetadata"), self.current_usage)
        for candidate in payload.get("candidates") or []:
            if not isinstance(candidate, dict):
                continue
            content = candidate.get("content") or {}
            for part in content.get("parts") or []:
                if not isinstance(part, dict):
                    continue
                if part.get("text"):
                    text = str(part["text"])
                    self._parts.append(text)
                    yield _openai_chunk(self._model, {"content": text})
                elif part.get("functionCall"):
                    tool_call = _gemini_tool_call(part["functionCall"])
                    self._tool_calls.append(tool_call)
                    yield _openai_chunk(
                        self._model, {"tool_calls": [{"index": len(self._tool_calls) - 1, **tool_call}]}
                    )
            if candidate.get("finishReason"):
                self._finish_reason = _finish_reason(candidate.get("finishReason"))
                yield _openai_chunk(self._model, {}, self._finish_reason)
                yield b"data: [DONE]\n\n"

    def finish(self) -> CanonicalCompletion:
        return CanonicalCompletion(
            model=self._model,
            content="".join(self._parts),
            tool_calls=self._tool_calls or None,
            finish_reason=self._finish_reason,
            usage=self.current_usage,
        )


class GeminiAdapter(LLMAdapter):
    provider = "gemini"

    def endpoint(self) -> str:
        return self.request_url(model="gemini-3.5-flash", stream=False)

    def request_url(self, *, model: str, stream: bool) -> str:
        action = "streamGenerateContent?alt=sse" if stream else "generateContent"
        clean_model = _model_name(model)
        return f"{settings.gemini_base_url.rstrip('/')}/v1beta/models/{clean_model}:{action}"

    def headers(self, api_key: str) -> dict[str, str]:
        return {"x-goog-api-key": api_key, "content-type": "application/json"}

    def prepare_request(self, body: dict, *, model: str, stream: bool) -> dict:
        system_instruction, contents = _gemini_contents_from_openai(body.get("messages") or [])
        wire: dict[str, Any] = {"contents": contents}
        if system_instruction:
            wire["systemInstruction"] = {"parts": [{"text": system_instruction}]}
        generation_config: dict[str, Any] = {}
        if "temperature" in body:
            generation_config["temperature"] = body["temperature"]
        max_tokens = body.get("max_tokens") or body.get("max_completion_tokens")
        if max_tokens is not None:
            generation_config["maxOutputTokens"] = max_tokens
        if generation_config:
            wire["generationConfig"] = generation_config
        tools = _gemini_tools_from_openai(body.get("tools") or [])
        if tools:
            wire["tools"] = [{"functionDeclarations": tools}]
        return wire

    def parse_completion(self, raw: dict) -> CanonicalCompletion:
        parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        finish = "stop"
        for candidate in raw.get("candidates") or []:
            if not isinstance(candidate, dict):
                continue
            finish = _finish_reason(candidate.get("finishReason"))
            content = candidate.get("content") or {}
            for part in content.get("parts") or []:
                if not isinstance(part, dict):
                    continue
                if part.get("text"):
                    parts.append(str(part["text"]))
                elif part.get("functionCall"):
                    tool_calls.append(_gemini_tool_call(part["functionCall"]))
        return CanonicalCompletion(
            model=_model_name(raw.get("modelVersion")),
            content="".join(parts),
            tool_calls=tool_calls or None,
            finish_reason=finish,
            usage=_usage_from_metadata(raw.get("usageMetadata")),
        )

    def stream_translator(self) -> StreamTranslator:
        return GeminiStreamTranslator()


def _gemini_contents_from_openai(messages: list[dict[str, Any]]) -> tuple[str | None, list[dict[str, Any]]]:
    system_parts: list[str] = []
    contents: list[dict[str, Any]] = []
    for message in messages:
        role = message.get("role")
        text = _openai_content_text(message.get("content"))
        if role == "system":
            if text:
                system_parts.append(text)
            continue
        if role == "tool":
            contents.append(
                {
                    "role": "user",
                    "parts": [
                        {
                            "functionResponse": {
                                "name": message.get("name") or message.get("tool_call_id") or "tool",
                                "response": {"content": text},
                            }
                        }
                    ],
                }
            )
            continue
        if role in {"user", "assistant"}:
            gemini_role = "model" if role == "assistant" else "user"
            parts: list[dict[str, Any]] = [{"text": text}] if text else []
            for call in message.get("tool_calls") or []:
                function = call.get("function") or {}
                try:
                    args = json.loads(function.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                parts.append({"functionCall": {"name": function.get("name") or "", "args": args}})
            contents.append({"role": gemini_role, "parts": parts or [{"text": ""}]})
    return "\n\n".join(system_parts) or None, contents


def _openai_content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text"
        )
    return ""


def _gemini_tools_from_openai(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for tool in tools:
        function = tool.get("function") if isinstance(tool, dict) else None
        if not isinstance(function, dict):
            continue
        out.append(
            {
                "name": function.get("name") or "",
                "description": function.get("description") or "",
                "parameters": function.get("parameters") or {"type": "object"},
            }
        )
    return out
