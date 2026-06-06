"""Live quality-drift guard on the holdback.

The control arm (held back on the incumbent) is the live baseline. If the
treatment arm's objective response health drops more than a tolerance below the
control's, with enough samples on both arms, the route is rolled back: the rule is
disabled (traffic returns to the incumbent on the next request) and the
recommendation is marked rolled_back and surfaced as a system action.

Objective signal only. Subtle subjective drift is a judge-based, approve-mode
concern and never triggers auto-rollback (CLAUDE.md).
"""

from datetime import UTC, datetime

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.models import ROUTING_LEVERS, Project, ProxyPolicy, Recommendation, RecommendationAction, UsageEvent
from app.proxy.experiment import MIN_ARM_SAMPLES
from app.proxy.routing import ARM_CONTROL, ARM_TREATMENT
from app.proxy.trim import LEVER as TRIM_LEVER

logger = get_logger("varsten.proxy.drift")


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
    drifted = bool(enough and delta is not None and delta > settings.drift_tolerance)
    return {
        "control_requests": n_c,
        "treatment_requests": n_t,
        "control_ok_rate": round(ok_c, 4) if ok_c is not None else None,
        "treatment_ok_rate": round(ok_t, 4) if ok_t is not None else None,
        "quality_drop": round(delta, 4) if delta is not None else None,
        "enough_signal": enough,
        "drifted": drifted,
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
                ProxyPolicy.lever.in_((*ROUTING_LEVERS, TRIM_LEVER)),
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
                ProxyPolicy.lever.in_((*ROUTING_LEVERS, TRIM_LEVER)),
                ProxyPolicy.enabled.is_(True),
            )
        )
    )
    for rule in rules:
        incumbent = rule.incumbent_model
        candidate = rule.candidate_model if rule.lever in ROUTING_LEVERS else incumbent
        if not candidate:
            continue
        d = evaluate_drift(db, project.id, incumbent, candidate, period_start)
        if not d["drifted"]:
            continue
        rule.enabled = False
        route_label = f"{incumbent} -> {candidate}" if rule.lever in ROUTING_LEVERS else f"{incumbent} (trim)"
        title = (
            f"Auto-rollback {route_label}: quality drift ({d['treatment_ok_rate']} vs {d['control_ok_rate']} control)"
        )
        rec = db.get(Recommendation, rule.source_recommendation_id) if rule.source_recommendation_id else None
        if rec is not None:
            rec.status = "rolled_back"
            rec.resolved_at = now
            rec.updated_at = now
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
                detail="Treatment arm objective quality fell below the control arm beyond tolerance.",
                occurred_at=now,
            )
        )
        logger.warning("route auto-rolled back on drift", extra={"project_id": str(project.id), "route": title})
        rolled.append(
            {
                "route": route_label,
                **d,
            }
        )
    db.commit()
    return rolled
