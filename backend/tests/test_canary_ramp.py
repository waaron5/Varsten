"""Canary ramp for policy activation (slice C4).

A routing/trim policy can activate at a small rollout and be promoted stage by
stage once each stage shows no quality or latency regression. Traffic outside the
rollout is plain passthrough, never an experiment arm.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.core.config import settings
from app.models import Project, ProxyPolicy, Recommendation, RecommendationAction, UsageEvent
from app.proxy import canary, routing
from app.proxy import drift as drift_mod
from app.savings import month_start

INCUMBENT = "gpt-4o"
CANDIDATE = "gpt-4o-mini"


# --- pure policy ---------------------------------------------------------------


def test_in_rollout_edges():
    assert canary.in_rollout(100) is True
    assert canary.in_rollout(None) is True
    assert canary.in_rollout(0) is False


def test_in_rollout_respects_percent(monkeypatch):
    # Draw just below / above the threshold deterministically.
    monkeypatch.setattr(canary.random, "random", lambda: 0.09)
    assert canary.in_rollout(10) is True
    monkeypatch.setattr(canary.random, "random", lambda: 0.11)
    assert canary.in_rollout(10) is False


def test_next_stage():
    assert canary.next_stage(0) == 10
    assert canary.next_stage(10) == 50
    assert canary.next_stage(50) == 100
    assert canary.next_stage(100) is None


def test_initial_rollout_percent(monkeypatch):
    monkeypatch.setattr(settings, "canary_enabled", False)
    assert canary.initial_rollout_percent() == 100
    monkeypatch.setattr(settings, "canary_enabled", True)
    monkeypatch.setattr(settings, "canary_initial_percent", 10)
    assert canary.initial_rollout_percent() == 10


# --- resolve_route gate --------------------------------------------------------


def _policy(project, *, rollout_percent, **kw):
    return ProxyPolicy(
        organization_id=project.organization_id,
        project_id=project.id,
        lever="model_downshift",
        target_type="model",
        target_key=INCUMBENT,
        params={"candidate_model": CANDIDATE},
        enabled=True,
        rollout_percent=rollout_percent,
        **kw,
    )


@pytest.mark.anyio
async def test_resolve_route_skips_out_of_rollout(async_provision, async_db_session):
    ws = await async_provision()
    project = await async_db_session.get(Project, uuid.UUID(ws["project_id"]))
    async_db_session.add(_policy(project, rollout_percent=0))
    await async_db_session.flush()

    decision = await routing.resolve_route(async_db_session, project.id, INCUMBENT, {"messages": []})
    assert decision is None


@pytest.mark.anyio
async def test_resolve_route_applies_when_fully_rolled_out(async_provision, async_db_session):
    ws = await async_provision()
    project = await async_db_session.get(Project, uuid.UUID(ws["project_id"]))
    async_db_session.add(_policy(project, rollout_percent=100))
    await async_db_session.flush()

    decision = await routing.resolve_route(async_db_session, project.id, INCUMBENT, {"messages": []})
    assert decision is not None
    assert decision.candidate_model == CANDIDATE


# --- activation ----------------------------------------------------------------


def _rec(db_session, project) -> Recommendation:
    rec = Recommendation(
        organization_id=project.organization_id,
        project_id=project.id,
        dedupe_key=f"rec-{uuid.uuid4()}",
        type="model_downshift",
        lever="model_downshift",
        title="Route gpt-4o -> gpt-4o-mini",
        description="x",
        risk_level="medium",
        confidence="medium",
        related_model=INCUMBENT,
    )
    db_session.add(rec)
    db_session.flush()
    return rec


def _project(db_session, provision) -> Project:
    p = provision()
    return db_session.get(Project, uuid.UUID(p["project_id"]))


def test_activation_starts_at_canary_when_enabled(db_session, provision, monkeypatch):
    monkeypatch.setattr(settings, "canary_enabled", True)
    monkeypatch.setattr(settings, "canary_initial_percent", 10)
    project = _project(db_session, provision)
    rec = _rec(db_session, project)

    policy = routing.activate_rule(db_session, project, rec, CANDIDATE)
    db_session.flush()

    assert policy is not None
    assert policy.rollout_percent == 10


def test_activation_is_fully_live_when_canary_off(db_session, provision, monkeypatch):
    monkeypatch.setattr(settings, "canary_enabled", False)
    project = _project(db_session, provision)
    rec = _rec(db_session, project)

    policy = routing.activate_rule(db_session, project, rec, CANDIDATE)
    db_session.flush()

    assert policy is not None
    assert policy.rollout_percent == 100


# --- promotion in the drift sweep ----------------------------------------------

_JITTER = (-20, -5, 5, 20)


def _seed_healthy(db_session, project, arm, *, count):
    model = INCUMBENT if arm == "control" else CANDIDATE
    meta = {
        "proxy": True,
        "holdback": True,
        "arm": arm,
        "experiment_from": INCUMBENT,
        "experiment_to": CANDIDATE,
        "quality_ok": True,
    }
    for i in range(count):
        db_session.add(
            UsageEvent(
                project_id=project.id,
                organization_id=project.organization_id,
                api_key_id=None,
                provider="openai",
                model=model,
                operation="chat_completion",
                request_type="chat_completion",
                feature="proxy",
                environment="production",
                input_tokens=1000,
                output_tokens=500,
                cached_input_tokens=0,
                total_tokens=1500,
                cost_usd=Decimal("0.001"),
                cost_source="catalog",
                pricing_status="priced",
                currency="USD",
                status="success",
                success=True,
                latency_ms=300 + _JITTER[i % 4],
                event_metadata=meta,
                occurred_at=datetime.now(UTC),
            )
        )
    db_session.flush()


def _canaried_policy(db_session, project, *, rollout_percent) -> ProxyPolicy:
    rec = _rec(db_session, project)
    policy = _policy(project, rollout_percent=rollout_percent, source_recommendation_id=rec.id)
    db_session.add(policy)
    db_session.flush()
    return policy


def test_canary_promotes_through_stages(db_session, provision, monkeypatch):
    monkeypatch.setattr(settings, "canary_enabled", True)
    monkeypatch.setattr(drift_mod, "MIN_ARM_SAMPLES", 10)
    project = _project(db_session, provision)
    policy = _canaried_policy(db_session, project, rollout_percent=10)
    # Healthy arms: quality holds, latency comparable -> no regression.
    _seed_healthy(db_session, project, "control", count=15)
    _seed_healthy(db_session, project, "treatment", count=15)
    db_session.commit()

    start = month_start(datetime.now(UTC))
    drift_mod.check_and_rollback_drift(db_session, project, start)
    db_session.refresh(policy)
    assert policy.rollout_percent == 50

    drift_mod.check_and_rollback_drift(db_session, project, start)
    db_session.refresh(policy)
    assert policy.rollout_percent == 100

    # Fully live: no further promotion.
    drift_mod.check_and_rollback_drift(db_session, project, start)
    db_session.refresh(policy)
    assert policy.rollout_percent == 100

    promotions = (
        db_session.query(RecommendationAction)
        .filter(RecommendationAction.project_id == project.id, RecommendationAction.action_type == "canary_promoted")
        .all()
    )
    assert len(promotions) == 2


def test_no_promotion_without_enough_signal(db_session, provision, monkeypatch):
    monkeypatch.setattr(settings, "canary_enabled", True)
    monkeypatch.setattr(drift_mod, "MIN_ARM_SAMPLES", 30)
    project = _project(db_session, provision)
    policy = _canaried_policy(db_session, project, rollout_percent=10)
    _seed_healthy(db_session, project, "control", count=5)
    _seed_healthy(db_session, project, "treatment", count=5)
    db_session.commit()

    drift_mod.check_and_rollback_drift(db_session, project, month_start(datetime.now(UTC)))
    db_session.refresh(policy)
    assert policy.rollout_percent == 10
