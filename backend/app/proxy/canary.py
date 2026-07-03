"""Canary ramp for policy activation.

A routing or trim policy does not have to go from off to 100% of traffic in one
step. When canary mode is on, activation starts the policy at a small rollout
percent and the drift sweep promotes it one stage at a time -- 10 -> 50 -> 100 --
only after each stage has accumulated enough holdback signal with no quality or
latency regression. A regression at any stage rolls the whole policy back through
the normal drift path.

Two independence rules keep the statistics honest:

- The rollout draw (is this request subject to the policy at all?) is a separate
  random draw from the holdback arm assignment (control vs treatment). A request
  outside the rollout is plain passthrough and is never tagged as an experiment
  arm, so it cannot pollute the A/B.
- Promotion is gated on the same peeking-safe confidence sequences the drift
  guard already computes, so ramping up is as evidence-driven as rolling back.

This module is pure policy: the random draw and the stage arithmetic. The sweep
(app/proxy/drift.py) owns when promotion is evaluated; resolve_route/resolve_trim
own the per-request gate.
"""

import random

from app.core.config import settings

# A fully-live policy: the gate is a no-op, matching pre-canary behaviour.
FULLY_LIVE = 100


def initial_rollout_percent() -> int:
    """The rollout percent a freshly activated policy starts at. Canary off ->
    fully live immediately (unchanged behaviour); canary on -> the configured
    starting stage."""
    if not settings.canary_enabled:
        return FULLY_LIVE
    return max(1, min(FULLY_LIVE, settings.canary_initial_percent))


def in_rollout(rollout_percent: int | None) -> bool:
    """Whether this request falls inside the policy's current rollout.

    A fully-live (100) or missing value always returns True, so the gate costs
    nothing for a policy that is not being canaried. The draw is statistical, not
    security-sensitive."""
    pct = FULLY_LIVE if rollout_percent is None else rollout_percent
    if pct >= FULLY_LIVE:
        return True
    if pct <= 0:
        return False
    return random.random() * 100.0 < pct  # nosec B311


def next_stage(current: int) -> int | None:
    """The next rollout stage above ``current``, or None when already fully live.

    Stages are the configured ramp; anything at or above the last stage is done."""
    for stage in settings.canary_stages:
        if stage > current:
            return stage
    return None
