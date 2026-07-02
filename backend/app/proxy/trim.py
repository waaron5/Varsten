"""Token-trim lever execution: a deterministic prompt transform on the hot path.

The transform removes provable redundancy from the request body before it is
forwarded, so OpenAI bills fewer input tokens. It is structural and lossless of
*information that matters*: prune conversation turns past a window, drop
exact-duplicate context blocks, collapse runs of whitespace. No tokenizer and no
model call run inline; the savings are the real input-token delta, measured by
the holdback A/B (control = untrimmed) exactly like routing.

Anything that could change the answer (summarising context with an LLM, dropping
unique content) is out: that judgement belongs off-path in the eval harness, not
in the request path.
"""

import copy
import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models import Project, ProxyPolicy, Recommendation

logger = get_logger("varsten.proxy.trim")

LEVER = "token_trim"

# Conservative defaults. Keep system messages always; keep the most recent N
# non-system turns; remove older ones (stale context the model rarely needs).
_DEFAULT_KEEP_LAST_TURNS = 12
_WHITESPACE = re.compile(r"[ \t]{2,}")
_BLANKLINES = re.compile(r"\n{3,}")


class TrimDecision(NamedTuple):
    holdback_percent: Decimal
    params: dict
    policy_id: uuid.UUID | None = None
    source_recommendation_id: uuid.UUID | None = None


async def resolve_trim(db: AsyncSession, project_id: uuid.UUID, requested_model: str) -> TrimDecision | None:
    """The enabled token-trim policy for this model, or None. Fail-open: any error
    returns None (forward the body untouched)."""
    if not requested_model:
        return None
    try:
        policy = (
            await db.scalars(
                select(ProxyPolicy)
                .where(
                    ProxyPolicy.project_id == project_id,
                    ProxyPolicy.lever == LEVER,
                    ProxyPolicy.target_key == requested_model,
                    ProxyPolicy.enabled.is_(True),
                )
                .order_by(ProxyPolicy.activated_at.desc().nullslast())
                .limit(1)
            )
        ).first()
        if policy is None:
            return None
        return TrimDecision(
            policy.holdback_percent or Decimal("0"),
            policy.params or {},
            policy_id=policy.id,
            source_recommendation_id=policy.source_recommendation_id,
        )
    except Exception:
        logger.exception("trim lookup failed; forwarding untrimmed", extra={"project_id": str(project_id)})
        return None


def _collapse_text(text: str) -> str:
    text = _WHITESPACE.sub(" ", text)
    text = _BLANKLINES.sub("\n\n", text)
    return text


def trim_messages(messages: list[dict], params: dict | None = None) -> tuple[list[dict], bool]:
    """Return (trimmed_messages, changed). Pure and deterministic. Only touches
    string content; list/multimodal content is passed through untouched so we
    never corrupt a structured payload."""
    params = params or {}
    if not isinstance(messages, list) or not messages:
        return messages, False
    keep_last = int(params.get("keep_last_turns", _DEFAULT_KEEP_LAST_TURNS))
    do_dedupe = params.get("dedupe", True)
    do_collapse = params.get("collapse_whitespace", True)

    system = [m for m in messages if m.get("role") == "system"]
    rest = [m for m in messages if m.get("role") != "system"]

    # Window: keep system context plus the most recent turns.
    windowed_rest = rest[-keep_last:] if keep_last > 0 and len(rest) > keep_last else rest

    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for m in system + windowed_rest:
        new_m = m
        content = m.get("content")
        if isinstance(content, str):
            text = _collapse_text(content) if do_collapse else content
            if do_dedupe:
                key = (m.get("role", ""), text)
                if key in seen:
                    continue
                seen.add(key)
            if text != content:
                new_m = {**m, "content": text}
        out.append(new_m)

    changed = out != messages
    return out, changed


def apply_trim(body: dict, params: dict | None = None) -> tuple[dict, bool]:
    """Trim the messages in a chat-completions body. Returns (new_body, changed).
    Never mutates the caller's body in place."""
    messages = body.get("messages")
    if not isinstance(messages, list):
        return body, False
    trimmed, changed = trim_messages(messages, params)
    if not changed:
        return body, False
    new_body = copy.copy(body)
    new_body["messages"] = trimmed
    return new_body, True


def activate_trim_policy(
    db: Session,
    project: Project,
    recommendation: Recommendation,
    *,
    now: datetime | None = None,
) -> ProxyPolicy | None:
    """Activate (or refresh) the token-trim policy for an applied recommendation.
    Keyed on the route's dominant model so the inline proxy can resolve it per
    request. Returns None when the recommendation carries no model to target."""
    model = recommendation.related_model
    if not model:
        return None
    at = now or datetime.now(UTC)
    policy = db.scalar(
        select(ProxyPolicy).where(
            ProxyPolicy.project_id == project.id,
            ProxyPolicy.lever == LEVER,
            ProxyPolicy.target_key == model,
        )
    )
    if policy is None:
        policy = ProxyPolicy(
            organization_id=project.organization_id,
            project_id=project.id,
            lever=LEVER,
            target_type="model",
            target_key=model,
        )
        db.add(policy)
    policy.params = {**(policy.params or {})}
    policy.enabled = True
    policy.source_recommendation_id = recommendation.id
    policy.activated_at = at
    return policy


def deactivate_trim_for_recommendation(db: Session, recommendation: Recommendation) -> None:
    """Turn off any trim policy sourced from this recommendation."""
    db.execute(
        update(ProxyPolicy)
        .where(
            ProxyPolicy.source_recommendation_id == recommendation.id,
            ProxyPolicy.lever == LEVER,
        )
        .values(enabled=False)
    )
