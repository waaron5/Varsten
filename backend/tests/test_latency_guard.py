"""Latency guardrail (slice C3): a treatment arm that is confidently slower than
its control arm -- or confidently above a route SLO -- rolls back like quality
drift. A cheaper model is allowed to be somewhat slower; only a regression beyond
tolerance, confirmed by the peeking-safe confidence sequence, triggers rollback.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from app.models import Project, ProxyPolicy, QualityGuardrail, Recommendation, UsageEvent
from app.proxy import drift as drift_mod
from app.savings import month_start

INCUMBENT = "gpt-4o"
CANDIDATE = "gpt-4o-mini"


def _project(db_session, provision) -> Project:
    p = provision()
    return db_session.get(Project, uuid.UUID(p["project_id"]))


def _rule(db_session, project) -> tuple[ProxyPolicy, Recommendation]:
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
    policy = ProxyPolicy(
        organization_id=project.organization_id,
        project_id=project.id,
        lever="model_downshift",
        target_type="model",
        target_key=INCUMBENT,
        params={"candidate_model": CANDIDATE},
        enabled=True,
        holdback_percent=Decimal("0.1"),
        source_recommendation_id=rec.id,
    )
    db_session.add(policy)
    db_session.flush()
    return policy, rec


# Small deterministic jitter so each arm has non-zero latency variance (constant
# values give var_samp = 0 and no confidence sequence, which real traffic never does).
_JITTER = (-30, -10, 10, 30)


def _record(db_session, project, arm, *, latency_ms, quality_ok=None, count=40):
    model = INCUMBENT if arm == "control" else CANDIDATE
    meta = {
        "proxy": True,
        "holdback": True,
        "arm": arm,
        "experiment_from": INCUMBENT,
        "experiment_to": CANDIDATE,
    }
    if quality_ok is not None:
        meta["quality_ok"] = quality_ok
    for i in range(count):
        jittered = latency_ms + _JITTER[i % len(_JITTER)]
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
                latency_ms=jittered,
                event_metadata=meta,
                occurred_at=datetime.now(UTC),
            )
        )
    db_session.flush()


def test_latency_regression_detected(db_session, provision):
    project = _project(db_session, provision)
    # Control ~200ms, treatment ~1500ms: 1.3s slower, far beyond the 400ms tolerance.
    _record(db_session, project, "control", latency_ms=200)
    _record(db_session, project, "treatment", latency_ms=1500)
    db_session.commit()

    result = drift_mod.evaluate_latency_drift(
        db_session, project.id, INCUMBENT, CANDIDATE, month_start(datetime.now(UTC))
    )
    assert result["enough_signal"] is True
    assert result["regressed"] is True
    assert result["latency_delta_ms"] == 1300


def test_slower_but_within_tolerance_is_not_a_regression(db_session, provision):
    project = _project(db_session, provision)
    # Treatment 250ms slower: allowed (cheaper models can be a bit slower).
    _record(db_session, project, "control", latency_ms=300)
    _record(db_session, project, "treatment", latency_ms=550)
    db_session.commit()

    result = drift_mod.evaluate_latency_drift(
        db_session, project.id, INCUMBENT, CANDIDATE, month_start(datetime.now(UTC))
    )
    assert result["regressed"] is False
    assert result["slo_breached"] is False


def test_latency_regression_rolls_back_route(db_session, provision, monkeypatch):
    monkeypatch.setattr(drift_mod, "MIN_ARM_SAMPLES", 10)
    project = _project(db_session, provision)
    policy, rec = _rule(db_session, project)
    # Quality holds (both arms pass) but treatment is far slower.
    _record(db_session, project, "control", latency_ms=200, quality_ok=True, count=15)
    _record(db_session, project, "treatment", latency_ms=1600, quality_ok=True, count=15)
    db_session.commit()

    rolled = drift_mod.check_and_rollback_drift(db_session, project, month_start(datetime.now(UTC)))

    assert len(rolled) == 1
    assert rolled[0]["trigger"] == "latency"
    db_session.refresh(policy)
    db_session.refresh(rec)
    assert policy.enabled is False
    assert rec.status == "rolled_back"


def test_latency_slo_breach_rolls_back(db_session, provision, monkeypatch):
    monkeypatch.setattr(drift_mod, "MIN_ARM_SAMPLES", 10)
    project = _project(db_session, provision)
    policy, _ = _rule(db_session, project)
    db_session.add(
        QualityGuardrail(
            organization_id=project.organization_id,
            project_id=project.id,
            route=INCUMBENT,
            max_latency_ms=1000,
            enabled=True,
        )
    )
    # Both arms equally slow (no relative regression) but above the 1000ms SLO.
    _record(db_session, project, "control", latency_ms=1500, quality_ok=True, count=15)
    _record(db_session, project, "treatment", latency_ms=1500, quality_ok=True, count=15)
    db_session.commit()

    rolled = drift_mod.check_and_rollback_drift(db_session, project, month_start(datetime.now(UTC)))

    assert len(rolled) == 1
    assert rolled[0]["trigger"] == "latency_slo"
    db_session.refresh(policy)
    assert policy.enabled is False


def test_latency_guard_disabled_does_not_roll_back(db_session, provision, monkeypatch):
    monkeypatch.setattr(drift_mod, "MIN_ARM_SAMPLES", 10)
    monkeypatch.setattr(drift_mod.settings, "latency_guard_enabled", False)
    monkeypatch.setattr(drift_mod.settings, "latency_slo_enabled", False)
    project = _project(db_session, provision)
    policy, _ = _rule(db_session, project)
    _record(db_session, project, "control", latency_ms=200, quality_ok=True, count=15)
    _record(db_session, project, "treatment", latency_ms=1600, quality_ok=True, count=15)
    db_session.commit()

    rolled = drift_mod.check_and_rollback_drift(db_session, project, month_start(datetime.now(UTC)))
    assert rolled == []
    db_session.refresh(policy)
    assert policy.enabled is True
