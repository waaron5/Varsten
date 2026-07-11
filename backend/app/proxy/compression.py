"""Prompt-compression lever execution: an exact-match substitution on the hot path.

The hot path never compresses anything. It resolves an enabled policy for the
requested model (one indexed lookup, canary-gated, fail-open), loads the
approved artifact through a short TTL cache, and substitutes the compressed
system prompt ONLY when the request's system prompt hashes exactly to the
original the shadow eval proved. Any other request — different prompt, edited
prompt, no system message, structured content — passes through untouched. The
worst failure mode is "we stop saving on this route," never "we altered a
prompt we did not evaluate."

Savings are measured, not asserted: the policy carries the standard holdback,
the control arm forwards the original prompt, and the same-model experiment
pair (model -> model) feeds the live A/B and the drift guard exactly like trim.
"""

import threading
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import NamedTuple

from cachetools import TTLCache
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.engine.compression import artifact_for_recommendation, substitute_system_prompt
from app.engine.route_identity import DEFAULT_ROUTE, route_key_from_recommendation
from app.lever_controls import lever_enabled_async
from app.levers import LEVER_PROMPT_COMPRESSION, LEVER_TOKEN_TRIM
from app.models import Project, PromptCompression, ProxyPolicy, Recommendation
from app.proxy import canary

logger = get_logger("varsten.proxy.compression")

LEVER = LEVER_PROMPT_COMPRESSION

_ARTIFACT_CACHE_TTL_SECONDS = 60
# artifact_id -> (original_system_hash, compressed_system_prompt)
_artifact_cache: TTLCache[str, tuple[str, str]] = TTLCache(maxsize=1024, ttl=_ARTIFACT_CACHE_TTL_SECONDS)
_artifact_lock = threading.Lock()


class TransformConflictError(Exception):
    """Two body-transform levers cannot be live on one model: their same-model
    holdback experiments would merge into one unattributable A/B."""


class CompressionDecision(NamedTuple):
    holdback_percent: Decimal
    artifact_id: uuid.UUID | None
    policy_id: uuid.UUID | None = None
    source_recommendation_id: uuid.UUID | None = None


class _CompressionPolicySnapshot(NamedTuple):
    id: uuid.UUID
    holdback_percent: Decimal
    artifact_id: uuid.UUID | None
    source_recommendation_id: uuid.UUID | None
    rollout_percent: int


_POLICY_CACHE_TTL_SECONDS = 30
_policy_cache: TTLCache[tuple[str, str, str | None], _CompressionPolicySnapshot | None] = TTLCache(
    maxsize=4096,
    ttl=_POLICY_CACHE_TTL_SECONDS,
)
_policy_lock = threading.Lock()


def clear_policy_cache(project_id: uuid.UUID | None = None) -> None:
    with _policy_lock:
        if project_id is None:
            _policy_cache.clear()
            return
        prefix = str(project_id)
        for key in list(_policy_cache.keys()):
            if key[0] == prefix:
                _policy_cache.pop(key, None)


def _snapshot(policy: ProxyPolicy | None) -> _CompressionPolicySnapshot | None:
    if policy is None:
        return None
    raw_artifact_id = (policy.params or {}).get("artifact_id")
    return _CompressionPolicySnapshot(
        id=policy.id,
        holdback_percent=policy.holdback_percent or Decimal("0"),
        artifact_id=uuid.UUID(str(raw_artifact_id)) if raw_artifact_id else None,
        source_recommendation_id=policy.source_recommendation_id,
        rollout_percent=policy.rollout_percent,
    )


def clear_artifact_cache() -> None:
    with _artifact_lock:
        _artifact_cache.clear()


async def resolve_compression(
    db: AsyncSession,
    project_id: uuid.UUID,
    requested_model: str,
    *,
    route_key: str | None = None,
) -> CompressionDecision | None:
    """The enabled compression policy for this model, or None. Canary-gated and
    fail-open: any error forwards the body untouched."""
    if not requested_model:
        return None
    try:
        key = (str(project_id), requested_model, route_key)
        cache_hit = False
        policy: _CompressionPolicySnapshot | None = None
        if settings.proxy_policy_cache_enabled:
            with _policy_lock:
                cached = _policy_cache.get(key)
            if key in _policy_cache:
                cache_hit = True
                policy = cached
        if not cache_hit:
            base = (
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
            if route_key:
                row = (await db.scalars(base.where(ProxyPolicy.route_key == route_key))).first()
                if row is None:
                    row = (await db.scalars(base.where(ProxyPolicy.route_key == DEFAULT_ROUTE))).first()
            else:
                row = (await db.scalars(base)).first()
            policy = _snapshot(row)
            if settings.proxy_policy_cache_enabled:
                with _policy_lock:
                    _policy_cache[key] = policy
        if policy is None:
            return None
        if not await lever_enabled_async(db, project_id, LEVER):
            return None
        if policy.artifact_id is None:
            return None
        if not canary.in_rollout(policy.rollout_percent):
            return None
        return CompressionDecision(
            policy.holdback_percent,
            policy.artifact_id,
            policy_id=policy.id,
            source_recommendation_id=policy.source_recommendation_id,
        )
    except Exception:
        logger.exception("compression lookup failed; forwarding untouched", extra={"project_id": str(project_id)})
        return None


async def load_artifact(db: AsyncSession, artifact_id: uuid.UUID) -> tuple[str, str] | None:
    """(original_hash, compressed_text) for an artifact, TTL-cached. Fail-open."""
    key = str(artifact_id)
    with _artifact_lock:
        cached = _artifact_cache.get(key)
    if cached is not None:
        return cached
    try:
        artifact = await db.get(PromptCompression, artifact_id)
    except Exception:
        logger.exception("compression artifact load failed; forwarding untouched")
        return None
    if artifact is None:
        return None
    value = (artifact.original_system_hash, artifact.compressed_system_prompt)
    with _artifact_lock:
        _artifact_cache[key] = value
    return value


def apply_compression(body: dict, original_hash: str, compressed_text: str) -> tuple[dict, bool]:
    """Substitute the approved rewrite into a chat body on exact hash match.
    Returns (new_body, applied); never mutates the caller's body."""
    messages = body.get("messages")
    if not isinstance(messages, list):
        return body, False
    substituted, applied = substitute_system_prompt(messages, original_hash, compressed_text)
    if not applied:
        return body, False
    return {**body, "messages": substituted}, True


# --- control plane -------------------------------------------------------------------


def activate_compression_policy(
    db: Session,
    project: Project,
    recommendation: Recommendation,
    *,
    now: datetime | None = None,
) -> ProxyPolicy | None:
    """Activate (or refresh) the compression policy for an applied recommendation.

    Refuses to activate while a trim policy is enabled on the same model: two
    body transforms on one model would share a (model -> model) experiment pair
    and make the holdback A/B unattributable. Returns None when the
    recommendation lacks a target model or an artifact."""
    model = recommendation.related_model or recommendation.target_key
    if not model:
        return None
    artifact = artifact_for_recommendation(db, recommendation.id)
    if artifact is None:
        return None
    route_key = route_key_from_recommendation(recommendation)
    policy_route_key = route_key or DEFAULT_ROUTE
    trim_stmt = select(ProxyPolicy.id).where(
        ProxyPolicy.project_id == project.id,
        ProxyPolicy.lever == LEVER_TOKEN_TRIM,
        ProxyPolicy.target_key == model,
        ProxyPolicy.enabled.is_(True),
    )
    if policy_route_key != DEFAULT_ROUTE:
        trim_stmt = trim_stmt.where(
            or_(ProxyPolicy.route_key == policy_route_key, ProxyPolicy.route_key == DEFAULT_ROUTE)
        )
    trim_live = db.scalar(trim_stmt)
    if trim_live is not None:
        raise TransformConflictError(
            f"a token-trim policy is live on {model}; disable it before activating prompt compression "
            "(two body transforms on one model would merge their holdback experiments)"
        )
    at = now or datetime.now(UTC)
    stmt = select(ProxyPolicy).where(
        ProxyPolicy.project_id == project.id,
        ProxyPolicy.lever == LEVER,
        ProxyPolicy.target_key == model,
        ProxyPolicy.route_key == policy_route_key,
    )
    policy = db.scalar(stmt)
    fresh = policy is None or not policy.enabled
    if policy is None:
        policy = ProxyPolicy(
            organization_id=project.organization_id,
            project_id=project.id,
            lever=LEVER,
            target_type="model",
            target_key=model,
        )
        db.add(policy)
    policy.route_key = policy_route_key
    policy.params = {**(policy.params or {}), "artifact_id": str(artifact.id)}
    if fresh:
        policy.rollout_percent = canary.initial_rollout_percent()
    policy.enabled = True
    policy.source_recommendation_id = recommendation.id
    policy.activated_at = at
    clear_artifact_cache()
    clear_policy_cache(project.id)
    return policy


def deactivate_compression_for_recommendation(db: Session, recommendation: Recommendation) -> None:
    """Turn off any compression policy sourced from this recommendation."""
    db.execute(
        update(ProxyPolicy)
        .where(
            ProxyPolicy.source_recommendation_id == recommendation.id,
            ProxyPolicy.lever == LEVER,
        )
        .values(enabled=False)
    )
    clear_artifact_cache()
    clear_policy_cache(recommendation.project_id)
