"""Always-valid sequential inference for the live holdback.

The holdback A/B is monitored continuously: every dashboard load and every
drift sweep re-reads the same accumulating arms. A fixed-sample 95% CI (the
z = 1.96 interval the proxy used to compute) does not survive that. Under
continuous peeking, the probability that a fixed interval excludes the truth at
*some* look grows far past 5% -- the textbook "peeking" problem. Both the
auto-rollback trigger and the billed savings number rest on that error control,
so a fixed interval consulted continuously is quietly wrong.

This module replaces the fixed interval with a time-uniform *confidence
sequence* (CS): an interval valid simultaneously at every sample size, so a
reader may stop and look whenever they like without inflating error. A CS that
excludes zero is honest evidence of an effect no matter how many times it was
checked.

The construction is the asymptotic confidence sequence (AsympCS) of
Waudby-Smith, Arbour, Sinha, Kennedy & Ramdas (2023), "Time-uniform central
limit theory and asymptotic confidence sequences." It is the CLT interval with
a slowly growing (log-log) correction, needs only the running count, mean, and
variance per arm -- exactly what the ledger already aggregates -- and handles
the unbounded, right-skewed per-request cost distribution the old normal
interval was already assuming. Width grows like sqrt(log n) relative to the
pointwise interval; that widening is the price of validity under peeking.

The correctness contract here is behavioural, not formula-level. See
``tests/test_sequential_inference.py``, which asserts time-uniform coverage,
power, and monotone shrinkage by simulation. The closed form below may change
only if those properties still hold.

Nothing in this module touches the database or the request path; it is pure
arithmetic over already-aggregated statistics, and deliberately depends on the
standard library only (no numpy) so it stays cheap to import anywhere.
"""

import math
from typing import NamedTuple


class ConfidenceSequence(NamedTuple):
    """A time-uniform interval for a difference of means.

    ``point`` is the difference estimate; ``lo``/``hi`` are the confidence
    sequence bounds valid simultaneously across all sample sizes."""

    point: float
    lo: float
    hi: float

    @property
    def excludes_zero(self) -> bool:
        return self.lo > 0.0 or self.hi < 0.0

    def exceeds(self, threshold: float) -> bool:
        """True when the whole interval sits above ``threshold`` -- i.e. we are
        confident the true difference is larger than it, not merely that a noisy
        point estimate was. This is the peeking-safe analogue of ``point >
        threshold``."""
        return self.lo > threshold


def rho_for_target(target_n: float, alpha: float) -> float:
    """Tuning parameter that makes the sequence tightest near ``target_n``.

    The width-optimal choice from Waudby-Smith et al. (2023). The CS is valid
    for every n regardless of this value; it only shifts where the interval is
    narrowest, so set it near the sample size at which decisions are typically
    made (a few hundred for our routes)."""
    target_n = max(float(target_n), 1.0)
    return math.sqrt((-2.0 * math.log(alpha) + math.log(-2.0 * math.log(alpha) + 1.0)) / target_n)


def boundary_multiplier(n: float, rho: float, alpha: float) -> float:
    """The time-uniform analogue of the fixed-n normal quantile (z = 1.96 at
    95%). Multiply a standard error by this to get a confidence-sequence
    half-width. Grows like sqrt(log n): the cost of monitoring continuously."""
    n_rho2 = n * rho * rho
    return math.sqrt((2.0 * (n_rho2 + 1.0) / n_rho2) * math.log(math.sqrt(n_rho2 + 1.0) / alpha))


def difference_confidence_sequence(
    n_a: int,
    mean_a: float,
    var_a: float | None,
    n_b: int,
    mean_b: float,
    var_b: float | None,
    *,
    alpha: float,
    target_n: float,
) -> ConfidenceSequence | None:
    """A (1 - alpha) confidence sequence for ``mean_a - mean_b``, valid at all n.

    ``var_a``/``var_b`` are the arms' sample variances. Returns ``None`` when an
    arm has fewer than two samples or the pooled standard error is degenerate
    (zero/negative variance) -- callers fall back to the bare point estimate,
    which is the pre-existing behaviour when an arm lacked variance."""
    if n_a < 2 or n_b < 2 or var_a is None or var_b is None:
        return None
    se2 = var_a / n_a + var_b / n_b
    if se2 <= 0.0:
        return None
    rho = rho_for_target(target_n, alpha)
    radius = math.sqrt(se2) * boundary_multiplier(n_a + n_b, rho, alpha)
    point = mean_a - mean_b
    return ConfidenceSequence(point, point - radius, point + radius)


def mean_confidence_sequence(
    n: int,
    mean: float,
    var: float | None,
    *,
    alpha: float,
    target_n: float,
) -> ConfidenceSequence | None:
    """A (1 - alpha) confidence sequence for a single mean, valid at all n.

    Used for absolute thresholds -- e.g. "is the treatment arm's mean latency
    confidently above this SLO" -- where there is no second arm to difference
    against. Returns ``None`` when the sample is too small or has no dispersion."""
    if n < 2 or var is None or var <= 0.0:
        return None
    rho = rho_for_target(target_n, alpha)
    radius = math.sqrt(var / n) * boundary_multiplier(n, rho, alpha)
    return ConfidenceSequence(mean, mean - radius, mean + radius)


def rate_difference_confidence_sequence(
    n_a: int,
    successes_a: float,
    n_b: int,
    successes_b: float,
    *,
    alpha: float,
    target_n: float,
) -> ConfidenceSequence | None:
    """A confidence sequence for the difference of two [0, 1] success rates.

    Laplace (Beta(1, 1)) smoothing keeps each arm's variance non-degenerate when
    it is all-pass or all-fail, so a maximal split still yields a bounded,
    actionable interval once enough samples accumulate, instead of the zero
    sample variance that would otherwise make the interval undefined."""
    if n_a < 2 or n_b < 2:
        return None
    p_a = (successes_a + 1.0) / (n_a + 2.0)
    p_b = (successes_b + 1.0) / (n_b + 2.0)
    return difference_confidence_sequence(
        n_a,
        p_a,
        p_a * (1.0 - p_a),
        n_b,
        p_b,
        p_b * (1.0 - p_b),
        alpha=alpha,
        target_n=target_n,
    )
