"""Live holdback A/B: rigorous savings from concurrently-sampled arms.

Derived straight from the usage-event ledger (no experiment table). For a route's
incumbent -> candidate swap over a period, the control arm (held back on the
incumbent) and the treatment arm (routed to the candidate) are sampled at the
same time, so any app-level or provider-price change lands on both and cancels.

Savings per request is the measured cost-per-request difference between the arms;
the realized savings is that times the treatment volume, reported with a
confidence interval, never a bare point estimate. Because the ledger is read
continuously (dashboards, the drift sweep), the interval is a time-uniform
*confidence sequence* (app/proxy/sequential.py), not a fixed-n 95% CI that would
lose its coverage under repeated looks. This is the number that survives a CFO.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import UsageEvent
from app.proxy.routing import ARM_CONTROL, ARM_TREATMENT
from app.proxy.sequential import difference_confidence_sequence

# Minimum requests per arm before the A/B reports a confidence interval. Below
# this the point estimate is shown but flagged as not yet significant.
MIN_ARM_SAMPLES = 30

_Q = Decimal("0.00000001")


def _q(value) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value)).quantize(_Q)


def compute_experiment(
    db: Session,
    project_id,
    incumbent: str,
    candidate: str,
    period_start: datetime,
    period_end: datetime | None = None,
) -> dict:
    """Arm aggregates and the measured A/B savings for one route this period."""
    meta = UsageEvent.event_metadata
    conditions = [
        UsageEvent.project_id == project_id,
        UsageEvent.received_at >= period_start,
        meta["holdback"].astext == "true",
        meta["experiment_from"].astext == incumbent,
        meta["experiment_to"].astext == candidate,
    ]
    if period_end is not None:
        conditions.append(UsageEvent.received_at < period_end)
    rows = db.execute(
        select(
            meta["arm"].astext.label("arm"),
            func.count().label("n"),
            func.avg(UsageEvent.cost_usd).label("mean"),
            func.var_samp(UsageEvent.cost_usd).label("var"),
        )
        .where(*conditions)
        .group_by("arm")
    ).all()

    arms = {r.arm: r for r in rows}
    control = arms.get(ARM_CONTROL)
    treatment = arms.get(ARM_TREATMENT)

    n_c = int(control.n) if control else 0
    n_t = int(treatment.n) if treatment else 0
    mean_c = Decimal(str(control.mean)) if control and control.mean is not None else None
    mean_t = Decimal(str(treatment.mean)) if treatment and treatment.mean is not None else None

    per_request: Decimal | None = None
    ci_low = ci_high = None
    measured = measured_low = measured_high = None

    if mean_c is not None and mean_t is not None:
        per_request = mean_c - mean_t
        measured = per_request * Decimal(n_t)
        # Time-uniform confidence sequence on the difference of arm means, valid
        # under the continuous re-reading this table gets. None (an arm too small
        # or without dispersion) leaves the bare point estimate uncintervaled,
        # exactly as the fixed-CI path did.
        cs = difference_confidence_sequence(
            n_c,
            float(mean_c),
            float(control.var) if control is not None and control.var is not None else None,
            n_t,
            float(mean_t),
            float(treatment.var) if treatment is not None and treatment.var is not None else None,
            alpha=settings.sequential_cs_alpha,
            target_n=settings.sequential_cs_target_n,
        )
        if cs is not None:
            ci_low = Decimal(str(cs.lo))
            ci_high = Decimal(str(cs.hi))
            measured_low = ci_low * Decimal(n_t)
            measured_high = ci_high * Decimal(n_t)

    return {
        "incumbent_model": incumbent,
        "candidate_model": candidate,
        "control_requests": n_c,
        "treatment_requests": n_t,
        "control_avg_cost_usd": _q(mean_c) if mean_c is not None else None,
        "treatment_avg_cost_usd": _q(mean_t) if mean_t is not None else None,
        "savings_per_request_usd": _q(per_request) if per_request is not None else None,
        "savings_per_request_ci_low_usd": _q(ci_low) if ci_low is not None else None,
        "savings_per_request_ci_high_usd": _q(ci_high) if ci_high is not None else None,
        "measured_savings_usd": _q(measured) if measured is not None else None,
        "measured_savings_ci_low_usd": _q(measured_low) if measured_low is not None else None,
        "measured_savings_ci_high_usd": _q(measured_high) if measured_high is not None else None,
        "has_signal": n_c >= MIN_ARM_SAMPLES and n_t >= MIN_ARM_SAMPLES,
    }
