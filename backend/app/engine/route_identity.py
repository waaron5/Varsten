"""Canonical route identity.

Learning segments, eval runs, policies, and guardrails all need to name "the same
route" to attach evidence to it, but historically each keyed on something
different (a model, a task type, a free-form guardrail string, a feature tag).
This module defines the one canonical route key they should converge on.

A route is identified, in priority order, by the most specific business handle
the caller supplied: the ``feature`` it serves, else the ``workflow`` it belongs
to, else the API ``request_type``, else the inferred ``task_type``; failing all,
it is the project's ``default`` route. The key is normalized (lowercased,
whitespace collapsed, length-capped) so the same route always produces the same
string regardless of incidental casing or spacing.

The key is content-free — it is built only from allocation tags and derived
labels, never from prompt or completion text — so it is safe to persist on the
decision ledger and aggregate over.
"""

from __future__ import annotations

import re

MAX_ROUTE_KEY_LEN = 128
DEFAULT_ROUTE = "default"

_WHITESPACE = re.compile(r"\s+")


def _normalize(value: str) -> str:
    return _WHITESPACE.sub("_", value.strip().lower())[:MAX_ROUTE_KEY_LEN]


def canonical_route_key(
    *,
    feature: str | None = None,
    workflow: str | None = None,
    request_type: str | None = None,
    task_type: str | None = None,
) -> str:
    """The canonical route key, most-specific business handle first.

    Returns ``default`` when the caller supplied no route-identifying context."""
    for value in (feature, workflow, request_type, task_type):
        if value and value.strip():
            return _normalize(value)
    return DEFAULT_ROUTE


def route_key_from_context(ctx, *, request_type: str | None = None) -> str:
    """Build the canonical route key from a RequestContext (+ the API request
    type). Tolerates ``None`` context by returning the default route."""
    if ctx is None:
        return canonical_route_key(request_type=request_type)
    return canonical_route_key(
        feature=getattr(ctx, "feature", None),
        workflow=getattr(ctx, "workflow", None),
        request_type=request_type,
        task_type=getattr(ctx, "task_type", None),
    )


def model_scoped_route_key(route_key: str, model: str | None) -> str:
    """A route key scoped to a specific model, for consumers that key on the
    (route, incumbent model) pair (routing policies, per-model guardrails)."""
    return f"{route_key}::{model}" if model else route_key
