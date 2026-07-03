"""Behavioural spec for the always-valid confidence sequence (slice B1).

Correctness for sequential inference is a property, not a formula. A fixed 95%
CI consulted continuously would inflate its false-positive rate far past 5%, so
these simulations assert the three properties the production math in
``app/proxy/sequential.py`` must hold:

1. time-uniform coverage -- under the null, the probability the sequence *ever*
   excludes zero across a whole monitoring run stays at (or below) the nominal
   level, no matter how many times it is peeked at;
2. power -- a real effect is detected in a reasonable number of samples;
3. monotone shrinkage -- the interval tightens as evidence accumulates.

The closed form may change freely as long as these still pass. Do not weaken the
thresholds to make a broken implementation green.

Runs are vectorised with numpy for speed; ``_diff_cs_vec`` mirrors the scalar
production function and is kept faithful by ``test_vectorized_helper_matches_production``,
so the coverage/power/shrinkage assertions certify the real code, not a copy.
"""

from itertools import pairwise

import pytest

np = pytest.importorskip("numpy")

from app.core.config import settings  # noqa: E402  (after importorskip guard)
from app.proxy.sequential import (  # noqa: E402
    boundary_multiplier,
    difference_confidence_sequence,
    rho_for_target,
)

ALPHA = settings.sequential_cs_alpha
TARGET_N = settings.sequential_cs_target_n

# Realistic per-request cost: right-skewed, a couple of cents, in dollars.
_COST_LOG_MEAN = np.log(0.02)
_COST_LOG_SD = 0.6


def _diff_cs_vec(n_a, mean_a, var_a, n_b, mean_b, var_b, alpha, target_n):
    """Vectorised mirror of sequential.difference_confidence_sequence.

    ``n_a``/``n_b`` are scalars (the same sample size across all simulated
    experiments at a given checkpoint); the mean/var arguments are arrays over
    experiments. Returns (point, lo, hi) arrays."""
    rho = rho_for_target(target_n, alpha)
    se2 = var_a / n_a + var_b / n_b
    n_rho2 = (n_a + n_b) * rho * rho
    mult = np.sqrt((2.0 * (n_rho2 + 1.0) / n_rho2) * np.log(np.sqrt(n_rho2 + 1.0) / alpha))
    radius = np.sqrt(se2) * mult
    point = mean_a - mean_b
    return point, point - radius, point + radius


def _checkpoints(low, high, count=40):
    """A geometric grid of sample sizes. Continuous monitoring is approximated
    by a dense log-spaced grid, standard in confidence-sequence simulation
    studies: the ever-cross event is evaluated at every grid point."""
    grid = np.unique(np.geomspace(low, high, count).round().astype(int))
    return [int(n) for n in grid if n >= low]


def _running_mean_var(cumsum, cumsum_sq, n):
    mean = cumsum[:, n - 1] / n
    var = (cumsum_sq[:, n - 1] - n * mean * mean) / (n - 1)
    return mean, var


def test_vectorized_helper_matches_production():
    rng = np.random.default_rng(1)
    for _ in range(300):
        n_a = int(rng.integers(2, 500))
        n_b = int(rng.integers(2, 500))
        mean_a = float(rng.normal(0.1, 0.05))
        mean_b = float(rng.normal(0.1, 0.05))
        var_a = float(rng.uniform(1e-4, 1e-1))
        var_b = float(rng.uniform(1e-4, 1e-1))
        prod = difference_confidence_sequence(n_a, mean_a, var_a, n_b, mean_b, var_b, alpha=ALPHA, target_n=TARGET_N)
        point, lo, hi = _diff_cs_vec(
            n_a, np.array([mean_a]), np.array([var_a]), n_b, np.array([mean_b]), np.array([var_b]), ALPHA, TARGET_N
        )
        assert prod is not None
        assert np.isclose(prod.point, point[0])
        assert np.isclose(prod.lo, lo[0])
        assert np.isclose(prod.hi, hi[0])


def test_boundary_multiplier_exceeds_fixed_quantile():
    # The time-uniform multiplier is strictly wider than the fixed-n z=1.96 at
    # every sample size -- that extra width is what buys validity under peeking --
    # and is tightest near the tuning target (U-shaped in n, not monotone).
    rho = rho_for_target(TARGET_N, ALPHA)
    m_low = boundary_multiplier(30, rho, ALPHA)
    m_target = boundary_multiplier(TARGET_N, rho, ALPHA)
    m_high = boundary_multiplier(5000, rho, ALPHA)
    assert m_low > 1.96
    assert m_target > 1.96
    assert m_high > 1.96
    assert m_target <= m_low
    assert m_target <= m_high


def test_time_uniform_coverage_under_null():
    rng = np.random.default_rng(20260702)
    n_sim, max_n = 2000, 2000
    a = rng.lognormal(_COST_LOG_MEAN, _COST_LOG_SD, size=(n_sim, max_n))
    b = rng.lognormal(_COST_LOG_MEAN, _COST_LOG_SD, size=(n_sim, max_n))
    csa, csa2 = np.cumsum(a, axis=1), np.cumsum(a * a, axis=1)
    csb, csb2 = np.cumsum(b, axis=1), np.cumsum(b * b, axis=1)

    ever_cross = np.zeros(n_sim, dtype=bool)
    for n in _checkpoints(30, max_n):
        mean_a, var_a = _running_mean_var(csa, csa2, n)
        mean_b, var_b = _running_mean_var(csb, csb2, n)
        _, lo, hi = _diff_cs_vec(n, mean_a, var_a, n, mean_b, var_b, ALPHA, TARGET_N)
        ever_cross |= (lo > 0.0) | (hi < 0.0)

    # Nominal level is 5%; allow simulation slack. A fixed 1.96-sigma interval
    # peeked at ~35 checkpoints would cross well above 20% here.
    rate = float(ever_cross.mean())
    assert rate <= 0.06, f"cumulative type-I {rate:.4f} exceeds 0.06 (peeking not controlled)"


def test_power_under_real_effect():
    rng = np.random.default_rng(7)
    n_sim, n = 1000, 2000
    control = rng.lognormal(_COST_LOG_MEAN, _COST_LOG_SD, size=(n_sim, n))
    # Treatment is 30% cheaper in expectation (a real routing/downshift saving).
    treatment = rng.lognormal(_COST_LOG_MEAN + np.log(0.7), _COST_LOG_SD, size=(n_sim, n))

    mean_c, var_c = control.mean(axis=1), control.var(axis=1, ddof=1)
    mean_t, var_t = treatment.mean(axis=1), treatment.var(axis=1, ddof=1)
    _, lo, _ = _diff_cs_vec(n, mean_c, var_c, n, mean_t, var_t, ALPHA, TARGET_N)

    # Savings = control - treatment > 0: the sequence should sit entirely above 0.
    detected = float((lo > 0.0).mean())
    assert detected >= 0.95, f"power {detected:.3f} below 0.95 by n={n}"


def test_width_shrinks_monotonically():
    rng = np.random.default_rng(3)
    n_sim, max_n = 500, 2000
    a = rng.lognormal(_COST_LOG_MEAN, _COST_LOG_SD, size=(n_sim, max_n))
    b = rng.lognormal(_COST_LOG_MEAN, _COST_LOG_SD, size=(n_sim, max_n))
    csa, csa2 = np.cumsum(a, axis=1), np.cumsum(a * a, axis=1)
    csb, csb2 = np.cumsum(b, axis=1), np.cumsum(b * b, axis=1)

    widths = []
    for n in _checkpoints(30, max_n):
        mean_a, var_a = _running_mean_var(csa, csa2, n)
        mean_b, var_b = _running_mean_var(csb, csb2, n)
        _, lo, hi = _diff_cs_vec(n, mean_a, var_a, n, mean_b, var_b, ALPHA, TARGET_N)
        widths.append(float(np.mean(hi - lo)))

    # Mean interval width must be non-increasing as evidence accumulates (small
    # relative slack for Monte Carlo noise between checkpoints).
    for earlier, later in pairwise(widths):
        assert later <= earlier * 1.001, f"width grew: {earlier:.6f} -> {later:.6f}"
