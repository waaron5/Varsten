"""Apply/dismiss dispatch for the executable levers.

One place maps a recommendation's lever to the execution policy it activates, so
the two apply paths (the plain recommendations API and the engine API the UI
calls) stay in sync. Model-swap levers need a passing eval (the gating run);
token-trim is ungated and activates directly.
"""

from datetime import datetime

from sqlalchemy.orm import Session

from app.models import ROUTING_LEVERS, Project, Recommendation
from app.proxy import compression, routing, trim


def activate_execution(
    db: Session,
    project: Project,
    recommendation: Recommendation,
    gating_run,
    *,
    now: datetime | None = None,
) -> None:
    """Activate the execution policy for an applied recommendation, by lever.

    Prompt compression may raise TransformConflictError (a trim policy is live on
    the same model); the apply endpoint surfaces that as a conflict rather than
    silently applying nothing."""
    lever = recommendation.lever
    if lever in ROUTING_LEVERS:
        if gating_run is not None:
            routing.activate_rule(db, project, recommendation, gating_run.candidate_model, now=now)
    elif lever == trim.LEVER:
        trim.activate_trim_policy(db, project, recommendation, now=now)
    elif lever == compression.LEVER:
        compression.activate_compression_policy(db, project, recommendation, now=now)


def deactivate_execution(db: Session, recommendation: Recommendation) -> None:
    """Turn off any execution policy sourced from this recommendation, whatever the
    lever. Safe to call for levers that have no policy."""
    routing.deactivate_rules_for_recommendation(db, recommendation)
    trim.deactivate_trim_for_recommendation(db, recommendation)
    compression.deactivate_compression_for_recommendation(db, recommendation)
