"""Learned prompt compression: the off-path pipeline.

The lever's whole life happens off the request path except one exact-match
substitution:

1. **Generate.** From the route's replay corpus (the existing consented content
   store), find the dominant stable system prompt; an injectable generator
   (default: an off-path LLM rewrite on the customer's key, metered as
   optimization overhead) produces a shorter rewrite. A rewrite that fails
   validation — empty, not meaningfully shorter, or identical — is rejected on
   the spot and nothing is persisted.
2. **Prove.** The artifact gets a Recommendation and a pending EvalRun (lever
   ``prompt_compression``, same model on both sides). The standard eval runner
   replays the route's real traffic with the compressed prompt substituted and
   scores it against the incumbent responses; the standard verdict vocabulary
   applies, and the measured input-token cost delta falls out of the same
   machinery that prices model swaps.
3. **Approve.** The lever is in GATED_LEVERS (apply requires a completed run)
   and GOVERNED_LEVERS (a ``needs_human`` verdict proposes a ChangeRequest a
   named human must approve). It is approve-mode by default and stays that way.
4. **Execute.** Applying activates a ProxyPolicy with the standard canary ramp
   and holdback; the proxy substitutes the approved rewrite only when a
   request's system prompt hashes exactly to the evaluated original
   (``substitute_system_prompt``). Anything else passes through untouched —
   production prompts are never compressed inline, ever.
5. **Watch.** The holdback A/B measures the real savings; the drift guard rolls
   the policy back on confirmed quality or latency regression like any other
   transform lever.

The pure helpers here (extract/hash/substitute) are shared with the proxy's
hot-path module; they inspect content in memory only and persist nothing.
"""

import hashlib
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import AsyncSessionLocal
from app.eval import openai_ops
from app.eval.runner import run_eval
from app.levers import LEVER_PROMPT_COMPRESSION
from app.models import (
    EvalRun,
    ModelPrice,
    Project,
    PromptCompression,
    Recommendation,
    ReplaySample,
    RequestDecisionEvent,
    UsageEvent,
)
from app.pricing import price_usage_event

logger = get_logger("varsten.engine.compression")

LEVER = LEVER_PROMPT_COMPRESSION

# (system_prompt, key) -> (compressed_text | None, input_tokens, output_tokens)
CompressFn = Callable[[str, str], Awaitable[tuple[str | None, int, int]]]

# Crude chars-per-token estimate, used only for the recommendation's up-front
# savings *estimate*; the eval and the live holdback replace it with measurement.
_CHARS_PER_TOKEN = 4
_PREFIX_ROLES = {"system", "developer"}


class CompressionGenerationError(Exception):
    """Candidate generation failed a precondition; message is operator-safe."""


# --- pure helpers (shared with the proxy hot path) --------------------------------


def extract_system_text(messages: list | None) -> str | None:
    """The first system/developer message's string content, or None. This is
    exactly the text the substitution will replace, so extraction and
    substitution must stay symmetrical."""
    if not isinstance(messages, list):
        return None
    for message in messages:
        if not isinstance(message, dict):
            return None
        if message.get("role") in _PREFIX_ROLES:
            content = message.get("content")
            return content if isinstance(content, str) and content else None
        return None  # the stable prefix ends at the first non-system turn
    return None


def system_text_hash(text: str) -> str:
    """Full sha256 hex of the exact system prompt text (the runtime match key)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def substitute_system_prompt(messages: list, original_hash: str, compressed_text: str) -> tuple[list, bool]:
    """Replace the system prompt with the approved rewrite — only on an exact
    hash match of the original. Pure; returns (new_messages, applied). Any body
    shape that does not carry exactly the evaluated prompt is returned untouched:
    the lever substitutes what was proven, it never compresses what it sees."""
    current = extract_system_text(messages)
    if current is None or system_text_hash(current) != original_hash:
        return messages, False
    out = []
    replaced = False
    for message in messages:
        if not replaced and isinstance(message, dict) and message.get("role") in _PREFIX_ROLES:
            out.append({**message, "content": compressed_text})
            replaced = True
        else:
            out.append(message)
    return out, replaced


# --- candidate generation (off-path) -----------------------------------------------


def _dominant_system_prompt(db: Session, project: Project, model: str) -> tuple[str, int, int]:
    """The route's most common system prompt across its replay corpus, with how
    many samples carry it and the corpus size. Content is read from the corpus
    (its own consent gate) and handled in memory only."""
    samples = list(
        db.scalars(
            select(ReplaySample)
            .where(ReplaySample.project_id == project.id, ReplaySample.route_key == model)
            .order_by(ReplaySample.created_at.desc())
            .limit(settings.eval_replay_max_samples)
        )
    )
    counts: Counter[str] = Counter()
    texts: dict[str, str] = {}
    for sample in samples:
        text = extract_system_text(sample.request_messages)
        if text:
            digest = system_text_hash(text)
            counts.update([digest])
            texts[digest] = text
    if not counts:
        raise CompressionGenerationError(
            f"no replay samples for {model} carry a system prompt; capture traffic or add golden samples first"
        )
    digest, carrier_count = counts.most_common(1)[0]
    return texts[digest], carrier_count, len(samples)


def _monthly_route_volume(db: Session, project: Project, model: str) -> int:
    start = datetime.now(UTC) - timedelta(days=30)
    return int(
        db.scalar(
            select(func.count()).where(
                RequestDecisionEvent.project_id == project.id,
                RequestDecisionEvent.model_requested == model,
                RequestDecisionEvent.created_at >= start,
            )
        )
        or 0
    )


def _input_rate(db: Session, model: str) -> Decimal | None:
    price = db.scalars(
        select(ModelPrice).where(ModelPrice.model_key == model).order_by(ModelPrice.effective_at.desc()).limit(1)
    ).first()
    return price.input_cost_per_token if price else None


def _estimated_monthly_savings(
    db: Session, project: Project, model: str, original_chars: int, compressed_chars: int
) -> tuple[Decimal | None, int]:
    """Up-front estimate: saved input tokens per request x route volume x input
    rate. Honest None when the model has no catalog price; the eval's measured
    cost delta supersedes this the moment it completes."""
    volume = _monthly_route_volume(db, project, model)
    rate = _input_rate(db, model)
    if rate is None or volume <= 0:
        return None, volume
    saved_tokens = max(original_chars - compressed_chars, 0) // _CHARS_PER_TOKEN
    return (Decimal(saved_tokens) * rate * volume).quantize(Decimal("0.00000001")), volume


async def _meter_generation_overhead(
    db: Session, project: Project, input_tokens: int, output_tokens: int, at: datetime
) -> None:
    """The generation call ran on the customer's key: meter it as optimization
    overhead so verified savings subtract it. Priced through the async catalog
    bridge (read-only), written on the caller's session so it commits atomically
    with the artifact it paid for. Best-effort."""
    if input_tokens <= 0 and output_tokens <= 0:
        return
    try:
        async with AsyncSessionLocal() as adb:
            cost, cost_source, pricing_status, price_version_id = await price_usage_event(
                adb,
                organization_id=project.organization_id,
                model_key=settings.compression_generator_model,
                provider="openai",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_input_tokens=0,
                reported_cost_usd=None,
                at=at,
            )
        db.add(
            UsageEvent(
                project_id=project.id,
                organization_id=project.organization_id,
                api_key_id=None,
                source="overhead",
                provider="openai",
                model=settings.compression_generator_model,
                operation="prompt_compression",
                request_type="prompt_compression",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_input_tokens=0,
                total_tokens=input_tokens + output_tokens,
                cost_usd=cost,
                cost_source=cost_source,
                pricing_status=pricing_status,
                price_version_id=price_version_id,
                currency="USD",
                status="success",
                success=True,
                event_metadata={"overhead": "compression"},
                occurred_at=at,
                environment="production",
            )
        )
    except Exception:
        logger.exception("compression overhead metering failed", extra={"project_id": str(project.id)})


async def generate_compression_candidate(
    db: Session,
    project: Project,
    model: str,
    *,
    key: str,
    compress_fn: CompressFn = openai_ops.compress_system_prompt,
    generator_label: str | None = None,
    now: datetime | None = None,
) -> PromptCompression:
    """Generate, validate, and persist a compression candidate for a route, plus
    the Recommendation and pending EvalRun that carry it through the decision
    loop. Raises CompressionGenerationError on any precondition failure; on
    success nothing is live — the eval gate and approval still stand between the
    artifact and production traffic."""
    at = now or datetime.now(UTC)
    original, carrier_count, corpus_size = _dominant_system_prompt(db, project, model)
    if len(original) < settings.compression_min_prompt_chars:
        raise CompressionGenerationError(
            f"the dominant system prompt is {len(original)} chars; below "
            f"{settings.compression_min_prompt_chars} compression is not worth the quality risk"
        )

    compressed, gen_in, gen_out = await compress_fn(original, key)
    await _meter_generation_overhead(db, project, gen_in, gen_out, at)
    if not compressed or compressed == original:
        raise CompressionGenerationError("the generator returned no usable rewrite")
    if len(compressed) > len(original) * settings.compression_max_ratio:
        raise CompressionGenerationError(
            f"the rewrite is {len(compressed)}/{len(original)} chars; it does not clear the "
            f"{settings.compression_max_ratio:.0%} compression bar"
        )

    estimated, volume = _estimated_monthly_savings(db, project, model, len(original), len(compressed))
    recommendation = _upsert_recommendation(
        db, project, model, len(original), len(compressed), carrier_count, corpus_size, estimated, volume, at
    )

    artifact = PromptCompression(
        organization_id=project.organization_id,
        project_id=project.id,
        recommendation_id=recommendation.id,
        route_key=model,
        model=model,
        original_system_hash=system_text_hash(original),
        original_chars=len(original),
        compressed_system_prompt=compressed,
        compressed_chars=len(compressed),
        generator=generator_label or f"llm:{settings.compression_generator_model}",
    )
    db.add(artifact)

    run = EvalRun(
        organization_id=project.organization_id,
        project_id=project.id,
        recommendation_id=recommendation.id,
        lever=LEVER,
        route_key=model,
        incumbent_model=model,
        candidate_model=model,
    )
    db.add(run)
    db.commit()
    db.refresh(artifact)
    logger.info(
        "compression candidate generated",
        extra={
            "project_id": str(project.id),
            "model": model,
            "original_chars": len(original),
            "compressed_chars": len(compressed),
        },
    )
    return artifact


def _upsert_recommendation(
    db: Session,
    project: Project,
    model: str,
    original_chars: int,
    compressed_chars: int,
    carrier_count: int,
    corpus_size: int,
    estimated: Decimal | None,
    volume: int,
    at: datetime,
) -> Recommendation:
    dedupe_key = f"prompt_compression:{model}:{at:%Y-%m}"
    ratio = compressed_chars / original_chars if original_chars else 1.0
    title = f"Compress the system prompt on {model} ({(1 - ratio) * 100:.0f}% smaller)"
    description = (
        f"A learned rewrite shrinks this route's dominant system prompt from {original_chars:,} to "
        f"{compressed_chars:,} chars ({carrier_count} of {corpus_size} replay samples carry it). It applies only "
        f"to requests whose system prompt exactly matches the evaluated original, after a shadow eval and approval."
    )
    existing = db.scalar(
        select(Recommendation).where(Recommendation.project_id == project.id, Recommendation.dedupe_key == dedupe_key)
    )
    if existing is not None and existing.status == "open":
        existing.title = title
        existing.description = description
        existing.estimated_monthly_savings_usd = estimated
        existing.monthly_request_volume = volume or None
        existing.updated_at = at
        db.flush()
        return existing
    recommendation = Recommendation(
        organization_id=project.organization_id,
        project_id=project.id,
        dedupe_key=dedupe_key if existing is None else f"{dedupe_key}:{uuid.uuid4().hex[:8]}",
        type=LEVER,
        lever=LEVER,
        title=title,
        description=description,
        rationale=(
            "Generated off-path from the route's replay corpus; gated on a shadow eval of the compressed prompt "
            "against the route's real traffic, then human approval, canary, and holdback measurement."
        ),
        estimated_monthly_savings_usd=estimated,
        monthly_request_volume=volume or None,
        measurement_method="estimated",
        risk_level="medium",
        confidence="medium",
        target_type="model",
        target_key=model,
        related_provider="openai",
        related_model=model,
    )
    db.add(recommendation)
    db.flush()
    return recommendation


# --- eval execution -----------------------------------------------------------------


def artifact_for_recommendation(db: Session, recommendation_id) -> PromptCompression | None:
    return db.scalars(
        select(PromptCompression)
        .where(PromptCompression.recommendation_id == recommendation_id)
        .order_by(PromptCompression.created_at.desc())
        .limit(1)
    ).first()


async def run_compression_eval(
    db: Session,
    run: EvalRun,
    *,
    key: str,
    replay_fn=openai_ops.replay_candidate,
    judge_fn=openai_ops.judge_pairwise,
    now: datetime | None = None,
) -> EvalRun:
    """Execute a compression eval: the standard runner, with a replay function
    that substitutes the compressed prompt before calling the (same) model.
    Samples that do not carry the exact original prompt are skipped — the eval
    proves the rewrite only on the traffic the lever would actually touch."""
    artifact = artifact_for_recommendation(db, run.recommendation_id)
    if artifact is None:
        run.status = "failed"
        run.error = "no compression artifact linked to this run's recommendation"
        db.commit()
        return run

    async def _replay_with_substitution(messages, params, candidate_model, replay_key):
        substituted, applied = substitute_system_prompt(
            messages or [], artifact.original_system_hash, artifact.compressed_system_prompt
        )
        if not applied:
            return None  # sample does not carry the evaluated prompt: skip
        return await replay_fn(substituted, params, candidate_model, replay_key)

    return await run_eval(
        db,
        run,
        key=key,
        replay_fn=_replay_with_substitution,
        judge_fn=judge_fn,
        now=now,
        source_dataset="compression_replay",
    )
