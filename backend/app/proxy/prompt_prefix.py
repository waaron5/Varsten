"""Content-free stable-prefix fingerprint for prompt-cache orchestration.

Provider prompt caches (OpenAI automatic caching, Anthropic cache_control) bill
a request's stable leading tokens at a much cheaper cache-read rate — but only
when that prefix is byte-stable across requests. A route that interleaves
volatile content (timestamps, user data, shuffled tool lists) into its system
prompt silently forfeits that discount on every call.

To *measure* prefix stability instead of guessing at it, the proxy fingerprints
the parts of each request a provider cache would key on — system/developer
messages and the tool definitions — as a SHA-256 hash. Per CLAUDE.md's data-flow
contract, hashes, token counts, and eval scores may flow to the control plane;
the content itself is inspected in memory only and never stored. The share of a
route's traffic that repeats one dominant fingerprint is the route's measured
cacheable-prefix share, which the prompt-cache recommendation uses in place of a
flat assumption (and, inverted, is the signal for "your prefix is unstable —
restructure it").

Handles the three client dialects' request shapes; unknown shapes yield None
(no signal) rather than a misleading hash.
"""

import hashlib
import json
from typing import Any

# Roles whose messages form the stable prefix a provider cache keys on.
_PREFIX_ROLES = {"system", "developer"}


def stable_prefix_hash(body: dict[str, Any] | None) -> str | None:
    """A content-free fingerprint of this request's cacheable prefix, or None
    when the request carries no stable-prefix material to fingerprint."""
    if not isinstance(body, dict):
        return None
    parts: list[Any] = []

    # OpenAI dialect: leading system/developer messages + tool definitions.
    messages = body.get("messages")
    if isinstance(messages, list):
        for message in messages:
            if not isinstance(message, dict) or message.get("role") not in _PREFIX_ROLES:
                break  # the stable prefix ends at the first non-system turn
            parts.append(message.get("content"))

    # Anthropic native: a top-level system prompt.
    system = body.get("system")
    if system is not None:
        parts.append(system)

    # Gemini native: systemInstruction.
    system_instruction = body.get("systemInstruction") or body.get("system_instruction")
    if system_instruction is not None:
        parts.append(system_instruction)

    tools = body.get("tools")
    if tools:
        parts.append(tools)

    if not parts:
        return None
    blob = json.dumps(parts, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def full_request_fingerprint(body: dict[str, Any] | None) -> str | None:
    """A content-free fingerprint of the whole request body.

    Two requests with the same fingerprint asked the provider the same question.
    Within one client trace (X-Varsten-Trace-Id) a repeated fingerprint is a
    redundant LLM call — an agent loop re-asking what it already knows — which the
    trace analysis surfaces as a workflow recommendation. Same data-flow contract
    as the prefix hash: content is hashed in memory, only the digest is stored."""
    if not isinstance(body, dict) or not body:
        return None
    blob = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
