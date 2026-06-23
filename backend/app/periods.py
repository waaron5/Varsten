"""Period windows for the dashboard's period-scoped reads.

Resolves a named period (month / quarter / year) into an explicit, UTC,
*to-date* window plus the *same-elapsed* prior-period window that the KPI deltas
compare against. Pure and deterministic: pass ``now``, get back the boundaries.
No DB and no I/O, so it is unit-tested in isolation and reused by every
period-scoped read (savings, breakdown, data-quality, the consolidated
dashboard) -- one definition of "this period" so the panels cannot drift.

The prior window is the same *duration* into the previous period, clamped so it
never spills past the previous period's end. That is the apples-to-apples
comparison a CFO trusts: day 1..N of this period vs day 1..N of the last one,
never a partial window measured against a full one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

Period = Literal["month", "quarter", "year"]
Granularity = Literal["day", "week", "month"]

# Chart bucket size per period: daily bars for a month, weekly for a quarter,
# monthly for a year -- keeps the bar count readable as the window widens.
_GRANULARITY: dict[Period, Granularity] = {"month": "day", "quarter": "week", "year": "month"}


@dataclass(frozen=True)
class PeriodWindow:
    """An explicit, UTC, to-date window and its same-elapsed prior window.

    All bounds are half-open ``[start, end)`` so day buckets never double-count a
    boundary instant. ``end`` is ``now`` (the to-date edge), not the period's
    calendar end -- the dashboard reports what has happened, not a full-period
    projection.
    """

    period: Period
    start: datetime  # inclusive: 00:00 UTC on the first day of the period
    end: datetime  # exclusive: now (the to-date edge)
    prev_start: datetime  # inclusive: 00:00 UTC on the first day of the prior period
    prev_end: datetime  # exclusive: same elapsed duration into the prior period (clamped to < start)
    granularity: Granularity

    @property
    def elapsed(self) -> timedelta:
        return self.end - self.start

    def prior(self) -> PeriodWindow:
        """The same-elapsed prior window expressed as a window in its own right, so
        the savings core can run over it unchanged for the KPI deltas. Its own prior
        bounds collapse to empty -- delta math only needs one level of comparison."""
        return PeriodWindow(
            period=self.period,
            start=self.prev_start,
            end=self.prev_end,
            prev_start=self.prev_start,
            prev_end=self.prev_start,
            granularity=self.granularity,
        )


def _midnight(dt: datetime) -> datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def _month_start(dt: datetime) -> datetime:
    return _midnight(dt).replace(day=1)


def _quarter_start(dt: datetime) -> datetime:
    first_month = ((dt.month - 1) // 3) * 3 + 1
    return _midnight(dt).replace(month=first_month, day=1)


def _year_start(dt: datetime) -> datetime:
    return _midnight(dt).replace(month=1, day=1)


def _period_start(now: datetime, period: Period) -> datetime:
    if period == "month":
        return _month_start(now)
    if period == "quarter":
        return _quarter_start(now)
    if period == "year":
        return _year_start(now)
    raise ValueError(f"unknown period: {period!r}")


def _previous_start(start: datetime, period: Period) -> datetime:
    # ``start`` is the first instant of the current period; stepping back one day
    # lands inside the previous period, then re-anchoring gives its start. For a
    # year that is just the prior calendar year.
    if period == "year":
        return start.replace(year=start.year - 1)
    return _period_start(start - timedelta(days=1), period)


def resolve_period(now: datetime, period: Period = "month") -> PeriodWindow:
    """Resolve ``period`` as of ``now`` into a :class:`PeriodWindow`.

    Naive ``now`` is treated as UTC. The current window is ``[start, now)``; the
    prior window is ``[prev_start, prev_start + elapsed)`` clamped to ``< start``
    so a long current month (e.g. day 30) never reads into the month after a
    short prior month (e.g. February) -- it tops out at the full prior period.
    """
    now = now.astimezone(UTC) if now.tzinfo is not None else now.replace(tzinfo=UTC)
    start = _period_start(now, period)
    prev_start = _previous_start(start, period)
    elapsed = now - start
    prev_end = min(prev_start + elapsed, start)
    return PeriodWindow(
        period=period,
        start=start,
        end=now,
        prev_start=prev_start,
        prev_end=prev_end,
        granularity=_GRANULARITY[period],
    )
