"""Eval / replay harness control-plane API.

- POST /v1/recommendations/{id}/evaluate   open + run a shadow eval for a
  model-downshift recommendation (runs off the request path, in a BackgroundTask).
- GET  /v1/evals                            list runs for a project
- GET  /v1/evals/{run_id}                   run detail with the per-sample audit
- POST /v1/evals/golden                     upload customer golden samples
- POST /v1/evals/capture-config             toggle per-project traffic capture

None of this touches the proxy hot path. The evaluate endpoint makes model calls,
but only inside the background worker, never inside a proxied request.
"""

import asyncio
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_user, resolve_project
from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import SessionLocal, get_db
from app.engine import compression as engine_compression
from app.eval.gate import GATED_LEVERS
from app.eval.runner import create_run_for_recommendation, run_eval
from app.levers import LEVER_PROMPT_COMPRESSION
from app.models import (
    EvalRun,
    EvalSampleResult,
    ModelCatalog,
    OrgMembership,
    Project,
    Recommendation,
    ReplaySample,
    User,
)
from app.models.eval import SOURCE_GOLDEN
from app.proxy.keys import provider_key_for_project
from app.schemas import (
    EvalCaptureConfigUpdate,
    EvalRunDetail,
    EvalRunOut,
    GoldenSampleBatchIn,
)

router = APIRouter(tags=["evals"])
logger = get_logger("varsten.eval.api")


def _assert_member(user: User, organization_id: uuid.UUID, db: Session) -> None:
    member = db.scalar(
        select(OrgMembership.id).where(
            OrgMembership.user_id == user.id,
            OrgMembership.organization_id == organization_id,
        )
    )
    if member is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not a member")


def _candidate_model(db: Session, recommendation: Recommendation) -> str | None:
    """The lower-cost substitute for the recommendation's incumbent model, from the
    catalog. This is the model the shadow eval tests."""
    if not recommendation.related_model:
        return None
    catalog = db.scalar(
        select(ModelCatalog).where(
            ModelCatalog.model_key == recommendation.related_model,
            ModelCatalog.provider == (recommendation.related_provider or "openai"),
        )
    )
    return catalog.cheaper_substitute_key if catalog else None


def _execute_run_background(run_id: uuid.UUID, key: str) -> None:
    """Background entrypoint: own DB session, own event loop. Isolated from the
    request so a long replay never holds the HTTP connection open. Dispatches by
    lever: a prompt-compression run replays with the compressed prompt
    substituted; everything else is the standard candidate-model replay."""
    db = SessionLocal()
    try:
        run = db.get(EvalRun, run_id)
        if run is None:
            return
        if run.lever == LEVER_PROMPT_COMPRESSION:
            asyncio.run(engine_compression.run_compression_eval(db, run, key=key))
        else:
            asyncio.run(run_eval(db, run, key=key))
    except Exception:
        logger.exception("background eval run failed", extra={"eval_run_id": str(run_id)})
    finally:
        db.close()


@router.post(
    "/recommendations/{recommendation_id}/evaluate",
    response_model=EvalRunOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def evaluate_recommendation(
    recommendation_id: uuid.UUID,
    background: BackgroundTasks,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> EvalRun:
    recommendation = db.get(Recommendation, recommendation_id)
    if recommendation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="recommendation not found")
    _assert_member(user, recommendation.organization_id, db)

    if recommendation.lever not in GATED_LEVERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"the {recommendation.lever} lever does not require a shadow eval",
        )
    if recommendation.lever == LEVER_PROMPT_COMPRESSION:
        # Same-model run: the candidate is the same model reading the compressed
        # prompt. Requires a generated artifact to substitute.
        if engine_compression.artifact_for_recommendation(db, recommendation.id) is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="no compression artifact for this recommendation; generate one first",
            )
        candidate = recommendation.related_model or recommendation.target_key
    else:
        candidate = _candidate_model(db, recommendation)
    if not candidate:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="no catalog lower-cost substitute found for this route's model",
        )
    project = db.get(Project, recommendation.project_id)
    key = provider_key_for_project(project.id, "openai") if project else None
    if not key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="no OpenAI key configured for this project; cannot replay",
        )

    # Compression generation opens a pending run alongside the artifact; reuse it
    # instead of stacking a second one.
    run = db.scalar(
        select(EvalRun)
        .where(EvalRun.recommendation_id == recommendation.id, EvalRun.status == "pending")
        .order_by(EvalRun.created_at.desc())
        .limit(1)
    )
    if run is None:
        run = create_run_for_recommendation(db, project, recommendation, candidate)
    background.add_task(_execute_run_background, run.id, key)
    return run


@router.get("/evals", response_model=list[EvalRunOut])
def list_eval_runs(
    project: Project = Depends(resolve_project),
    db: Session = Depends(get_db),
) -> list[EvalRun]:
    return list(db.scalars(select(EvalRun).where(EvalRun.project_id == project.id).order_by(EvalRun.created_at.desc())))


@router.post("/evals/golden", response_model=dict)
def upload_golden_samples(
    payload: GoldenSampleBatchIn,
    project: Project = Depends(resolve_project),
    db: Session = Depends(get_db),
) -> dict:
    """Add customer golden samples (the strongest scoring tier) for a route. These
    never expire and are scored first in every run."""
    created = 0
    for sample in payload.samples:
        db.add(
            ReplaySample(
                organization_id=project.organization_id,
                project_id=project.id,
                route_key=sample.route_key,
                source=SOURCE_GOLDEN,
                incumbent_model=sample.route_key,
                request_messages=sample.messages,
                request_params=sample.request_params,
                incumbent_response=None,
                expected_output=sample.expected_output,
                expires_at=None,
            )
        )
        created += 1
    db.commit()
    return {"created": created}


@router.get("/evals/config", response_model=dict)
def eval_config(
    project: Project = Depends(resolve_project),
    db: Session = Depends(get_db),
) -> dict:
    """Current capture opt-in plus the replay corpus per route, so the UI can show
    the toggle state and whether a route has enough samples to evaluate."""
    rows = db.execute(
        select(
            ReplaySample.route_key,
            ReplaySample.source,
            func.count().label("n"),
        )
        .where(ReplaySample.project_id == project.id)
        .group_by(ReplaySample.route_key, ReplaySample.source)
    ).all()
    routes: dict[str, dict] = {}
    for route_key, source, n in rows:
        entry = routes.setdefault(route_key, {"route_key": route_key, "traffic_samples": 0, "golden_samples": 0})
        if source == SOURCE_GOLDEN:
            entry["golden_samples"] += n
        else:
            entry["traffic_samples"] += n
    return {
        "eval_capture_enabled": project.eval_capture_enabled,
        "min_samples": settings.eval_min_samples,
        "routes": sorted(routes.values(), key=lambda r: r["route_key"]),
    }


@router.post("/evals/capture-config", response_model=dict)
def update_capture_config(
    payload: EvalCaptureConfigUpdate,
    project: Project = Depends(resolve_project),
    db: Session = Depends(get_db),
) -> dict:
    """Customer opt-in toggle for sampling real traffic into the replay corpus.
    Off by default; this is the consent gate for the content store."""
    project.eval_capture_enabled = payload.eval_capture_enabled
    project.updated_at = datetime.now(UTC)
    db.commit()
    return {"eval_capture_enabled": project.eval_capture_enabled}


# Registered last so the static /evals/* routes above are matched first; otherwise
# this path param swallows "config", "golden", etc.
@router.get("/evals/{run_id}", response_model=EvalRunDetail)
def get_eval_run(
    run_id: uuid.UUID,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> EvalRun:
    run = db.get(EvalRun, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="eval run not found")
    _assert_member(user, run.organization_id, db)
    results = list(
        db.scalars(
            select(EvalSampleResult)
            .where(EvalSampleResult.eval_run_id == run.id)
            .order_by(EvalSampleResult.created_at.asc())
        )
    )
    detail = EvalRunDetail.model_validate(run)
    detail.results = results
    return detail
