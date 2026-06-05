"""Smart-routing eligibility: a deterministic per-request predicate.

Smart routing sends an individual request to the cheaper candidate only when
cheap, structural request signals say it is within the candidate's reach;
otherwise it stays on the incumbent. This runs on the hot path, so it must be
pure and fast: NO model call, NO LLM judge, just inspection of the request body.

Signals (all conservative -- default to keeping the incumbent when unsure):
- prompt size: large contexts are harder; only route small prompts.
- tool / function calling: a structured agentic call; keep the stronger model
  unless explicitly allowed.
- structured output (response_format json): keep the stronger model unless allowed.
- requested completion budget: long generations are harder; only route short ones.

The same predicate filters the off-path eval's replay corpus, so the candidate is
proven on exactly the subset it will actually serve.
"""
from typing import Any

# Conservative defaults. Tunable per policy via params["predicate"].
DEFAULT_PREDICATE: dict[str, Any] = {
    "max_prompt_chars": 6000,
    "route_when_tools": False,
    "route_when_json_schema": False,
    "max_completion_tokens": 1024,
}


def _prompt_chars(messages: Any) -> int:
    if not isinstance(messages, list):
        return 0
    total = 0
    for m in messages:
        content = m.get("content") if isinstance(m, dict) else None
        if isinstance(content, str):
            total += len(content)
        elif isinstance(content, list):
            # Multimodal: count only the text parts.
            for block in content:
                if isinstance(block, dict) and isinstance(block.get("text"), str):
                    total += len(block["text"])
    return total


def _has_tools(body: dict) -> bool:
    return bool(body.get("tools") or body.get("functions"))


def _wants_structured_output(body: dict) -> bool:
    rf = body.get("response_format")
    return isinstance(rf, dict) and rf.get("type") in ("json_schema", "json_object")


def _completion_budget(body: dict) -> int | None:
    mt = body.get("max_completion_tokens")
    if mt is None:
        mt = body.get("max_tokens")
    try:
        return int(mt) if mt is not None else None
    except (TypeError, ValueError):
        return None


def is_eligible(body: dict, predicate: dict | None) -> bool:
    """True when this request may be routed to the candidate under the predicate.
    An empty/None predicate means always eligible (no per-request gating)."""
    if not predicate:
        return True
    if not isinstance(body, dict):
        return False

    max_chars = predicate.get("max_prompt_chars")
    if max_chars is not None and _prompt_chars(body.get("messages")) > max_chars:
        return False

    if _has_tools(body) and not predicate.get("route_when_tools", False):
        return False

    if _wants_structured_output(body) and not predicate.get("route_when_json_schema", False):
        return False

    max_completion = predicate.get("max_completion_tokens")
    if max_completion is not None:
        budget = _completion_budget(body)
        if budget is not None and budget > max_completion:
            return False

    return True
