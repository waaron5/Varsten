"""Cross-provider routing safety checks.

This module only answers whether a request can be translated safely from one
provider wire dialect to another. It does not choose the destination provider;
the router/policy layer owns that decision.
"""

from collections.abc import Iterator, Mapping
from typing import Any, NamedTuple

from app.proxy.client_dialects import ClientDialect, ParsedClientRequest


class RoutingIneligibility(NamedTuple):
    reason_code: str
    reason_detail: dict[str, Any]


_ANTHROPIC_SERVER_TOOL_TYPES = {
    "bash_20250124",
    "computer_20250124",
    "text_editor_20250124",
    "web_search_20250305",
}

_SAFE_GEMINI_PART_KEYS = {"text", "functionCall", "functionResponse"}
_SAFE_OPENAI_CONTENT_TYPES = {"text"}


def cross_provider_ineligibility(
    parsed: ParsedClientRequest,
    *,
    requested_provider: str,
    candidate_provider: str,
) -> RoutingIneligibility | None:
    """Return the first exact reason a cross-provider route is unsafe."""
    if requested_provider == candidate_provider:
        return None
    if parsed.dialect == ClientDialect.ANTHROPIC:
        return _anthropic_ineligibility(parsed)
    if parsed.dialect == ClientDialect.GEMINI_NATIVE:
        return _gemini_native_ineligibility(parsed)
    if parsed.dialect == ClientDialect.OPENAI:
        return _openai_ineligibility(parsed)
    return None


def _anthropic_ineligibility(parsed: ParsedClientRequest) -> RoutingIneligibility | None:
    if _find_key(parsed.body, "cache_control"):
        return RoutingIneligibility(
            "anthropic_cache_control",
            {"path": parsed.path, "field": "cache_control"},
        )
    if parsed.headers.get("anthropic-beta"):
        return RoutingIneligibility(
            "anthropic_beta_unsupported",
            {"path": parsed.path, "header": "anthropic-beta", "value": parsed.headers["anthropic-beta"]},
        )
    if _has_anthropic_server_tool(parsed.body):
        return RoutingIneligibility(
            "server_side_tool",
            {"path": parsed.path, "field": "tools"},
        )
    return None


def _gemini_native_ineligibility(parsed: ParsedClientRequest) -> RoutingIneligibility | None:
    if parsed.body.get("safetySettings"):
        return RoutingIneligibility(
            "gemini_safety_settings",
            {"path": parsed.path, "field": "safetySettings"},
        )
    if _has_unmapped_gemini_part(parsed.body):
        return RoutingIneligibility(
            "native_multimodal_unmapped",
            {"path": parsed.path, "field": "contents.parts"},
        )
    return None


def _openai_ineligibility(parsed: ParsedClientRequest) -> RoutingIneligibility | None:
    server_tool = _openai_server_side_tool(parsed.body)
    if server_tool:
        return RoutingIneligibility(
            "server_side_tool",
            {"path": parsed.path, "field": "tools", "tool_type": server_tool},
        )
    if _has_unmapped_openai_content_part(parsed.body):
        return RoutingIneligibility(
            "native_multimodal_unmapped",
            {"path": parsed.path, "field": "messages.content"},
        )
    return None


def _iter_dicts(value: Any) -> Iterator[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        yield value
        for child in value.values():
            yield from _iter_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_dicts(child)


def _find_key(value: Any, key: str) -> bool:
    return any(key in item for item in _iter_dicts(value))


def _has_anthropic_server_tool(body: dict[str, Any]) -> bool:
    for tool in body.get("tools") or []:
        if not isinstance(tool, Mapping):
            continue
        tool_type = tool.get("type")
        if isinstance(tool_type, str) and tool_type in _ANTHROPIC_SERVER_TOOL_TYPES:
            return True
    return False


def _has_unmapped_gemini_part(body: dict[str, Any]) -> bool:
    for item in _iter_dicts(body.get("contents") or []):
        parts = item.get("parts")
        if not isinstance(parts, list):
            continue
        for part in parts:
            if not isinstance(part, Mapping):
                continue
            if not any(key in part for key in _SAFE_GEMINI_PART_KEYS):
                return True
            if "inlineData" in part or "fileData" in part:
                return True
    return False


def _openai_server_side_tool(body: dict[str, Any]) -> str | None:
    for tool in body.get("tools") or []:
        if not isinstance(tool, Mapping):
            continue
        tool_type = tool.get("type")
        if isinstance(tool_type, str) and tool_type != "function":
            return tool_type
    return None


def _has_unmapped_openai_content_part(body: dict[str, Any]) -> bool:
    for message in body.get("messages") or []:
        if not isinstance(message, Mapping):
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, Mapping):
                continue
            part_type = part.get("type")
            if part_type not in _SAFE_OPENAI_CONTENT_TYPES:
                return True
    return False
