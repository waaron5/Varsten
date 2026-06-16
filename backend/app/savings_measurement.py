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

from app.models import UsageEvent
from app.proxy.experiment import compute_experiment
from app.proxy.routing import SMART_ROUTING

# --- Strict measurement vocabulary --------------------------------------------
METHOD_ESTIMATED = "estimated"
METHOD_DIRECT_MEASURED = "direct_measured"
METHOD_HOLDBACK_MEASURED = "holdback_measured"
METHOD_REPLAY_MEASURED = "replay_measured"

# Methods whose savings are measured, not modeled. Only these roll into "verified".
MEASURED_METHODS = frozenset({METHOD_DIRECT_MEASURED, METHOD_HOLDBACK_MEASURED, METHOD_REPLAY_MEASURED})

# Lever names (mirror the recommendation/lever-config vocabulary).
LEVER_SEMANTIC_CACHE = "semantic_cache"
LEVER_BATCHING = "batching"

_CENTS = Decimal("0.01")
_meta = UsageEvent.event_metadata
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


def direct_measured_by_lever(db: Session, project_id, start: datetime, end: datetime) -> dict[str, Decimal]:
    """Direct measured savings this period, by lever, from the ledger.

    The three buckets are disjoint by construction (a holdback treatment event is
    tagged ``holdback=true`` and excluded from the direct-routing bucket), so the
    holdback measurement below never double-counts these.
    """
    cache = _sum_saved(db, project_id, start, end, _meta["cache"].astext == "hit")
    batching = _sum_saved(db, project_id, start, end, _meta["batch"].astext == "true")
    direct_routing = _sum_saved(
        db,
        project_id,
        start,
        end,
        _meta["routed"].astext == "true",
        func.coalesce(_meta["holdback"].astext, "false") != "true",
    )
    out: dict[str, Decimal] = {}
    if cache:
        out[LEVER_SEMANTIC_CACHE] = cache
    if batching:
        out[LEVER_BATCHING] = batching
    if direct_routing:
        out[SMART_ROUTING] = direct_routing
    return out


def _experiment_pairs(db: Session, project_id, start: datetime) -> list[tuple[str, str]]:
    rows = db.execute(
        select(
            _meta["experiment_from"].astext.label("incumbent"),
            _meta["experiment_to"].astext.label("candidate"),
        )
        .where(
            UsageEvent.project_id == project_id,
            UsageEvent.received_at >= start,
            _meta["holdback"].astext == "true",
        )
        .distinct()
    ).all()
    return [(r.incumbent, r.candidate) for r in rows if r.incumbent and r.candidate]


def holdback_measured(db: Session, project_id, start: datetime) -> dict:
    """Holdback A/B measured savings this period across all routing experiments,
    summed with a confidence interval. Experiments without a measurable arm
    difference contribute nothing (they stay estimated until they have signal)."""
    total = Decimal("0")
    ci_low = Decimal("0")
    ci_high = Decimal("0")
    experiments: list[dict] = []
    has_signal = False
    for incumbent, candidate in _experiment_pairs(db, project_id, start):
        exp = compute_experiment(db, project_id, incumbent, candidate, start)
        measured = exp["measured_savings_usd"]
        if measured is None:
            continue
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
        "has_signal": has_signal,
        "experiments": experiments,
    }


def compute_verified_savings(db: Session, project_id, start: datetime, end: datetime) -> dict:
    """Verified savings = direct measured + holdback measured, with provenance.

    This is the only number Proof should present as "saved". A skeptical reader can
    trace ``direct_by_lever`` to ledger ``saved_usd`` rows and ``holdback`` to the
    per-experiment arm aggregates.
    """
    direct = direct_measured_by_lever(db, project_id, start, end)
    direct_total = sum(direct.values(), Decimal("0"))
    holdback = holdback_measured(db, project_id, start)
    verified = direct_total + holdback["total_usd"]
    return {
        "direct_by_lever": {lever: _q(value) for lever, value in direct.items()},
        "direct_measured_usd": _q(direct_total),
        "holdback_measured_usd": _q(holdback["total_usd"]),
        "holdback_ci_low_usd": _q(holdback["ci_low_usd"]),
        "holdback_ci_high_usd": _q(holdback["ci_high_usd"]),
        "holdback_has_signal": holdback["has_signal"],
        "verified_savings_usd": _q(verified),
    }
