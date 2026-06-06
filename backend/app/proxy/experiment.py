"""Live holdback A/B: rigorous savings from concurrently-sampled arms.

Derived straight from the usage-event ledger (no experiment table). For a route's
incumbent -> candidate swap over a period, the control arm (held back on the
incumbent) and the treatment arm (routed to the candidate) are sampled at the
same time, so any app-level or provider-price change lands on both and cancels.

Savings per request is the measured cost-per-request difference between the arms;
the realized savings is that times the treatment volume, reported with a
confidence interval, never a bare point estimate. This is the number that
survives a CFO.
"""

import math
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import UsageEvent
from app.proxy.routing import ARM_CONTROL, ARM_TREATMENT

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
) -> dict:
    """Arm aggregates and the measured A/B savings for one route this period."""
    meta = UsageEvent.event_metadata
    rows = db.execute(
        select(
            meta["arm"].astext.label("arm"),
            func.count().label("n"),
            func.avg(UsageEvent.cost_usd).label("mean"),
            func.var_samp(UsageEvent.cost_usd).label("var"),
        )
        .where(
            UsageEvent.project_id == project_id,
            UsageEvent.received_at >= period_start,
            meta["holdback"].astext == "true",
            meta["experiment_from"].astext == incumbent,
            meta["experiment_to"].astext == candidate,
        )
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
        # 95% CI on the difference of means via the standard errors of both arms.
        if (
            control is not None
            and treatment is not None
            and n_c >= 2
            and n_t >= 2
            and control.var is not None
            and treatment.var is not None
        ):
            se = math.sqrt((float(control.var) / n_c) + (float(treatment.var) / n_t))
            half = Decimal(str(1.96 * se))
            ci_low = per_request - half
            ci_high = per_request + half
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
