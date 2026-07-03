from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.engine.types import RequestFacts

_FRESHNESS_TERMS = (
    "as of ",
    "breaking",
    "current",
    "latest",
    "live",
    "now",
    "recent",
    "right now",
    "stock price",
    "this month",
    "this week",
    "today",
    "weather",
    "yesterday",
)

_PERSONALIZED_TERMS = (
    "account number",
    "billing address",
    "customer id",
    "for my account",
    "my account",
    "patient",
    "policy number",
    "ssn",
    "social security",
)

_HIGH_RISK_TERMS = (
    "diagnose",
    "dosage",
    "financial advice",
    "legal advice",
    "medical advice",
    "prescription",
    "security vulnerability",
    "trade stock",
)

_TEXT_CONTAINER_KEYS = {
    "content",
    "contents",
    "input",
    "message",
    "messages",
    "parts",
    "prompt",
    "system",
    "systemInstruction",
    "text",
}

_MULTIMODAL_PART_TYPES = (
    "audio",
    "file",
    "image",
    "image_url",
    "input_audio",
    "input_file",
    "input_image",
    "video",
)

_MULTIMODAL_FIELDS = (
    "audio",
    "file",
    "file_data",
    "fileData",
    "image",
    "image_url",
    "inline_data",
    "inlineData",
    "input_audio",
    "input_file",
    "input_image",
    "video",
)


def normalize_request_facts(body: dict[str, Any]) -> RequestFacts:
    """Extract provider-agnostic facts from a provider/client request body.

    This function is the boundary where raw request content may be inspected.
    It returns only counts and boolean signals that are safe for decision traces.
    """

    prompt_fragments = tuple(_iter_text_fragments(body))
    prompt_text = "\n".join(prompt_fragments).lower()
    return RequestFacts(
        prompt_chars=sum(len(fragment) for fragment in prompt_fragments),
        message_count=_message_count(body),
        has_tools=_has_tools(body),
        wants_json=_wants_json(body),
        has_multimodal=_body_has_multimodal(body),
        freshness_signal=_contains_any(prompt_text, _FRESHNESS_TERMS),
        personalized_signal=_contains_any(prompt_text, _PERSONALIZED_TERMS),
        high_risk_signal=_contains_any(prompt_text, _HIGH_RISK_TERMS),
    )


def _iter_text_fragments(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        if value.strip():
            yield value
        return
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in _TEXT_CONTAINER_KEYS:
                yield from _iter_text_fragments(nested)
        return
    if isinstance(value, list):
        for item in value:
            yield from _iter_text_fragments(item)


def _message_count(body: dict[str, Any]) -> int:
    for key in ("messages", "contents", "input"):
        value = body.get(key)
        if isinstance(value, list):
            return len(value)
    return 0


def _has_tools(body: dict[str, Any]) -> bool:
    return bool(body.get("tools") or body.get("functions") or body.get("tool_config") or body.get("toolConfig"))


def _wants_json(body: dict[str, Any]) -> bool:
    response_format = body.get("response_format")
    if isinstance(response_format, dict) and response_format.get("type") in {"json_object", "json_schema"}:
        return True

    generation_config = body.get("generationConfig")
    if isinstance(generation_config, dict) and generation_config.get("responseMimeType") == "application/json":
        return True

    response_mime_type = body.get("response_mime_type") or body.get("responseMimeType")
    return response_mime_type == "application/json"


def _body_has_multimodal(body: dict[str, Any]) -> bool:
    return any(
        _has_multimodal(value)
        for value in (body.get("messages"), body.get("input"), body.get("content"), body.get("contents"))
    )


def _has_multimodal(value: Any) -> bool:
    if isinstance(value, dict):
        content_type = value.get("type")
        if isinstance(content_type, str) and content_type.lower() in _MULTIMODAL_PART_TYPES:
            return True
        if any(field in value for field in _MULTIMODAL_FIELDS):
            return True
        return any(_has_multimodal(value.get(field)) for field in ("content", "contents", "messages", "input", "parts"))
    if isinstance(value, list):
        return any(_has_multimodal(item) for item in value)
    return False


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)
