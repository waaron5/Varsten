"""Learning-loop promotion: measured evidence becomes open recommendations.

Covers the phase-A loop closure: decision evidence + feedback that clears the
readiness bar is promoted into a Recommendation that enters the existing
eval-gate/apply pipeline, and everything below the bar (or already running, or
not a policy-backed lever) is left alone.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.engine.promotion import adjust_adaptive_holdbacks, promote_learning_candidates, sweep_all_projects
from app.models import (
    EngineOutcomePrior,
    LeverConfig,
    Project,
    ProxyPolicy,
    Recommendation,
    RecommendationAction,
    RequestDecisionEvent,
    RequestFeedback,
    UsageEvent,
)


def _project(db_session, project_id: str) -> Project:
    return db_session.get(Project, uuid.UUID(project_id))


def _add_decisions(
    db_session,
    project: Project,
    count: int,
    *,
    lever: str = "model_downshift",
    model_requested: str = "gpt-4o",
    model_chosen: str = "gpt-4o-mini",
    savings: str | None = "0.01",
    quality_ok: bool | None = True,
    feedback_outcome: str | None = "accepted",
) -> list[RequestDecisionEvent]:
    decisions = []
    for i in range(count):
        decision = RequestDecisionEvent(
            organization_id=project.organization_id,
            project_id=project.id,
            request_id=f"req_{lever}_{i}",
            provider_requested="openai",
            model_requested=model_requested,
            provider_chosen="openai",
            model_chosen=model_chosen,
            decision_type="experiment_treatment",
            lever=lever,
            cache_status="miss",
            optimization_applied=True,
            task_type="classification.intent",
            risk_level="low",
            realized_savings_usd=Decimal(savings) if savings is not None else None,
            pricing_status="priced",
            quality_ok=quality_ok,
        )
        db_session.add(decision)
        decisions.append(decision)
    db_session.flush()
    if feedback_outcome:
        for decision in decisions:
            db_session.add(
                RequestFeedback(
                    organization_id=project.organization_id,
                    project_id=project.id,
                    decision_event_id=decision.id,
                    request_id=decision.request_id,
                    outcome=feedback_outcome,
                )
            )
        db_session.flush()
    return decisions


def _recommendations(db_session, project: Project) -> list[Recommendation]:
    return list(
        db_session.scalars(
            select(Recommendation).where(
                Recommendation.project_id == project.id,
                Recommendation.dedupe_key.like("engine_learning:%"),
            )
        )
    )


def _recommendation(db_session, project: Project) -> Recommendation:
    rec = Recommendation(
        organization_id=project.organization_id,
        project_id=project.id,
        dedupe_key=f"rec-{uuid.uuid4()}",
        type="model_downshift",
        lever="model_downshift",
        title="Route gpt-4o to gpt-4o-mini",
        description="x",
        risk_level="medium",
        confidence="medium",
        related_model="gpt-4o",
        monthly_request_volume=100,
    )
    db_session.add(rec)
    db_session.flush()
    return rec


def _policy_with_recommendation(
    db_session,
    project: Project,
    *,
    holdback_percent: Decimal,
) -> ProxyPolicy:
    rec = _recommendation(db_session, project)
    policy = ProxyPolicy(
        organization_id=project.organization_id,
        project_id=project.id,
        lever="model_downshift",
        target_type="model",
        target_key="gpt-4o",
        params={"candidate_model": "gpt-4o-mini"},
        enabled=True,
        holdback_percent=holdback_percent,
        source_recommendation_id=rec.id,
    )
    db_session.add(policy)
    db_session.flush()
    return policy


def _add_holdback_usage(
    db_session,
    project: Project,
    *,
    arm: str,
    cost_usd: Decimal,
    idx: int,
    now: datetime,
) -> None:
    model = "gpt-4o" if arm == "control" else "gpt-4o-mini"
    db_session.add(
        UsageEvent(
            project_id=project.id,
            organization_id=project.organization_id,
            provider="openai",
            model=model,
            operation="chat_completion",
            source="proxy",
            request_type="chat_completion",
            feature="proxy",
            environment="production",
            input_tokens=100,
            output_tokens=20,
            total_tokens=120,
            cost_usd=cost_usd,
            cost_source="catalog",
            pricing_status="priced",
            currency="USD",
            status="success",
            success=True,
            event_metadata={
                "holdback": True,
                "arm": arm,
                "experiment_from": "gpt-4o",
                "experiment_to": "gpt-4o-mini",
            },
            received_at=now - timedelta(minutes=idx),
        )
    )


def _seed_holdback_experiment(
    db_session,
    project: Project,
    *,
    now: datetime,
    control_costs: tuple[Decimal, Decimal],
    treatment_costs: tuple[Decimal, Decimal],
    count_per_arm: int = 40,
) -> None:
    for idx in range(count_per_arm):
        _add_holdback_usage(
            db_session,
            project,
            arm="control",
            cost_usd=control_costs[idx % 2],
            idx=idx,
            now=now,
        )
        _add_holdback_usage(
            db_session,
            project,
            arm="treatment",
            cost_usd=treatment_costs[idx % 2],
            idx=count_per_arm + idx,
            now=now,
        )
    db_session.flush()


def test_promotes_recommendable_segment(provision, db_session):
    p = provision()
    project = _project(db_session, p["project_id"])
    _add_decisions(db_session, project, 6)

    promoted = promote_learning_candidates(db_session, project)

    assert len(promoted) == 1
    recs = _recommendations(db_session, project)
    assert len(recs) == 1
    rec = recs[0]
    assert rec.lever == "model_downshift"
    assert rec.status == "open"
    assert rec.target_type == "route"
    assert rec.target_key == "classification.intent"
    assert rec.related_model == "gpt-4o"
    assert rec.confidence == "medium"
    # Forward projection of measured history stays an estimate until the live
    # holdback measures it again.
    assert rec.measurement_method == "estimated"
    assert rec.estimated_monthly_savings_usd == Decimal("0.06")
    assert "Promoted from measured production evidence" in rec.rationale
    assert "recommendable" in rec.rationale


def test_promotion_is_idempotent(provision, db_session):
    p = provision()
    project = _project(db_session, p["project_id"])
    _add_decisions(db_session, project, 6)

    promote_learning_candidates(db_session, project)
    promote_learning_candidates(db_session, project)

    assert len(_recommendations(db_session, project)) == 1


def test_does_not_resurrect_non_open_recommendations(provision, db_session):
    p = provision()
    project = _project(db_session, p["project_id"])
    _add_decisions(db_session, project, 6)

    promote_learning_candidates(db_session, project)
    rec = _recommendations(db_session, project)[0]
    rec.status = "dismissed"
    db_session.flush()

    promote_learning_candidates(db_session, project)

    recs = _recommendations(db_session, project)
    assert len(recs) == 1
    assert recs[0].status == "dismissed"


def test_skips_segment_with_enabled_policy(provision, db_session):
    p = provision()
    project = _project(db_session, p["project_id"])
    _add_decisions(db_session, project, 6)
    db_session.add(
        ProxyPolicy(
            organization_id=project.organization_id,
            project_id=project.id,
            lever="model_downshift",
            target_type="model",
            target_key="gpt-4o",
            enabled=True,
        )
    )
    db_session.flush()

    promoted = promote_learning_candidates(db_session, project)

    assert promoted == []
    assert _recommendations(db_session, project) == []


def test_auto_candidate_proposes_automation_upgrade_without_flipping_mode(provision, db_session):
    p = provision()
    project = _project(db_session, p["project_id"])
    _add_decisions(db_session, project, 20)
    db_session.add(
        ProxyPolicy(
            organization_id=project.organization_id,
            project_id=project.id,
            lever="model_downshift",
            target_type="model",
            target_key="gpt-4o",
            enabled=True,
        )
    )
    config = LeverConfig(
        organization_id=project.organization_id,
        project_id=project.id,
        lever="model_downshift",
        enabled=True,
        automation_mode="approve",
    )
    db_session.add(config)
    db_session.flush()

    promoted = promote_learning_candidates(db_session, project)

    assert len(promoted) == 1
    rec = _recommendations(db_session, project)[0]
    assert rec.type == "automation_upgrade"
    assert rec.lever == "model_downshift"
    assert rec.target_type == "automation_mode"
    assert rec.target_key == "model_downshift"
    assert rec.measurement_method == "estimated"
    assert rec.confidence == "high"
    assert "auto_apply_candidate" in rec.rationale
    db_session.refresh(config)
    assert config.automation_mode == "approve"


def test_does_not_promote_below_readiness_bar(provision, db_session):
    p = provision()
    project = _project(db_session, p["project_id"])
    # Corrective feedback marks the segment quality_risk: never promoted.
    _add_decisions(db_session, project, 6, feedback_outcome="rejected")

    promoted = promote_learning_candidates(db_session, project)

    assert promoted == []
    assert _recommendations(db_session, project) == []


def test_skips_always_on_levers(provision, db_session):
    p = provision()
    project = _project(db_session, p["project_id"])
    # Semantic cache evidence clears the bar but there is nothing to approve.
    _add_decisions(
        db_session,
        project,
        6,
        lever="semantic_cache",
        model_chosen="gpt-4o",
    )

    promoted = promote_learning_candidates(db_session, project)

    assert promoted == []
    assert _recommendations(db_session, project) == []


def test_sweep_promotes_across_projects(provision, db_session):
    p = provision()
    project = _project(db_session, p["project_id"])
    _add_decisions(db_session, project, 6)

    results = sweep_all_projects(db_session)

    assert str(project.id) in results
    assert len(results[str(project.id)]["promoted"]) == 1
    assert results[str(project.id)]["holdback_adjusted"] == []
    assert len(_recommendations(db_session, project)) == 1


def test_sweep_persists_outcome_priors(provision, db_session):
    p = provision()
    project = _project(db_session, p["project_id"])
    _add_decisions(db_session, project, 6)

    sweep_all_projects(db_session)

    priors = list(db_session.scalars(select(EngineOutcomePrior).where(EngineOutcomePrior.project_id == project.id)))
    assert len(priors) == 1
    prior = priors[0]
    assert prior.lever == "model_downshift"
    assert prior.route_key == "classification.intent"
    assert prior.model_requested == "gpt-4o"
    assert prior.model_chosen == "gpt-4o-mini"
    assert prior.readiness_status == "recommendable"
    assert prior.sample_count == 6
    assert prior.measured_savings_count == 6
    assert prior.window_days > 0


def test_adaptive_holdback_shrinks_when_confidence_sequence_excludes_zero(provision, db_session):
    now = datetime(2026, 7, 2, tzinfo=UTC)
    p = provision()
    project = _project(db_session, p["project_id"])
    policy = _policy_with_recommendation(db_session, project, holdback_percent=Decimal("0.05"))
    _seed_holdback_experiment(
        db_session,
        project,
        now=now,
        control_costs=(Decimal("0.020"), Decimal("0.022")),
        treatment_costs=(Decimal("0.010"), Decimal("0.011")),
    )

    adjusted = adjust_adaptive_holdbacks(db_session, project, now=now)

    assert len(adjusted) == 1
    assert adjusted[0]["old_holdback_percent"] == "0.05"
    assert adjusted[0]["new_holdback_percent"] == "0.02"
    db_session.refresh(policy)
    assert policy.holdback_percent == Decimal("0.02")
    action = db_session.scalar(
        select(RecommendationAction).where(
            RecommendationAction.project_id == project.id,
            RecommendationAction.action_type == "holdback_adjusted",
        )
    )
    assert action is not None
    assert action.source == "system"
    assert action.recommendation_id == policy.source_recommendation_id
    assert "cs_low=" in (action.detail or "")


def test_adaptive_holdback_restores_standard_rate_when_sequence_reincludes_zero(provision, db_session):
    now = datetime(2026, 7, 2, tzinfo=UTC)
    p = provision()
    project = _project(db_session, p["project_id"])
    policy = _policy_with_recommendation(db_session, project, holdback_percent=Decimal("0.01"))
    _seed_holdback_experiment(
        db_session,
        project,
        now=now,
        control_costs=(Decimal("0.020"), Decimal("0.022")),
        treatment_costs=(Decimal("0.020"), Decimal("0.022")),
    )

    adjusted = adjust_adaptive_holdbacks(db_session, project, now=now)

    assert len(adjusted) == 1
    assert adjusted[0]["reason"] == "savings_confidence_reincluded_zero"
    db_session.refresh(policy)
    assert policy.holdback_percent == Decimal("0.05")
