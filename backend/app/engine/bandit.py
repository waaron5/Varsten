"""Bandit routing: measured, quality-constrained selection among eval-cleared
candidate models on one route.

When a route has more than one candidate that cleared its shadow eval, a single
static swap leaves money on the table: the best candidate can change over time,
and a newly cleared candidate has no live evidence at all. The bandit picks per
request among the cleared candidates, learning from the same decision ledger the
rest of the engine learns from. No new learning store, no synthetic rewards —
every number the sampler sees is an aggregated ledger fact from the persisted
outcome priors, and every choice it makes lands back in that ledger as a normal
routed decision (model_chosen, realized cost, quality_ok), which the priors
sweep folds back into the stats. The loop is real or it is nothing.

Selection = hard constraints, then a quality-gated exploit/explore split:

1. **Eligibility is decided off-path, not here.** A model only appears in a
   policy's candidate set if its eval cleared (verdict ``safe``, or
   ``needs_human`` plus an approved ChangeRequest) — enforced at add time by
   ``routing.add_bandit_candidate`` — and the drift guard removes it again on
   measured quality/latency regression. The sampler never widens that set.
2. **Quality is a sampled hard floor.** Per candidate, draw
   theta ~ Beta(1 + passes, 1 + fails) from its measured quality counts; a draw
   below ``bandit_quality_floor`` disqualifies the candidate for this request.
   Thompson-style sampling (not the point estimate) means a candidate with
   little data is judged with honest uncertainty rather than a flattering mean.
3. **Exploit on measured savings.** Among quality-cleared candidates with at
   least ``bandit_min_samples`` of evidence, pick the highest posterior-mean
   per-request savings.
4. **Explore under an explicit budget.** With probability
   ``bandit_exploration_budget`` (a hard cap on the traffic share exploration
   may cost), pick uniformly among quality-cleared candidates that still lack
   ``bandit_min_samples`` — that is how a newly cleared candidate accrues live
   evidence without an unbounded gamble.
5. **Fall back to the primary.** No qualifying candidate, no stats, any error:
   the policy's existing single candidate wins, exactly as before the bandit.

Deliberately not Thompson over savings magnitude: the persisted priors carry
mean savings but not variance, and inventing a variance to sample from would be
fake learning. Exploration is explicit and budgeted instead; a savings-variance
column on the priors table can upgrade step 3 to full Thompson later.

The proxy's holdback control arm is assigned *after* this selection and always
stays on the incumbent, so the concurrent baseline (and the honest savings
math) is untouched no matter which candidate the bandit picks.
"""

import random
from dataclasses import dataclass
from decimal import Decimal

from app.core.config import settings

# bandit_routing_mode values.
MODE_OFF = "off"
MODE_SHADOW = "shadow"
MODE_ACTIVE = "active"


@dataclass(frozen=True)
class CandidateStats:
    """Aggregated ledger evidence for one candidate model on one route."""

    model: str
    provider: str
    sample_count: int
    quality_pass_rate: float | None  # measured, 0..1, None = no quality data yet
    average_savings_usd: Decimal | None  # measured mean per-request gross savings


@dataclass(frozen=True)
class BanditChoice:
    """The sampler's pick plus a content-free record of why, for the trace."""

    model: str
    provider: str
    reason: str  # exploit | explore | fallback_primary
    sampled_quality: float | None = None

    def trace_detail(self) -> dict:
        return {
            "chosen_model": self.model,
            "reason": self.reason,
            "sampled_quality": round(self.sampled_quality, 4) if self.sampled_quality is not None else None,
        }


def mode() -> str:
    value = (settings.bandit_routing_mode or MODE_OFF).strip().lower()
    return value if value in {MODE_OFF, MODE_SHADOW, MODE_ACTIVE} else MODE_OFF


def _quality_draw(stats: CandidateStats) -> float:
    """Thompson draw from the candidate's measured quality posterior.

    Beta(1 + passes, 1 + fails) with exposure = sample_count — once the
    candidate has ``bandit_min_samples`` of evidence. Below that the candidate
    is floor-exempt (returns 1.0): with tiny n the sampled posterior is so wide
    that even a perfect candidate fails a 0.95 floor most draws, which silently
    throttles the declared exploration budget for exactly the candidates
    exploration exists to measure (found by the V5 regret simulation, twice: a
    Beta(1,1) cold draw cut the budget twentyfold, and small-n draws created an
    accrual catch-22). A young candidate's real guards are the eval/governance
    clearance at entry, the hard exploration budget bounding its traffic share,
    and the drift guard's confirmed-regression removal. Once evidence is
    sufficient the sampled floor takes over and a measured-bad candidate is
    excluded per request."""
    if stats.quality_pass_rate is None or stats.sample_count < settings.bandit_min_samples:
        return 1.0
    passes = max(0.0, min(1.0, stats.quality_pass_rate)) * stats.sample_count
    fails = stats.sample_count - passes
    return random.betavariate(1 + passes, 1 + fails)  # nosec B311


def select_candidate(
    primary_model: str,
    primary_provider: str,
    candidates: list[CandidateStats],
) -> BanditChoice:
    """Pick this request's routed model among the policy's cleared candidates.

    ``candidates`` should include the primary's own stats when available so the
    exploit step compares it fairly; the primary is also the unconditional
    fallback. Pure and cheap (a few Beta draws); callers own fail-open."""
    if not candidates:
        return BanditChoice(primary_model, primary_provider, reason="fallback_primary")

    floor = settings.bandit_quality_floor
    cleared: list[tuple[CandidateStats, float]] = []
    for stats in candidates:
        draw = _quality_draw(stats)
        if draw >= floor:
            cleared.append((stats, draw))
    if not cleared:
        return BanditChoice(primary_model, primary_provider, reason="fallback_primary")

    # Explicit, budgeted exploration: give under-sampled cleared candidates a
    # bounded share of traffic so they can accrue real evidence.
    unproven = [(stats, draw) for stats, draw in cleared if stats.sample_count < settings.bandit_min_samples]
    if unproven and random.random() < settings.bandit_exploration_budget:  # nosec B311
        stats, draw = random.choice(unproven)  # nosec B311
        return BanditChoice(stats.model, stats.provider, reason="explore", sampled_quality=draw)

    # Exploit: highest measured mean savings among proven, quality-cleared
    # candidates. Ties and missing savings favour the primary via the fallback.
    proven = [
        (stats, draw)
        for stats, draw in cleared
        if stats.sample_count >= settings.bandit_min_samples and stats.average_savings_usd is not None
    ]
    if not proven:
        return BanditChoice(primary_model, primary_provider, reason="fallback_primary")
    best, best_draw = max(proven, key=lambda item: item[0].average_savings_usd or Decimal("0"))
    return BanditChoice(best.model, best.provider, reason="exploit", sampled_quality=best_draw)
