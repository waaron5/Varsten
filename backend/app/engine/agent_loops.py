"""Agent-loop detection: redundant LLM calls inside one client trace.

Agentic workflows routinely re-ask the model something they already asked in the
same run — a planner re-planning, a retry loop that didn't need to retry, a
sub-agent re-deriving context the orchestrator already had. Each repeat is a
whole model call whose answer the workflow already possessed, which often makes
this the largest single saving in agent-heavy traffic — and no inline lever can
capture it, because the fix is in the customer's workflow, not the request path.

Detection is pure measurement on the decision ledger: requests that share a
client trace id (``X-Varsten-Trace-Id``) and an identical content-free
whole-request fingerprint were the same question asked twice in one workflow.
The first ask is treated as necessary; every repeat's realized cost is waste,
summed per route. The output is evidence for a *recommendation* — Varsten never
rewrites a workflow, it shows the customer exactly where their agent loops and
what it costs.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Project, RequestDecisionEvent

# A fingerprint must repeat at least this many times within one trace to count.
MIN_REPEATS = 2
# A route needs at least this many affected traces before it is worth surfacing;
# one looping trace is an anecdote, a pattern of them is a workflow defect.
MIN_AFFECTED_TRACES = 3


@dataclass(frozen=True)
class RouteLoopFinding:
    """Measured redundant-call evidence for one route."""

    route_key: str
    model: str
    affected_traces: int
    redundant_calls: int
    total_calls_in_loops: int
    wasted_cost_usd: Decimal


def detect_agent_loops(
    db: Session,
    project: Project,
    start: datetime,
    *,
    min_repeats: int = MIN_REPEATS,
    min_affected_traces: int = MIN_AFFECTED_TRACES,
) -> list[RouteLoopFinding]:
    """Routes with measurable agent loops this period, worst first.

    Fail-open: any error returns an empty list — this is analysis, never a
    request-path dependency."""
    try:
        rows = db.execute(
            select(
                RequestDecisionEvent.route_key,
                RequestDecisionEvent.trace_id,
                RequestDecisionEvent.request_fingerprint,
                func.max(RequestDecisionEvent.model_requested).label("model"),
                func.count().label("n"),
                func.coalesce(func.sum(RequestDecisionEvent.realized_actual_cost_usd), 0).label("cost"),
            )
            .where(
                RequestDecisionEvent.project_id == project.id,
                RequestDecisionEvent.created_at >= start,
                RequestDecisionEvent.trace_id.isnot(None),
                RequestDecisionEvent.request_fingerprint.isnot(None),
            )
            .group_by(
                RequestDecisionEvent.route_key,
                RequestDecisionEvent.trace_id,
                RequestDecisionEvent.request_fingerprint,
            )
            .having(func.count() >= min_repeats)
        ).all()
    except Exception:
        return []

    per_route: dict[str, dict] = {}
    for row in rows:
        route = str(row.route_key or "default")
        agg = per_route.setdefault(
            route,
            {"model": str(row.model or ""), "traces": set(), "redundant": 0, "total": 0, "wasted": Decimal("0")},
        )
        n = int(row.n)
        total_cost = Decimal(str(row.cost or 0))
        agg["traces"].add(str(row.trace_id))
        agg["redundant"] += n - 1
        agg["total"] += n
        # The first ask was necessary; the repeats' share of the group cost is waste.
        agg["wasted"] += total_cost * Decimal(n - 1) / Decimal(n)

    findings = [
        RouteLoopFinding(
            route_key=route,
            model=agg["model"],
            affected_traces=len(agg["traces"]),
            redundant_calls=agg["redundant"],
            total_calls_in_loops=agg["total"],
            wasted_cost_usd=agg["wasted"],
        )
        for route, agg in per_route.items()
        if len(agg["traces"]) >= min_affected_traces
    ]
    findings.sort(key=lambda f: f.wasted_cost_usd, reverse=True)
    return findings
