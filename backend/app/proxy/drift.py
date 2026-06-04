"""Live quality-drift guard on the holdback.

The control arm (held back on the incumbent) is the live baseline. If the
treatment arm's objective response health drops more than a tolerance below the
control's, with enough samples on both arms, the route is rolled back: the rule is
disabled (traffic returns to the incumbent on the next request) and the
recommendation is marked rolled_back and surfaced as a system action.

Objective signal only. Subtle subjective drift is a judge-based, approve-mode
concern and never triggers auto-rollback (CLAUDE.md).
"""
from datetime import datetime, timezone

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.models import Project, ProxyRoutingRule, Recommendation, RecommendationAction, UsageEvent
from app.proxy.experiment import MIN_ARM_SAMPLES
from app.proxy.routing import ARM_CONTROL, ARM_TREATMENT

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


def check_and_rollback_drift(
    db: Session, project: Project, period_start: datetime, now: datetime | None = None
) -> list[dict]:
    """Sweep the project's enabled routes; roll back any that have drifted. Returns
    the routes rolled back. The production trigger is a scheduled job (a cron
    calling the endpoint); the function is idempotent (a disabled route is skipped
    next time)."""
    now = now or datetime.now(timezone.utc)
    rolled: list[dict] = []
    if not settings.drift_auto_rollback_enabled:
        return rolled

    rules = list(
        db.scalars(
            select(ProxyRoutingRule).where(
                ProxyRoutingRule.project_id == project.id, ProxyRoutingRule.enabled.is_(True)
            )
        )
    )
    for rule in rules:
        d = evaluate_drift(db, project.id, rule.incumbent_model, rule.candidate_model, period_start)
        if not d["drifted"]:
            continue
        rule.enabled = False
        title = (
            f"Auto-rollback {rule.incumbent_model} -> {rule.candidate_model}: quality drift "
            f"({d['treatment_ok_rate']} vs {d['control_ok_rate']} control)"
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
                lever="cheaper_model",
                action_type="rolled_back",
                status="completed",
                source="system",
                title=title,
                detail="Treatment arm objective quality fell below the control arm beyond tolerance.",
                occurred_at=now,
            )
        )
        logger.warning("route auto-rolled back on drift", extra={"project_id": str(project.id), "route": title})
        rolled.append({
            "route": f"{rule.incumbent_model} -> {rule.candidate_model}",
            **d,
        })
    db.commit()
    return rolled
