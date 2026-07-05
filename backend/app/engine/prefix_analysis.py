"""Deterministic prompt-prefix restructuring proposals (D1 follow-through).

The stability detector can already say "this route's prefix churns, so the
provider prompt cache never engages". This module says WHERE: it aligns the
route's captured system prompts, finds the byte-stable head and tail around
the volatile middle, and quantifies what moving that middle to the end would
unlock. The result is a concrete, deterministic proposal — "your first N chars
are stable, a volatile span of ~X-Y chars starts at offset N; moved to the
end, P% of the prompt becomes cache-keyable" — instead of generic advice.

Content rules: prompt text is read from the consented replay corpus and held
in memory only. What persists (on ``Recommendation.details``) is structure —
offsets, lengths, shares, sample counts — never text. This is a proposal for a
human to act on in their own codebase; Varsten does not rewrite prompts here
(a restructuring *transform* would need the full eval/governance/canary path
like D2 compression).
"""

from dataclasses import asdict, dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engine.compression import extract_system_text
from app.models import Project, ReplaySample

# Fewer samples than this and the common-prefix alignment is anecdote, not
# structure; the recommendation then stays generic rather than overclaiming.
MIN_SAMPLES = 5
# A proposal is only worth surfacing when it actually changes the picture:
# the stable head must be under this share (otherwise the prefix is already
# mostly stable) and the projected share after restructuring must clear it.
PROJECTED_SHARE_FLOOR = 0.5
_SAMPLE_LIMIT = 40


@dataclass(frozen=True)
class PrefixProposal:
    """Structure metrics for one route's system prompt. No text, ever."""

    sample_count: int
    median_prompt_chars: int
    stable_prefix_chars: int  # byte-identical head across all samples
    stable_suffix_chars: int  # byte-identical tail across all samples
    stable_prefix_share: float  # head / median length
    volatile_span_offset: int  # where the churn starts (== stable head length)
    volatile_span_min_chars: int
    volatile_span_max_chars: int
    projected_stable_share: float  # (head + tail) / median, if the middle moves to the end

    def as_details(self) -> dict:
        return {"prefix_restructure_proposal": asdict(self)}


def _common_prefix_len(texts: list[str]) -> int:
    shortest = min(texts, key=len)
    for i, ch in enumerate(shortest):
        if any(t[i] != ch for t in texts):
            return i
    return len(shortest)


def analyze_prefix_structure(texts: list[str]) -> PrefixProposal | None:
    """Pure alignment of a route's system prompts into stable head + volatile
    middle + stable tail. Returns None when there is nothing actionable: too
    few samples, prompts already stable, or no stability to be gained."""
    texts = [t for t in texts if t]
    if len(texts) < MIN_SAMPLES:
        return None
    if len(set(texts)) == 1:
        return None  # already byte-stable; the cache, not restructuring, is the answer

    head = _common_prefix_len(texts)
    # The tail may not overlap the head in the shortest sample.
    max_tail = min(len(t) for t in texts) - head
    tail = _common_prefix_len([t[::-1] for t in texts])
    tail = min(tail, max_tail)

    lengths = sorted(len(t) for t in texts)
    median = lengths[len(lengths) // 2]
    if median <= 0:
        return None
    volatile_lengths = [len(t) - head - tail for t in texts]
    projected = min((head + tail) / median, 1.0)
    prefix_share = head / median

    # Only propose when restructuring changes the outcome: an already-stable
    # head needs no proposal, and a projection that stays under the floor
    # would promise work for no unlock.
    if prefix_share >= PROJECTED_SHARE_FLOOR or projected < PROJECTED_SHARE_FLOOR:
        return None

    return PrefixProposal(
        sample_count=len(texts),
        median_prompt_chars=median,
        stable_prefix_chars=head,
        stable_suffix_chars=tail,
        stable_prefix_share=round(prefix_share, 4),
        volatile_span_offset=head,
        volatile_span_min_chars=min(volatile_lengths),
        volatile_span_max_chars=max(volatile_lengths),
        projected_stable_share=round(projected, 4),
    )


def propose_prefix_restructure(db: Session, project: Project, model: str) -> PrefixProposal | None:
    """Analyze the route's captured system prompts from the replay corpus.
    Best-effort: no corpus (capture off) or an analysis surprise degrades to
    None and the recommendation stays generic — never blocks detection."""
    try:
        rows = db.scalars(
            select(ReplaySample.request_messages)
            .where(
                ReplaySample.project_id == project.id,
                ReplaySample.route_key == model,
                ReplaySample.source == "traffic",
            )
            .order_by(ReplaySample.created_at.desc())
            .limit(_SAMPLE_LIMIT)
        ).all()
        texts = [text for messages in rows if (text := extract_system_text(messages)) is not None]
        return analyze_prefix_structure(texts)
    except Exception:
        return None
