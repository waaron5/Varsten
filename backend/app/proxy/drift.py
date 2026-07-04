"""Live quality-drift guard on the holdback.

The control arm (held back on the incumbent) is the live baseline. If the
treatment arm's objective response health drops below the control's by more than
a tolerance, the route is rolled back: the rule is disabled (traffic returns to
the incumbent on the next request) and the recommendation is marked rolled_back
and surfaced as a system action.

The rollback test is peeking-safe. This sweep runs every few minutes against the
same accumulating arms, so a point-estimate rule ("drop > tolerance") checked
repeatedly would fire on noise. Instead we build a time-uniform confidence
sequence for the quality-rate drop and roll back only when the whole sequence
sits above the tolerance -- i.e. we are confident the true drop exceeds it, not
merely that one noisy read did (app/proxy/sequential.py). The cost is that a
real drop needs enough samples to be confirmed rather than one unlucky window;
that is the correct trade for an automatic, irreversible action.

Objective signal only. Subtle subjective drift is a judge-based, approve-mode
concern and never triggers auto-rollback (CLAUDE.md).
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.engine import governance
from app.models import (
    ROUTING_LEVERS,
    Project,
    ProxyPolicy,
    QualityGuardrail,
    Recommendation,
    RecommendationAction,
    UsageEvent,
)
from app.proxy import canary
from app.proxy import routing as routing_mod
from app.proxy.compression import LEVER as COMPRESSION_LEVER
from app.proxy.experiment import MIN_ARM_SAMPLES
from app.proxy.routing import ARM_CONTROL, ARM_TREATMENT
from app.proxy.sequential import (
    ConfidenceSequence,
    difference_confidence_sequence,
    mean_confidence_sequence,
    rate_difference_confidence_sequence,
)
from app.proxy.trim import LEVER as TRIM_LEVER

logger = get_logger("varsten.proxy.drift")


@dataclass(frozen=True)
class _LatencyArm:
    requests: int
    mean_ms: float | None
    variance: float | None


def evaluate_drift(
    db: Session,
    project_id,
    incumbent: str,
    candidate: str,
    period_start: datetime,
) -> dict:
    """Compare objective response-health between the arms for one route."""
    meta = UsageEvent.event_metadata
    ok_rate = func.avg(case((meta["quality_ok"].astext == "true", 1.0), else_=0.0))
    rows = db.execute(
        select(meta["arm"].astext.label("arm"), func.count().label("n"), ok_rate.label("ok"))
        .where(
            UsageEvent.project_id == project_id,
            UsageEvent.received_at >= period_start,
            meta["holdback"].astext == "true",
            meta["experiment_from"].astext == incumbent,
            meta["experiment_to"].astext == candidate,
            meta["quality_ok"].astext.in_(["true", "false"]),
        )
        .group_by("arm")
    ).all()
    arms = {r.arm: r for r in rows}
    control = arms.get(ARM_CONTROL)
    treatment = arms.get(ARM_TREATMENT)

    n_c = int(control.n) if control else 0
    n_t = int(treatment.n) if treatment else 0
    ok_c = float(control.ok) if control and control.ok is not None else None
    ok_t = float(treatment.ok) if treatment and treatment.ok is not None else None

    enough = n_c >= MIN_ARM_SAMPLES and n_t >= MIN_ARM_SAMPLES
    delta = (ok_c - ok_t) if (ok_c is not None and ok_t is not None) else None
    # Confidence sequence for the quality drop (control ok-rate minus treatment
    # ok-rate). Roll back only when the whole interval clears the tolerance.
    cs = None
    if enough and ok_c is not None and ok_t is not None:
        cs = rate_difference_confidence_sequence(
            n_c,
            ok_c * n_c,
            n_t,
            ok_t * n_t,
            alpha=settings.sequential_cs_alpha,
            target_n=settings.sequential_cs_target_n,
        )
    drifted = bool(cs is not None and cs.exceeds(settings.drift_tolerance))
    return {
        "control_requests": n_c,
        "treatment_requests": n_t,
        "control_ok_rate": round(ok_c, 4) if ok_c is not None else None,
        "treatment_ok_rate": round(ok_t, 4) if ok_t is not None else None,
        "quality_drop": round(delta, 4) if delta is not None else None,
        "quality_drop_ci_low": round(cs.lo, 4) if cs is not None else None,
        "quality_drop_ci_high": round(cs.hi, 4) if cs is not None else None,
        "enough_signal": enough,
        "drifted": drifted,
    }


def _latency_slo_ms(db: Session, project_id, incumbent: str, candidate: str) -> int | None:
    """The route's absolute latency ceiling from an enabled QualityGuardrail, if
    one is configured for the incumbent or candidate model. (Route identity is
    still per-model until slice A5 gives evals/guardrails a shared route key.)"""
    guard = db.scalar(
        select(QualityGuardrail)
        .where(
            QualityGuardrail.project_id == project_id,
            QualityGuardrail.enabled.is_(True),
            QualityGuardrail.max_latency_ms.isnot(None),
            QualityGuardrail.route.in_([incumbent, candidate]),
        )
        .limit(1)
    )
    return guard.max_latency_ms if guard is not None else None


def _latency_arm(row: Any | None) -> _LatencyArm:
    if row is None:
        return _LatencyArm(requests=0, mean_ms=None, variance=None)
    return _LatencyArm(
        requests=int(row.n),
        mean_ms=float(row.mean) if row.mean is not None else None,
        variance=float(row.var) if row.var is not None else None,
    )


def _latency_arms(
    db: Session,
    project_id,
    incumbent: str,
    candidate: str,
    period_start: datetime,
) -> tuple[_LatencyArm, _LatencyArm]:
    meta = UsageEvent.event_metadata
    rows = db.execute(
        select(
            meta["arm"].astext.label("arm"),
            func.count().label("n"),
            func.avg(UsageEvent.latency_ms).label("mean"),
            func.var_samp(UsageEvent.latency_ms).label("var"),
        )
        .where(
            UsageEvent.project_id == project_id,
            UsageEvent.received_at >= period_start,
            meta["holdback"].astext == "true",
            meta["experiment_from"].astext == incumbent,
            meta["experiment_to"].astext == candidate,
            UsageEvent.latency_ms.isnot(None),
        )
        .group_by("arm")
    ).all()
    arms = {r.arm: r for r in rows}
    return _latency_arm(arms.get(ARM_CONTROL)), _latency_arm(arms.get(ARM_TREATMENT))


def _latency_delta_cs(
    control: _LatencyArm,
    treatment: _LatencyArm,
    *,
    enough_signal: bool,
) -> ConfidenceSequence | None:
    if not enough_signal or control.mean_ms is None or treatment.mean_ms is None:
        return None
    return difference_confidence_sequence(
        treatment.requests,
        treatment.mean_ms,
        treatment.variance,
        control.requests,
        control.mean_ms,
        control.variance,
        alpha=settings.sequential_cs_alpha,
        target_n=settings.sequential_cs_target_n,
    )


def _latency_slo_cs(
    db: Session,
    project_id,
    incumbent: str,
    candidate: str,
    treatment: _LatencyArm,
    *,
    enough_signal: bool,
) -> tuple[int | None, ConfidenceSequence | None]:
    if not settings.latency_slo_enabled:
        return None, None
    slo_ms = _latency_slo_ms(db, project_id, incumbent, candidate)
    if slo_ms is None or not enough_signal or treatment.mean_ms is None:
        return slo_ms, None
    return slo_ms, mean_confidence_sequence(
        treatment.requests,
        treatment.mean_ms,
        treatment.variance,
        alpha=settings.sequential_cs_alpha,
        target_n=settings.sequential_cs_target_n,
    )


def evaluate_latency_drift(
    db: Session,
    project_id,
    incumbent: str,
    candidate: str,
    period_start: datetime,
) -> dict:
    """Compare request latency between the arms for one route.

    A cheaper candidate that is meaningfully slower is a regression even when its
    output quality holds, so latency gets the same peeking-safe treatment as
    quality: roll back only when the treatment arm is *confidently* slower than
    the concurrent control arm beyond the tolerance, or (when a route SLO is set)
    confidently above that absolute ceiling."""
    control, treatment = _latency_arms(db, project_id, incumbent, candidate, period_start)
    enough = control.requests >= MIN_ARM_SAMPLES and treatment.requests >= MIN_ARM_SAMPLES
    delta = (
        treatment.mean_ms - control.mean_ms if control.mean_ms is not None and treatment.mean_ms is not None else None
    )

    # Confidence sequence for (treatment - control) latency: positive is slower.
    cs = _latency_delta_cs(control, treatment, enough_signal=enough)
    regressed = bool(
        settings.latency_guard_enabled and cs is not None and cs.exceeds(settings.latency_drift_tolerance_ms)
    )
    slo_ms, slo_cs = _latency_slo_cs(db, project_id, incumbent, candidate, treatment, enough_signal=enough)
    slo_breached = bool(slo_ms is not None and slo_cs is not None and slo_cs.exceeds(float(slo_ms)))

    return {
        "control_requests": control.requests,
        "treatment_requests": treatment.requests,
        "control_latency_ms": round(control.mean_ms) if control.mean_ms is not None else None,
        "treatment_latency_ms": round(treatment.mean_ms) if treatment.mean_ms is not None else None,
        "latency_delta_ms": round(delta) if delta is not None else None,
        "latency_delta_ci_low_ms": round(cs.lo) if cs is not None else None,
        "latency_delta_ci_high_ms": round(cs.hi) if cs is not None else None,
        "slo_ms": slo_ms,
        "enough_signal": enough,
        "regressed": regressed,
        "slo_breached": slo_breached,
    }


def sweep_all_projects(db: Session, *, now: datetime | None = None) -> dict[str, list[dict]]:
    """Run the drift sweep for every project that has an enabled holdback-measured
    policy. The scheduler's entry point; idempotent and per-project safe. Returns a
    map of project_id -> rolled-back routes (only projects with rollbacks)."""
    now = now or datetime.now(UTC)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    project_ids = list(
        db.scalars(
            select(ProxyPolicy.project_id)
            .where(
                ProxyPolicy.enabled.is_(True),
                ProxyPolicy.lever.in_((*ROUTING_LEVERS, TRIM_LEVER, COMPRESSION_LEVER)),
            )
            .distinct()
        )
    )
    results: dict[str, list[dict]] = {}
    for pid in project_ids:
        project = db.get(Project, pid)
        if project is None:
            continue
        rolled = check_and_rollback_drift(db, project, start, now=now)
        if rolled:
            results[str(pid)] = rolled
    return results


def check_and_rollback_drift(
    db: Session, project: Project, period_start: datetime, now: datetime | None = None
) -> list[dict]:
    """Sweep the project's enabled routes; roll back any that have drifted. Returns
    the routes rolled back. The production trigger is a scheduled job (a cron
    calling the endpoint); the function is idempotent (a disabled route is skipped
    next time)."""
    now = now or datetime.now(UTC)
    rolled: list[dict] = []
    if not settings.drift_auto_rollback_enabled:
        return rolled

    # All holdback-measured levers carry an objective drift guard: routing swaps
    # and token-trim transforms. (Trim is a same-model experiment, so its
    # experiment pair is model -> model.)
    rules = list(
        db.scalars(
            select(ProxyPolicy).where(
                ProxyPolicy.project_id == project.id,
                ProxyPolicy.lever.in_((*ROUTING_LEVERS, TRIM_LEVER, COMPRESSION_LEVER)),
                ProxyPolicy.enabled.is_(True),
            )
        )
    )
    for rule in rules:
        incumbent = rule.incumbent_model
        candidate = rule.candidate_model if rule.lever in ROUTING_LEVERS else incumbent
        if not candidate:
            continue
        route_label = f"{incumbent} -> {candidate}" if rule.lever in ROUTING_LEVERS else f"{incumbent} ({rule.lever})"

        q = evaluate_drift(db, project.id, incumbent, candidate, period_start)
        lat = evaluate_latency_drift(db, project.id, incumbent, candidate, period_start)

        if q["drifted"]:
            title = (
                f"Auto-rollback {route_label}: quality drift "
                f"({q['treatment_ok_rate']} vs {q['control_ok_rate']} control)"
            )
            _record_rollback(
                db,
                project,
                rule,
                now,
                title=title,
                detail="Treatment arm objective quality fell below the control arm beyond tolerance.",
            )
            rolled.append({"route": route_label, "trigger": "quality", **q})
        elif lat["regressed"]:
            title = (
                f"Auto-rollback {route_label}: latency regression "
                f"({lat['treatment_latency_ms']}ms vs {lat['control_latency_ms']}ms control)"
            )
            _record_rollback(
                db,
                project,
                rule,
                now,
                title=title,
                detail="Treatment arm was confidently slower than the control arm beyond the latency tolerance.",
            )
            rolled.append({"route": route_label, "trigger": "latency", **lat})
        elif lat["slo_breached"]:
            title = (
                f"Auto-rollback {route_label}: latency SLO breach ({lat['treatment_latency_ms']}ms > {lat['slo_ms']}ms)"
            )
            _record_rollback(
                db,
                project,
                rule,
                now,
                title=title,
                detail="Treatment arm latency was confidently above the route's max_latency_ms SLO.",
            )
            rolled.append({"route": route_label, "trigger": "latency_slo", **lat})
        else:
            # No regression this stage: if the route is mid-canary, ramp it up.
            _maybe_promote_canary(db, project, rule, now, route_label, q, lat)

        # Bandit candidates carry their own per-pair drift guard: a regressed
        # candidate is removed from the set (surgical) while the policy and its
        # primary stay live. The primary's regression above rolls back everything.
        if rule.lever in ROUTING_LEVERS and rule.enabled:
            rolled.extend(_check_bandit_candidates(db, project, rule, period_start, now))
    db.commit()
    return rolled


def _check_bandit_candidates(
    db: Session,
    project: Project,
    rule: ProxyPolicy,
    period_start: datetime,
    now: datetime,
) -> list[dict]:
    """Evaluate each bandit candidate's own holdback pair; remove any that has a
    confirmed quality or latency regression. Same peeking-safe confidence
    sequences as the primary; the response is surgical (drop the candidate, keep
    the policy) because one bad candidate must not kill a healthy route."""
    removed: list[dict] = []
    incumbent = rule.incumbent_model
    for entry in routing_mod.bandit_candidate_entries(rule):
        candidate = entry["model"]
        q = evaluate_drift(db, project.id, incumbent, candidate, period_start)
        lat = evaluate_latency_drift(db, project.id, incumbent, candidate, period_start)
        trigger = (
            "quality"
            if q["drifted"]
            else "latency"
            if lat["regressed"]
            else "latency_slo"
            if lat["slo_breached"]
            else None
        )
        if trigger is None:
            continue
        if not routing_mod.remove_bandit_candidate(db, rule, candidate):
            continue
        label = f"{incumbent} -> {candidate} (bandit)"
        db.add(
            RecommendationAction(
                organization_id=project.organization_id,
                project_id=project.id,
                recommendation_id=rule.source_recommendation_id,
                actor_user_id=None,
                lever=rule.lever,
                action_type="bandit_candidate_removed",
                status="completed",
                source="system",
                title=f"Bandit candidate removed {label}: {trigger} regression",
                detail="This candidate's holdback pair showed a confirmed regression; it left the candidate set.",
                occurred_at=now,
            )
        )
        logger.warning(
            "bandit candidate removed on drift",
            extra={"project_id": str(project.id), "route": label, "trigger": trigger},
        )
        removed.append({"route": label, "trigger": trigger, **(q if trigger == "quality" else lat)})
    return removed


def _maybe_promote_canary(
    db: Session,
    project: Project,
    rule: ProxyPolicy,
    now: datetime,
    route_label: str,
    quality: dict,
    latency: dict,
) -> None:
    """Promote a mid-canary route to its next rollout stage when the current stage
    has accumulated enough holdback signal with no quality or latency regression.
    A no-op unless canary mode is on and the route is below full rollout."""
    if not settings.canary_enabled or rule.rollout_percent >= canary.FULLY_LIVE:
        return
    # Only ramp up once a regression would have been visible: enough signal on at
    # least one guarded dimension, and (by construction here) none fired.
    if not (quality["enough_signal"] or latency["enough_signal"]):
        return
    target = canary.next_stage(rule.rollout_percent)
    if target is None or target <= rule.rollout_percent:
        return
    previous = rule.rollout_percent
    rule.rollout_percent = target
    db.add(
        RecommendationAction(
            organization_id=project.organization_id,
            project_id=project.id,
            recommendation_id=rule.source_recommendation_id,
            actor_user_id=None,
            lever=rule.lever,
            action_type="canary_promoted",
            status="completed",
            source="system",
            title=f"Canary ramp {route_label}: {previous}% -> {target}%",
            detail="No quality or latency regression at the current stage; promoting rollout.",
            occurred_at=now,
        )
    )
    logger.info(
        "canary rollout promoted",
        extra={"project_id": str(project.id), "route": route_label, "from": previous, "to": target},
    )


def _record_rollback(
    db: Session,
    project: Project,
    rule: ProxyPolicy,
    now: datetime,
    *,
    title: str,
    detail: str,
) -> None:
    """Disable a route, mark its source recommendation rolled back, and log the
    system action. Shared by the quality and latency rollback triggers."""
    rule.enabled = False
    rec = db.get(Recommendation, rule.source_recommendation_id) if rule.source_recommendation_id else None
    if rec is not None:
        rec.status = "rolled_back"
        rec.resolved_at = now
        rec.updated_at = now
        # Close the governance loop: the change this request approved is no longer
        # live. Best-effort; a governance sync failure never blocks a rollback.
        governance.mark_change_request_rolled_back(db, rec, now=now)
    db.add(
        RecommendationAction(
            organization_id=project.organization_id,
            project_id=project.id,
            recommendation_id=rule.source_recommendation_id,
            actor_user_id=None,
            lever=rule.lever,
            action_type="rolled_back",
            status="completed",
            source="system",
            title=title,
            detail=detail,
            occurred_at=now,
        )
    )
    logger.warning("route auto-rolled back", extra={"project_id": str(project.id), "route": title})
