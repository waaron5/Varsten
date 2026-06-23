"""Realized-savings accounting.

When a recommendation is applied, Varsten records the savings it claims so the
Proof section reports numbers that trace back to a real recommendation, derived
from real usage and real pricing, rather than seeded constants.

v1 honesty: savings are the recommendation's run-rate *estimate*, labelled with
its measurement_method. A true randomized-holdback measurement (the product
guide's destination) needs elapsed time and is deferred. But the entire chain
here is computed, never hard-coded.
"""

import calendar
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import TypedDict

from sqlalchemy import Numeric, cast, func, select
from sqlalchemy.orm import Session

from app.levers import LEVER_DISPLAY_ORDER
from app.models import (
    LeverConfig,
    Project,
    Recommendation,
    RecommendationAction,
    SavingsAttribution,
    UsageEvent,
)
from app.periods import PeriodWindow
from app.savings_measurement import (
    METHOD_ESTIMATED,
    compute_verified_savings,
    direct_measured_by_lever,
    is_measured,
)

_CENTS = Decimal("0.01")


def org_fee_percent(project: Project) -> Decimal:
    """Varsten's gain-share fraction for this project's org. The single source of
    truth is ``organizations.gain_share_percent`` (per-org, default 0.25); never a
    hard-coded rate. ``billing.py`` reads the same column for invoicing, so the
    fee a customer sees on the dashboard matches the fee they are billed."""
    return Decimal(project.organization.gain_share_percent)


class SavingsSummary(TypedDict):
    period_start: datetime
    period_end: datetime
    actual_spend_usd: Decimal
    # NOTE: the gross/fee/net/counterfactual fields below are the ESTIMATED impact
    # of applied optimizations, derived from recommendation estimates. They are NOT
    # measured savings and must never be presented as "saved" — see the verified_*
    # fields, which are the audited number. Kept under these names for backward
    # compatibility with existing read paths.
    counterfactual_spend_usd: Decimal
    gross_savings_usd: Decimal
    varsten_fee_usd: Decimal
    net_savings_usd: Decimal
    # Estimated opportunity still on the table (open, not-yet-applied recommendations).
    estimated_opportunity_usd: Decimal
    # Verified (measured) savings — direct + holdback, from the ledger. The honest
    # "saved" number, with the fee and net Varsten can actually bill.
    direct_measured_usd: Decimal
    holdback_measured_usd: Decimal
    holdback_ci_low_usd: Decimal
    holdback_ci_high_usd: Decimal
    holdback_has_signal: bool
    verified_savings_usd: Decimal
    verified_fee_usd: Decimal
    verified_net_usd: Decimal
    billable_savings_usd: Decimal


def month_start(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def month_end(now: datetime) -> datetime:
    return (month_start(now) + timedelta(days=32)).replace(day=1) - timedelta(seconds=1)


def _q(value: Decimal) -> Decimal:
    return Decimal(value).quantize(_CENTS, rounding=ROUND_HALF_UP)


def _refresh_lever_savings(
    db: Session,
    project: Project,
    lever: str,
    period_start: datetime,
    period_end: datetime,
) -> None:
    """Set the lever's savings-to-date to the sum of its attributed savings this
    period, so the Levers screen never shows an invented number."""
    total = db.scalar(
        select(func.coalesce(func.sum(SavingsAttribution.gross_savings_usd), 0)).where(
            SavingsAttribution.project_id == project.id,
            SavingsAttribution.lever == lever,
            SavingsAttribution.period_start == period_start,
            SavingsAttribution.period_end == period_end,
        )
    ) or Decimal("0")
    config = db.scalar(select(LeverConfig).where(LeverConfig.project_id == project.id, LeverConfig.lever == lever))
    if config is not None:
        config.savings_to_date_usd = _q(total)


def record_applied_savings(
    db: Session,
    project: Project,
    recommendation: Recommendation,
    *,
    actor_user_id: uuid.UUID | None = None,
    source: str = "user",
    now: datetime | None = None,
) -> SavingsAttribution | None:
    """Record applying a recommendation: an action row (always) plus, when the
    recommendation carries a measurable lever savings, a savings attribution and a
    refreshed lever total. Returns the attribution, or None for a governance /
    unpriced recommendation that has no dollar lever savings to attribute."""
    now = now or datetime.now(UTC)
    start = month_start(now)
    end = month_end(now)
    gross_raw = recommendation.estimated_monthly_savings_usd

    action = RecommendationAction(
        organization_id=project.organization_id,
        project_id=project.id,
        recommendation_id=recommendation.id,
        actor_user_id=actor_user_id,
        lever=recommendation.lever,
        action_type="applied",
        status="completed",
        source=source,
        title=recommendation.title,
        estimated_savings_usd=gross_raw,
        occurred_at=now,
    )
    db.add(action)

    if recommendation.lever is None or gross_raw is None or gross_raw <= 0:
        return None

    gross = _q(gross_raw)
    fee = _q(gross * org_fee_percent(project))
    net = gross - fee

    # One attribution per (lever, period): re-applying refreshes it rather than
    # stacking duplicate savings.
    attribution = db.scalar(
        select(SavingsAttribution).where(
            SavingsAttribution.project_id == project.id,
            SavingsAttribution.lever == recommendation.lever,
            SavingsAttribution.period_start == start,
            SavingsAttribution.period_end == end,
        )
    )
    method = recommendation.measurement_method or METHOD_ESTIMATED
    # A row is "measured" only when its method is one of the measured methods
    # (replay/holdback/direct). Otherwise it is honestly an estimate.
    row_status = "measured" if is_measured(method) else "estimated"
    if attribution is None:
        attribution = SavingsAttribution(
            organization_id=project.organization_id,
            project_id=project.id,
            lever=recommendation.lever,
            measurement_method=method,
            status=row_status,
            period_start=start,
            period_end=end,
        )
        db.add(attribution)

    attribution.recommendation_id = recommendation.id
    attribution.measurement_method = method
    attribution.status = row_status
    attribution.gross_savings_usd = gross
    attribution.varsten_fee_usd = fee
    attribution.net_savings_usd = net
    attribution.confidence_low_usd = _q(gross * Decimal("0.80"))
    attribution.confidence_high_usd = _q(gross * Decimal("1.15"))
    attribution.notes = f"Derived from recommendation {recommendation.id} ({recommendation.measurement_method})."
    action.realized_savings_usd = net

    db.flush()
    _refresh_lever_savings(db, project, recommendation.lever, start, end)
    return attribution


def compute_savings_summary(db: Session, project: Project, now: datetime | None = None) -> SavingsSummary:
    """The month's savings accounting, derived end to end:

    actual          = month-to-date spend, run-rated to the full month
    gross           = sum of attributed lever savings this month
    counterfactual  = actual + gross (what spend would have been without the cuts)
    fee / net       = Varsten fee and the customer's net, from the attributions

    No value here is hard-coded; every number traces to usage events and applied
    recommendations.
    """
    now = now or datetime.now(UTC)
    start = month_start(now)
    end = month_end(now)

    actual_mtd = db.scalar(
        select(func.coalesce(func.sum(UsageEvent.cost_usd), 0)).where(
            UsageEvent.project_id == project.id, UsageEvent.received_at >= start
        )
    ) or Decimal("0")
    days_in_month = calendar.monthrange(now.year, now.month)[1]
    actual = _q(Decimal(actual_mtd) / Decimal(now.day) * Decimal(days_in_month)) if now.day else Decimal("0")

    agg = db.execute(
        select(
            func.coalesce(func.sum(SavingsAttribution.gross_savings_usd), 0).label("gross"),
            func.coalesce(func.sum(SavingsAttribution.varsten_fee_usd), 0).label("fee"),
            func.coalesce(func.sum(SavingsAttribution.net_savings_usd), 0).label("net"),
        ).where(
            SavingsAttribution.project_id == project.id,
            SavingsAttribution.period_start == start,
            SavingsAttribution.period_end == end,
        )
    ).one()
    gross = _q(agg.gross)
    fee = _q(agg.fee)
    net = _q(agg.net)

    # Estimated opportunity still open (not yet applied). Clearly an estimate.
    opportunity = db.scalar(
        select(func.coalesce(func.sum(Recommendation.estimated_monthly_savings_usd), 0)).where(
            Recommendation.project_id == project.id,
            Recommendation.status == "open",
        )
    ) or Decimal("0")

    # Verified (measured) savings from the ledger. This is the audited "saved"
    # number; the fee is charged on it (billable), never on the estimate.
    verified = compute_verified_savings(db, project.id, start, end)
    verified_gross = verified["verified_savings_usd"]
    verified_fee = _q(verified_gross * org_fee_percent(project))
    verified_net = verified_gross - verified_fee

    return {
        "period_start": start,
        "period_end": now,
        "actual_spend_usd": actual,
        "counterfactual_spend_usd": actual + gross,
        "gross_savings_usd": gross,
        "varsten_fee_usd": fee,
        "net_savings_usd": net,
        "estimated_opportunity_usd": _q(opportunity),
        "direct_measured_usd": verified["direct_measured_usd"],
        "holdback_measured_usd": verified["holdback_measured_usd"],
        "holdback_ci_low_usd": verified["holdback_ci_low_usd"],
        "holdback_ci_high_usd": verified["holdback_ci_high_usd"],
        "holdback_has_signal": verified["holdback_has_signal"],
        "verified_savings_usd": verified_gross,
        "verified_fee_usd": verified_fee,
        "verified_net_usd": verified_net,
        "billable_savings_usd": verified_gross,
    }


# --- Window-scoped, reconciling savings (the dashboard's single source) --------
#
# compute_savings_summary above is month-anchored and run-rates ``actual``; the
# function below is the integrity spine for the consolidated dashboard. It takes
# an explicit PeriodWindow and returns numbers that reconcile by construction:
#
#     gross == sum(by_lever)            (one savings source, split per lever)
#     counterfactual == actual + gross  (what you'd have paid == paid + avoided)
#     sum(measured_savings_series.saved) == gross   (the chart sums to the KPI)
#
# ``actual`` is period-to-date (never run-rated), so the chart and the KPI cover
# the same window. The coherence rule: report MEASURED savings where the ledger
# has them, otherwise the clearly-labelled ESTIMATE, never both summed together.

# Stable lever display order, mirroring the engine/lever vocabulary.
_LEVER_KEYS = LEVER_DISPLAY_ORDER

# Ledger saved_usd. By construction (see proxy/ledger.py) it is written only on a
# cache hit, a routed treatment event, or a batch -- each a real avoided cost. The
# daily chart sums all of them, matching the dashboard gross (which counts routed
# holdback treatment via include_holdback_treatment=True), so chart/lever/gross
# reconcile exactly. (Control-arm holdback events carry no saved_usd.)
_SAVED = cast(UsageEvent.event_metadata["saved_usd"].astext, Numeric(20, 12))


class WindowSavings(TypedDict):
    period: str
    period_start: datetime
    period_end: datetime
    mode: str  # "measured" | "estimated" | "spend_only" | "empty"
    actual_spend_usd: Decimal | None
    gross_savings_usd: Decimal | None
    varsten_fee_usd: Decimal | None
    net_savings_usd: Decimal | None
    counterfactual_spend_usd: Decimal | None
    by_lever: dict[str, Decimal]
    by_lever_source: str  # "measured" | "estimated" | ""
    # Verified provenance (always measured, surfaced for Proof). Holdback is an
    # interval estimate and is reported here, never folded into the per-day chart.
    direct_measured_usd: Decimal
    holdback_measured_usd: Decimal
    holdback_ci_low_usd: Decimal
    holdback_ci_high_usd: Decimal
    holdback_has_signal: bool
    estimated_opportunity_usd: Decimal
    fee_percent: Decimal


def _window_request_count(db: Session, project: Project, window: PeriodWindow) -> int:
    return (
        db.scalar(
            select(func.count()).where(
                UsageEvent.project_id == project.id,
                UsageEvent.received_at >= window.start,
                UsageEvent.received_at < window.end,
            )
        )
        or 0
    )


def _window_actual_spend(db: Session, project: Project, window: PeriodWindow) -> Decimal:
    total = db.scalar(
        select(func.coalesce(func.sum(UsageEvent.cost_usd), 0)).where(
            UsageEvent.project_id == project.id,
            UsageEvent.received_at >= window.start,
            UsageEvent.received_at < window.end,
        )
    )
    return Decimal(total or 0)


def _estimated_by_lever(db: Session, project: Project, window: PeriodWindow) -> dict[str, Decimal]:
    """Estimated savings per lever from the attributions whose period falls in the
    window. Used only as the fallback when the ledger has no measured savings."""
    rows = db.execute(
        select(
            SavingsAttribution.lever,
            func.coalesce(func.sum(SavingsAttribution.gross_savings_usd), 0).label("gross"),
        )
        .where(
            SavingsAttribution.project_id == project.id,
            SavingsAttribution.period_start >= window.start,
            SavingsAttribution.period_start < window.end,
        )
        .group_by(SavingsAttribution.lever)
    ).all()
    return {row.lever: Decimal(row.gross) for row in rows if row.lever and Decimal(row.gross) != 0}


def _fee_on(gross: Decimal, percent: Decimal) -> Decimal:
    """Gain-share fee on a gross figure, capped at the gross so net stays >= 0. The
    monthly floor is a billing-period concept and is deliberately excluded from a
    to-date display number so the fee is never overstated mid-period."""
    return min(_q(gross * percent), _q(gross))


def compute_savings_for_window(
    db: Session,
    project: Project,
    window: PeriodWindow,
    fee_percent: Decimal | None = None,
) -> WindowSavings:
    """The dashboard's reconciling savings for ``window``. See the module note for
    the invariants this guarantees. Returns nulls (mode="empty") on a zero-traffic
    window so the UI renders "—", never a fabricated $0."""
    percent = fee_percent if fee_percent is not None else org_fee_percent(project)

    verified = compute_verified_savings(db, project.id, window.start, window.end)
    # include_holdback_treatment=True so routed holdback-experiment savings appear
    # under their lever and in gross (as real per-event ledger facts), keeping the
    # dashboard's lever rows, daily chart, and gross total reconciled. Billing's
    # verified figure (above) keeps the disjoint A/B model.
    measured_by_lever = direct_measured_by_lever(
        db, project.id, window.start, window.end, include_holdback_treatment=True
    )
    measured_gross = _q(sum(measured_by_lever.values(), Decimal("0")))

    opportunity = db.scalar(
        select(func.coalesce(func.sum(Recommendation.estimated_monthly_savings_usd), 0)).where(
            Recommendation.project_id == project.id,
            Recommendation.status == "open",
        )
    ) or Decimal("0")

    base = {
        "period": window.period,
        "period_start": window.start,
        "period_end": window.end,
        "direct_measured_usd": verified["direct_measured_usd"],
        "holdback_measured_usd": verified["holdback_measured_usd"],
        "holdback_ci_low_usd": verified["holdback_ci_low_usd"],
        "holdback_ci_high_usd": verified["holdback_ci_high_usd"],
        "holdback_has_signal": verified["holdback_has_signal"],
        "estimated_opportunity_usd": _q(opportunity),
        "fee_percent": percent,
    }

    if _window_request_count(db, project, window) == 0:
        return {
            **base,
            "mode": "empty",
            "actual_spend_usd": None,
            "gross_savings_usd": None,
            "varsten_fee_usd": None,
            "net_savings_usd": None,
            "counterfactual_spend_usd": None,
            "by_lever": {},
            "by_lever_source": "",
        }

    actual = _q(_window_actual_spend(db, project, window))

    # Coherence rule: measured first, else the labelled estimate, else spend-only
    # (events exist but no realized or estimated savings -> gross is honestly null).
    if measured_gross > 0:
        mode, source, by_lever, gross = "measured", "measured", measured_by_lever, measured_gross
    else:
        estimated_by_lever = _estimated_by_lever(db, project, window)
        estimated_gross = _q(sum(estimated_by_lever.values(), Decimal("0")))
        if estimated_gross > 0:
            mode, source, by_lever, gross = "estimated", "estimated", estimated_by_lever, estimated_gross
        else:
            return {
                **base,
                "mode": "spend_only",
                "actual_spend_usd": actual,
                "gross_savings_usd": None,
                "varsten_fee_usd": None,
                "net_savings_usd": None,
                "counterfactual_spend_usd": actual,
                "by_lever": {},
                "by_lever_source": "",
            }

    fee = _fee_on(gross, percent)
    return {
        **base,
        "mode": mode,
        "actual_spend_usd": actual,
        "gross_savings_usd": gross,
        "varsten_fee_usd": fee,
        "net_savings_usd": gross - fee,
        "counterfactual_spend_usd": actual + gross,
        "by_lever": {k: _q(by_lever[k]) for k in _LEVER_KEYS if k in by_lever},
        "by_lever_source": source,
    }


# --- KPI deltas vs the same-elapsed prior window -------------------------------
#
# Each headline KPI is reported against the SAME elapsed slice of the previous
# period (day 1..N this period vs day 1..N last period), the apples-to-apples
# comparison a CFO trusts. The prior window comes straight from the resolver
# (window.prior()), so "last period" is defined in exactly one place.


class KpiDelta(TypedDict):
    current: Decimal | None
    previous: Decimal | None
    delta_pct: Decimal | None  # signed fraction, e.g. 0.18 == +18%; None when not comparable


class SavingsWithDeltas(TypedDict):
    current: WindowSavings
    kpis: dict[str, KpiDelta]


# KPI name -> the WindowSavings field it reads. These four are the dashboard tiles.
_KPI_FIELDS: dict[str, str] = {
    "net_saved": "net_savings_usd",
    "gross_saved": "gross_savings_usd",
    "without_varsten": "counterfactual_spend_usd",
    "actual_spend": "actual_spend_usd",
}


def _kpi_delta(current: Decimal | None, previous: Decimal | None) -> KpiDelta:
    """Signed percent change vs the prior window. Null-safe: no delta when either
    side is absent (renders "—") or when the prior value is 0 (division undefined,
    and "+inf%" is not a number a CFO can act on)."""
    if current is None or previous is None or previous == 0:
        delta_pct = None
    else:
        delta_pct = ((current - previous) / previous).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return {"current": current, "previous": previous, "delta_pct": delta_pct}


def compute_savings_with_deltas(
    db: Session,
    project: Project,
    window: PeriodWindow,
    fee_percent: Decimal | None = None,
) -> SavingsWithDeltas:
    """The full window savings plus each headline KPI's delta against the
    same-elapsed prior window. The prior arm runs the identical computation, so
    any methodology change applies to both arms and cancels in the delta."""
    current = compute_savings_for_window(db, project, window, fee_percent)
    previous = compute_savings_for_window(db, project, window.prior(), fee_percent)
    kpis = {name: _kpi_delta(current[field], previous[field]) for name, field in _KPI_FIELDS.items()}
    return {"current": current, "kpis": kpis}


def _next_month(d: date) -> date:
    return d.replace(year=d.year + 1, month=1) if d.month == 12 else d.replace(month=d.month + 1)


def _bucket_starts(window: PeriodWindow) -> list[date]:
    """Every bucket start in the window at its granularity, aligned to how Postgres
    ``date_trunc`` keys the grouped rows (day -> midnight, week -> Monday, month ->
    the 1st). Used to gap-fill so the chart shows a continuous axis from the start
    of the period to today, even across days with no traffic."""
    start, end, g = window.start, window.end, window.granularity
    out: list[date] = []
    if g == "day":
        cur, last = start.date(), end.date()
        while cur <= last:
            out.append(cur)
            cur += timedelta(days=1)
    elif g == "week":
        cur = (start - timedelta(days=start.weekday())).date()
        last = (end - timedelta(days=end.weekday())).date()
        while cur <= last:
            out.append(cur)
            cur += timedelta(weeks=1)
    else:  # month
        cur, last = start.date().replace(day=1), end.date().replace(day=1)
        while cur <= last:
            out.append(cur)
            cur = _next_month(cur)
    return out


def measured_savings_series(db: Session, project: Project, window: PeriodWindow) -> list[dict]:
    """Per-bucket optimized spend and measured savings across the window, bucketed
    at ``window.granularity`` (day/week/month). ``saved`` is non-holdback ledger
    saved_usd, so the series sums to the measured gross -- the chart reconciles
    with the KPI. ``baseline = optimized + saved`` is the naive-retail height.

    The series is gap-filled to a continuous axis from the start of the period to
    today (zero buckets for days with no traffic), so the chart reads as a full
    month rather than only the days that happened to have events. A zero-traffic
    window returns ``[]`` (the panel shows its empty state) -- gap-filling never
    fabricates a chart on a project that has no data at all."""
    bucket = func.date_trunc(window.granularity, UsageEvent.received_at).label("bucket")
    rows = db.execute(
        select(
            bucket,
            func.coalesce(func.sum(UsageEvent.cost_usd), 0).label("optimized"),
            func.coalesce(func.sum(_SAVED), 0).label("saved"),
        )
        .where(
            UsageEvent.project_id == project.id,
            UsageEvent.received_at >= window.start,
            UsageEvent.received_at < window.end,
        )
        .group_by(bucket)
        .order_by(bucket)
    ).all()
    if not rows:
        return []

    by_bucket = {row.bucket.date(): (Decimal(row.optimized), Decimal(row.saved)) for row in rows}
    series: list[dict] = []
    for day_value in _bucket_starts(window):
        optimized, saved = by_bucket.get(day_value, (Decimal("0"), Decimal("0")))
        series.append(
            {
                "date": day_value,
                "optimized_usd": _q(optimized),
                "saved_usd": _q(saved),
                "baseline_usd": _q(optimized + saved),
            }
        )
    return series
