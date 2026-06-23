"""Period-resolver boundaries.

The dashboard's deltas and period toggle stand on these windows, so the math is
pinned here: month/quarter/year anchors, the same-elapsed prior window, the
clamp that stops a long current month reading past a short prior month, and
leap-year safety. Pure function, no DB.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.periods import resolve_period


def _dt(y: int, m: int, d: int, hh: int = 12) -> datetime:
    return datetime(y, m, d, hh, 0, 0, tzinfo=UTC)


def test_month_window_and_prior_same_elapsed():
    now = _dt(2026, 6, 19)  # 18 days 12h into June
    w = resolve_period(now, "month")
    assert w.start == _dt(2026, 6, 1, 0)
    assert w.end == now
    assert w.prev_start == _dt(2026, 5, 1, 0)
    # Same elapsed duration into May (which is long enough, no clamp).
    assert w.prev_end == _dt(2026, 5, 1, 0) + (now - _dt(2026, 6, 1, 0))
    assert w.prev_end == _dt(2026, 5, 19)
    assert w.granularity == "day"


def test_quarter_window_anchors_to_quarter_start():
    now = _dt(2026, 6, 19)  # Q2
    w = resolve_period(now, "quarter")
    assert w.start == _dt(2026, 4, 1, 0)
    assert w.prev_start == _dt(2026, 1, 1, 0)  # Q1
    assert w.granularity == "week"


def test_quarter_q1_prior_is_previous_year_q4():
    now = _dt(2026, 2, 10)  # Q1 2026
    w = resolve_period(now, "quarter")
    assert w.start == _dt(2026, 1, 1, 0)
    assert w.prev_start == _dt(2025, 10, 1, 0)  # Q4 2025


def test_year_window_and_prior_year():
    now = _dt(2026, 6, 19)
    w = resolve_period(now, "year")
    assert w.start == _dt(2026, 1, 1, 0)
    assert w.prev_start == _dt(2025, 1, 1, 0)
    assert w.granularity == "month"


def test_prior_window_is_clamped_to_prior_period_end():
    # March 31: 30 days into March. February 2026 has only 28 days, so the same
    # elapsed duration would spill into March -- it must clamp to the full prior
    # period (Feb 1 .. Mar 1), never past it.
    now = _dt(2026, 3, 31)
    w = resolve_period(now, "month")
    assert w.prev_start == _dt(2026, 2, 1, 0)
    assert w.prev_end == w.start == _dt(2026, 3, 1, 0)
    # Clamped prior window is at most one full prior month long.
    assert w.prev_end - w.prev_start <= timedelta(days=29)


def test_leap_year_february_prior_window():
    now = _dt(2024, 3, 28)  # 27 days into March 2024
    w = resolve_period(now, "month")
    # Feb 2024 has 29 days, so 27d12h fits with no clamp.
    assert w.prev_start == _dt(2024, 2, 1, 0)
    assert w.prev_end == _dt(2024, 2, 1, 0) + (now - _dt(2024, 3, 1, 0))
    assert w.prev_end < w.start


def test_naive_now_is_treated_as_utc():
    naive = datetime(2026, 6, 19, 12, 0, 0)
    w = resolve_period(naive, "month")
    assert w.start.tzinfo is not None
    assert w.end == naive.replace(tzinfo=UTC)


def test_start_of_period_yields_empty_to_date_window():
    now = _dt(2026, 6, 1, 0)  # the first instant of the month
    w = resolve_period(now, "month")
    assert w.start == w.end  # nothing has elapsed yet -> empty current window
    assert w.prev_start == w.prev_end  # and an empty prior window


def test_prior_window_runs_over_the_prior_range():
    w = resolve_period(_dt(2026, 6, 19), "month")
    p = w.prior()
    assert p.start == w.prev_start
    assert p.end == w.prev_end
    assert p.period == w.period
    assert p.granularity == w.granularity


def test_unknown_period_raises():
    with pytest.raises(ValueError):
        resolve_period(_dt(2026, 6, 19), "week")  # type: ignore[arg-type]
