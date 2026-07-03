"""Measured savings, derived from the ledger — the number a CFO can audit.

This is the honest counterpart to the estimate-based accounting in ``savings.py``.
Nothing here is a model of a counterfactual; every dollar is either arithmetic on
recorded facts or a concurrent A/B difference:

- **Direct measured** (semantic cache, batching, non-holdback routing): the proxy
  records the avoided cost on each event as ``saved_usd`` in the ledger metadata —
  a cache hit avoids the model price outright, a batch captures a contractual
  discount on identical tokens, a direct route pays the candidate instead of the
  incumbent. Summing those is measurement, not estimation.
- **Holdback measured** (routing experiments): the per-request cost difference
  between the concurrently-sampled control and treatment arms, times treatment
  volume, with a 95% confidence interval (see ``proxy/experiment.py``).

The strict measurement-method vocabulary lives here so the API, the model, and the
UI all speak it. ``estimated`` is never reported as "saved"; only measured methods
roll into verified savings.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Numeric, cast, func, select
from sqlalchemy.orm import Session

from app.levers import LEVER_BATCHING, LEVER_SEMANTIC_CACHE, LEVER_SMART_ROUTING
from app.models import ProxyPolicy, UsageEvent
from app.models.proxy_policy import ROUTING_LEVERS
from app.proxy.experiment import compute_experiment

# --- Strict measurement vocabulary --------------------------------------------
METHOD_ESTIMATED = "estimated"
METHOD_DIRECT_MEASURED = "direct_measured"
METHOD_HOLDBACK_MEASURED = "holdback_measured"
METHOD_REPLAY_MEASURED = "replay_measured"

# Methods whose savings are measured, not modeled. Only these roll into "verified".
MEASURED_METHODS = frozenset({METHOD_DIRECT_MEASURED, METHOD_HOLDBACK_MEASURED, METHOD_REPLAY_MEASURED})

_CENTS = Decimal("0.01")
_meta = UsageEvent.event_metadata
_OVERHEAD_TAGS = ("eval_replay", "embedding")
# saved_usd is stored as a JSON string (e.g. "1.230000"); absent or JSON-null
# rows yield SQL NULL on .astext and are excluded by the not-null filter below.
_saved = cast(_meta["saved_usd"].astext, Numeric(20, 12))


def is_measured(method: str | None) -> bool:
    return method in MEASURED_METHODS


def _q(value: Decimal | None) -> Decimal:
    return Decimal(value or 0).quantize(_CENTS)


def _sum_saved(db: Session, project_id, start: datetime, end: datetime, *conditions) -> Decimal:
    """Sum the ledger's recorded ``saved_usd`` over the period for events matching
    ``conditions``. Real arithmetic on recorded facts, never a projection."""
    total = db.scalar(
        select(func.coalesce(func.sum(_saved), 0)).where(
            UsageEvent.project_id == project_id,
            UsageEvent.received_at >= start,
            UsageEvent.received_at < end,
            _meta["saved_usd"].astext.isnot(None),
            *conditions,
        )
    )
    return Decimal(total or 0)


def _routing_lever(db: Session, project_id) -> str:
    """Which routing lever (``model_downshift`` vs ``smart_routing``) gets credited
    for routed savings. The ledger marks an event ``routed`` but not which routing
    lever drove it, so we attribute it to the project's enabled routing policy.
    Falls back to ``smart_routing`` when no routing policy is enabled."""
    lever = db.scalar(
        select(ProxyPolicy.lever)
        .where(
            ProxyPolicy.project_id == project_id,
            ProxyPolicy.enabled.is_(True),
            ProxyPolicy.lever.in_(ROUTING_LEVERS),
        )
        .order_by(ProxyPolicy.activated_at.desc().nulls_last())
        .limit(1)
    )
    return lever or LEVER_SMART_ROUTING


def direct_measured_by_lever(
    db: Session,
    project_id,
    start: datetime,
    end: datetime,
    *,
    include_holdback_treatment: bool = False,
) -> dict[str, Decimal]:
    """Direct measured savings this period, by lever, from the ledger.

    Routed savings are credited to the project's enabled routing lever (see
    ``_routing_lever``) so the Savings-by-lever breakdown names the lever that
    actually drove the route, not a hard-coded default.

    ``include_holdback_treatment`` controls how routed *holdback experiment*
    treatment events are counted:

    - ``False`` (verified-savings / billing): exclude them, so they are measured
      exactly once by the rigorous A/B (``holdback_measured``) and the two buckets
      stay disjoint. ``verified = direct + holdback`` never double-counts.
    - ``True`` (dashboard per-lever + chart): include their real per-event
      ``saved_usd`` so the routing lever, the daily chart, and the gross total all
      reflect routing as concrete ledger facts that reconcile exactly. The A/B
      remains the conservative cross-check shown in Proof.
    """
    cache = _sum_saved(db, project_id, start, end, _meta["cache"].astext == "hit")
    batching = _sum_saved(db, project_id, start, end, _meta["batch"].astext == "true")
    routing_conditions = [_meta["routed"].astext == "true"]
    if not include_holdback_treatment:
        routing_conditions.append(func.coalesce(_meta["holdback"].astext, "false") != "true")
    direct_routing = _sum_saved(db, project_id, start, end, *routing_conditions)
    out: dict[str, Decimal] = {}
    if cache:
        out[LEVER_SEMANTIC_CACHE] = cache
    if batching:
        out[LEVER_BATCHING] = batching
    if direct_routing:
        out[_routing_lever(db, project_id)] = direct_routing
    return out


def _experiment_pairs(db: Session, project_id, start: datetime, end: datetime | None = None) -> list[tuple[str, str]]:
    conditions = [
        UsageEvent.project_id == project_id,
        UsageEvent.received_at >= start,
        _meta["holdback"].astext == "true",
    ]
    if end is not None:
        conditions.append(UsageEvent.received_at < end)
    rows = db.execute(
        select(
            _meta["experiment_from"].astext.label("incumbent"),
            _meta["experiment_to"].astext.label("candidate"),
        )
        .where(*conditions)
        .distinct()
    ).all()
    return [(r.incumbent, r.candidate) for r in rows if r.incumbent and r.candidate]


def holdback_measured(db: Session, project_id, start: datetime, end: datetime | None = None) -> dict:
    """Holdback A/B measured savings this period across all routing experiments,
    summed with a confidence interval. Experiments without a measurable arm
    difference contribute nothing (they stay estimated until they have signal)."""
    total = Decimal("0")
    ci_low = Decimal("0")
    ci_high = Decimal("0")
    measurement_cost = Decimal("0")
    experiments: list[dict] = []
    has_signal = False
    for incumbent, candidate in _experiment_pairs(db, project_id, start, end):
        exp = compute_experiment(db, project_id, incumbent, candidate, start, end)
        measured = exp["measured_savings_usd"]
        if measured is None:
            continue
        savings_per_request = exp["savings_per_request_usd"] or Decimal("0")
        exp_measurement_cost = max(Decimal(str(savings_per_request)), Decimal("0")) * Decimal(
            exp["control_requests"] or 0
        )
        exp["measurement_cost_usd"] = _q(exp_measurement_cost)
        measurement_cost += exp_measurement_cost
        total += measured
        # Fall back to the point estimate when an arm lacks the variance for a CI.
        ci_low += exp["measured_savings_ci_low_usd"] if exp["measured_savings_ci_low_usd"] is not None else measured
        ci_high += exp["measured_savings_ci_high_usd"] if exp["measured_savings_ci_high_usd"] is not None else measured
        has_signal = has_signal or exp["has_signal"]
        experiments.append(exp)
    return {
        "total_usd": total,
        "ci_low_usd": ci_low,
        "ci_high_usd": ci_high,
        "measurement_cost_usd": measurement_cost,
        "has_signal": has_signal,
        "experiments": experiments,
    }


def optimization_overhead_cost(db: Session, project_id, start: datetime, end: datetime) -> Decimal:
    """Cost of Varsten optimization work in the period.

    Overhead rows are real provider calls used to execute or validate an
    optimization, tagged in the ledger as ``metadata.overhead``. They reduce the
    verified savings basis before gain-share billing.
    """
    total = db.scalar(
        select(func.coalesce(func.sum(UsageEvent.cost_usd), 0)).where(
            UsageEvent.project_id == project_id,
            UsageEvent.received_at >= start,
            UsageEvent.received_at < end,
            _meta["overhead"].astext.in_(_OVERHEAD_TAGS),
        )
    )
    return Decimal(total or 0)


def compute_verified_savings(db: Session, project_id, start: datetime, end: datetime) -> dict:
    """Verified savings = measured gross savings minus proof/optimization cost.

    A skeptical reader can trace ``direct_by_lever`` to ledger ``saved_usd`` rows,
    ``holdback`` to the per-experiment arm aggregates, and the two cost offsets
    to explicit ledger facts. The returned ``verified_savings_usd`` is the net
    billable basis; ``verified_gross_savings_usd`` keeps the pre-cost number
    visible for audit.
    """
    direct = direct_measured_by_lever(db, project_id, start, end)
    direct_total = sum(direct.values(), Decimal("0"))
    holdback = holdback_measured(db, project_id, start, end)
    verified_gross = direct_total + holdback["total_usd"]
    measurement_cost = holdback["measurement_cost_usd"]
    overhead = optimization_overhead_cost(db, project_id, start, end)
    verified_net = verified_gross - measurement_cost - overhead
    return {
        "direct_by_lever": {lever: _q(value) for lever, value in direct.items()},
        "direct_measured_usd": _q(direct_total),
        "holdback_measured_usd": _q(holdback["total_usd"]),
        "holdback_ci_low_usd": _q(holdback["ci_low_usd"]),
        "holdback_ci_high_usd": _q(holdback["ci_high_usd"]),
        "measurement_cost_usd": _q(measurement_cost),
        "optimization_overhead_cost_usd": _q(overhead),
        "verified_gross_savings_usd": _q(verified_gross),
        "holdback_has_signal": holdback["has_signal"],
        "verified_savings_usd": _q(verified_net),
    }
