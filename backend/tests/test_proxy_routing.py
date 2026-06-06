"""Cheaper-model routing: the execution side of the lever.

Covers rule activation/deactivation on apply/dismiss, hot-path resolution,
naive-vs-optimized metering, and the proxy actually rewriting the upstream model.
OpenAI is mocked via httpx MockTransport.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models import (
    EvalRun,
    ModelPrice,
    Project,
    ProxyPolicy,
    Recommendation,
    RecommendationAction,
    UsageEvent,
)
from app.models.eval import RUN_COMPLETED, VERDICT_SAFE
from app.proxy import circuit
from app.proxy import drift as drift_mod
from app.proxy import router as proxy_router
from app.proxy.ledger import record_proxy_usage
from app.proxy.quality import response_quality_ok
from app.proxy.routing import (
    activate_rule,
    deactivate_rules_for_recommendation,
    resolve_effective_model,
)

INCUMBENT = "gpt-4o"
CANDIDATE = "gpt-4o-mini"


def _policy(project, *, incumbent=INCUMBENT, candidate=CANDIDATE, lever="cheaper_model", **kw):
    """Build a routing-lever execution policy in the unified proxy_policies table."""
    return ProxyPolicy(
        organization_id=project.organization_id,
        project_id=project.id,
        lever=lever,
        target_type="model",
        target_key=incumbent,
        params={"candidate_model": candidate},
        **kw,
    )


@pytest.fixture(autouse=True)
def reset_circuit():
    circuit.reset_all()
    yield
    circuit.reset_all()


def _project(db, provision) -> Project:
    ws = provision(sub="auth0|route", email="route@example.com")
    return db.get(Project, uuid.UUID(ws["project_id"]))


def _mk_rec(db, project) -> Recommendation:
    rec = Recommendation(
        organization_id=project.organization_id,
        project_id=project.id,
        dedupe_key=f"k-{uuid.uuid4()}",
        type="cheaper_model",
        lever="cheaper_model",
        title="Evaluate gpt-4o-mini",
        description="x",
        risk_level="medium",
        confidence="medium",
        related_model=INCUMBENT,
        related_provider="openai",
        monthly_request_volume=1000,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


async def _seed_prices(db, project):
    at = datetime.now(UTC) - timedelta(days=1)
    db.add_all(
        [
            ModelPrice(
                model_key=INCUMBENT,
                provider="openai",
                currency="USD",
                input_cost_per_token=Decimal("0.000005"),
                output_cost_per_token=Decimal("0.000015"),
                source="catalog",
                effective_at=at,
            ),
            ModelPrice(
                model_key=CANDIDATE,
                provider="openai",
                currency="USD",
                input_cost_per_token=Decimal("0.0000006"),
                output_cost_per_token=Decimal("0.0000024"),
                source="catalog",
                effective_at=at,
            ),
        ]
    )
    await db.flush()


# --- rule lifecycle -------------------------------------------------------------


def test_resolve_effective_model_only_when_enabled(client, provision, db_session):
    project = _project(db_session, provision)
    rule = _policy(project, enabled=True)
    db_session.add(rule)
    db_session.commit()
    assert resolve_effective_model(db_session, project.id, INCUMBENT) == CANDIDATE
    assert resolve_effective_model(db_session, project.id, "other-model") is None

    rule.enabled = False
    db_session.commit()
    assert resolve_effective_model(db_session, project.id, INCUMBENT) is None


def test_activate_then_deactivate(client, provision, db_session):
    project = _project(db_session, provision)
    rec = _mk_rec(db_session, project)
    activate_rule(db_session, project, rec, CANDIDATE)
    db_session.commit()
    rule = db_session.scalar(select(ProxyPolicy).where(ProxyPolicy.project_id == project.id))
    assert rule.enabled and rule.candidate_model == CANDIDATE and rule.incumbent_model == INCUMBENT

    deactivate_rules_for_recommendation(db_session, rec)
    db_session.commit()
    db_session.refresh(rule)
    assert rule.enabled is False


def test_apply_through_engine_activates_rule(client, provision, db_session):
    project = _project(db_session, provision)
    rec = _mk_rec(db_session, project)
    db_session.add(
        EvalRun(
            organization_id=project.organization_id,
            project_id=project.id,
            recommendation_id=rec.id,
            lever="cheaper_model",
            route_key=INCUMBENT,
            incumbent_model=INCUMBENT,
            candidate_model=CANDIDATE,
            status=RUN_COMPLETED,
            verdict=VERDICT_SAFE,
            cost_delta_usd=Decimal("100"),
        )
    )
    db_session.commit()

    resp = client.patch(
        f"/v1/engine/recommendations/{rec.id}",
        headers={"Authorization": "Bearer auth0|route"},
        params={"project_id": str(project.id)},
        json={"status": "applied"},
    )
    assert resp.status_code == 200
    rule = db_session.scalar(select(ProxyPolicy).where(ProxyPolicy.project_id == project.id))
    assert rule is not None and rule.enabled and rule.candidate_model == CANDIDATE


# --- metering -------------------------------------------------------------------


@pytest.mark.anyio
async def test_routed_usage_meters_measured_savings(async_provision, async_db_session):
    ws = await async_provision(sub="auth0|routed", email="routed@example.com")
    project = await async_db_session.get(Project, uuid.UUID(ws["project_id"]))
    await _seed_prices(async_db_session, project)
    event = await record_proxy_usage(
        async_db_session,
        project,
        None,
        model=CANDIDATE,
        input_tokens=1000,
        output_tokens=500,
        cached_input_tokens=0,
        cache_hit=False,
        naive_model=INCUMBENT,
    )
    # Actual spend is the candidate's cost; saved is incumbent minus candidate.
    assert event.model == CANDIDATE
    assert event.event_metadata["routed"] is True
    assert event.event_metadata["routed_from"] == INCUMBENT
    assert Decimal(event.event_metadata["saved_usd"]) > 0
    # candidate cost = 1000*6e-7 + 500*2.4e-6 = 0.0006 + 0.0012 = 0.0018
    assert event.cost_usd == Decimal("0.0018")


# --- proxy rewrites the upstream model ------------------------------------------


def _mock_openai(monkeypatch, seen: dict):
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen["model"] = payload["model"]
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-x",
                "object": "chat.completion",
                "model": payload["model"],
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500},
            },
        )

    real = httpx.AsyncClient
    monkeypatch.setattr(proxy_router.httpx, "AsyncClient", lambda *a, **k: real(transport=httpx.MockTransport(handler)))


@pytest.mark.anyio
async def test_proxy_routes_request_to_candidate(async_client, async_provision, async_db_session, monkeypatch):
    monkeypatch.setattr(settings, "proxy_cache_enabled", False)  # skip embeddings
    ws = await async_provision(sub="auth0|route2", email="route2@example.com")
    project = await async_db_session.get(Project, uuid.UUID(ws["project_id"]))
    monkeypatch.setattr(settings, "proxy_openai_keys", {str(project.id): "sk-test"})
    await _seed_prices(async_db_session, project)
    async_db_session.add(
        _policy(project, enabled=True, holdback_percent=Decimal("0"))  # no holdback: deterministically treatment
    )
    await async_db_session.flush()

    seen: dict = {}
    _mock_openai(monkeypatch, seen)

    resp = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {ws['api_key']}"},
        json={"model": INCUMBENT, "messages": [{"role": "user", "content": "hi"}], "stream": False},
    )
    assert resp.status_code == 200
    # The proxy rewrote the upstream model to the cheaper candidate.
    assert seen["model"] == CANDIDATE
    assert resp.headers.get("X-Varsten-Routed") == f"{INCUMBENT}->{CANDIDATE}"
    assert resp.headers.get("X-Varsten-Arm") == "treatment"

    event = await async_db_session.scalar(
        select(UsageEvent).where(UsageEvent.project_id == project.id, UsageEvent.model == CANDIDATE)
    )
    assert event is not None and event.event_metadata.get("routed") is True


def _usage_row(project, model, cost, meta):
    """A ledger row mirroring what record_proxy_usage writes, built via sync ORM so
    the sync drift/reporting endpoints (a separate connection from the async proxy)
    can read it. Costs match the seeded catalog rates for 1000 in / 500 out."""
    return UsageEvent(
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
        cost_usd=cost,
        cost_source="catalog",
        pricing_status="priced",
        currency="USD",
        status="success",
        success=True,
        event_metadata=meta,
        occurred_at=datetime.now(UTC),
    )


def _arm_meta(arm: str, *, quality_ok: bool | None = None) -> dict:
    if arm == "treatment":
        meta = {
            "proxy": True,
            "cache": "miss",
            "routed": True,
            "routed_from": INCUMBENT,
            "routed_to": CANDIDATE,
            "naive_cost_usd": "0.0125",
            "saved_usd": "0.0107",
            "holdback": True,
            "arm": "treatment",
            "experiment_from": INCUMBENT,
            "experiment_to": CANDIDATE,
        }
    else:
        meta = {
            "proxy": True,
            "cache": "miss",
            "holdback": True,
            "arm": "control",
            "experiment_from": INCUMBENT,
            "experiment_to": CANDIDATE,
        }
    if quality_ok is not None:
        meta["quality_ok"] = quality_ok
    return meta


def _record_arm(db, project, arm, model):
    cost = Decimal("0.0018") if arm == "treatment" else Decimal("0.0125")
    db.add(_usage_row(project, model, cost, _arm_meta(arm)))


def test_engine_routes_reports_holdback_ab(client, provision, db_session):
    project = _project(db_session, provision)
    db_session.add(_policy(project, enabled=True, holdback_percent=Decimal("0.1"), activated_at=datetime.now(UTC)))
    # Concurrent arms: control stays on the incumbent, treatment routes to candidate.
    for _ in range(2):
        _record_arm(db_session, project, "control", INCUMBENT)
    for _ in range(3):
        _record_arm(db_session, project, "treatment", CANDIDATE)
    db_session.commit()

    resp = client.get(
        "/v1/engine/routes",
        headers={"Authorization": "Bearer auth0|route"},
        params={"project_id": str(project.id)},
    )
    assert resp.status_code == 200
    route = resp.json()[0]
    assert route["control_requests"] == 2 and route["treatment_requests"] == 3
    # control avg = incumbent 0.0125, treatment avg = candidate 0.0018
    assert Decimal(route["control_avg_cost_usd"]) == Decimal("0.0125")
    assert Decimal(route["treatment_avg_cost_usd"]) == Decimal("0.0018")
    # per-request savings 0.0107 measured against the live control arm, x3 treatment
    assert Decimal(route["savings_per_request_usd"]) == Decimal("0.0107")
    assert Decimal(route["measured_savings_usd"]) == Decimal("0.0321")
    assert route["has_signal"] is False  # below the per-arm sample floor


def test_engine_route_patch_pauses_and_sets_holdback(client, provision, db_session):
    project = _project(db_session, provision)
    rule = _policy(project, enabled=True, holdback_percent=Decimal("0.05"))
    db_session.add(rule)
    db_session.commit()

    resp = client.patch(
        f"/v1/engine/routes/{rule.id}",
        headers={"Authorization": "Bearer auth0|route"},
        params={"project_id": str(project.id)},
        json={"enabled": False, "holdback_percent": "0.2"},
    )
    assert resp.status_code == 200
    db_session.refresh(rule)
    assert rule.enabled is False and rule.holdback_percent == Decimal("0.2")
    # Over the 50% cap is rejected.
    bad = client.patch(
        f"/v1/engine/routes/{rule.id}",
        headers={"Authorization": "Bearer auth0|route"},
        params={"project_id": str(project.id)},
        json={"holdback_percent": "0.9"},
    )
    assert bad.status_code == 422


def _completion_payload(content: str, finish: str = "stop") -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": finish}]}


def test_response_quality_ok_objective_signal():
    assert response_quality_ok(_completion_payload("a real answer"), False) is True
    assert response_quality_ok(_completion_payload(""), False) is False
    assert response_quality_ok(_completion_payload("cut off", finish="length"), False) is False
    assert response_quality_ok(_completion_payload('{"ok": 1}'), True) is True
    assert response_quality_ok(_completion_payload("not json"), True) is False
    assert response_quality_ok(None, False) is False


def _record_q(db, project, arm, model, ok):
    cost = Decimal("0.0018") if arm == "treatment" else Decimal("0.0125")
    db.add(_usage_row(project, model, cost, _arm_meta(arm, quality_ok=ok)))


def _rule_with_rec(db, project):
    rec = _mk_rec(db, project)
    rule = _policy(project, enabled=True, holdback_percent=Decimal("0.1"), source_recommendation_id=rec.id)
    db.add(rule)
    db.commit()
    return rule, rec


def test_drift_auto_rollback(client, provision, db_session, monkeypatch):
    monkeypatch.setattr(drift_mod, "MIN_ARM_SAMPLES", 4)
    project = _project(db_session, provision)
    rule, rec = _rule_with_rec(db_session, project)
    # Control healthy, treatment degraded: a clear, significant quality drop.
    for _ in range(5):
        _record_q(db_session, project, "control", INCUMBENT, True)
    for _ in range(5):
        _record_q(db_session, project, "treatment", CANDIDATE, False)
    db_session.commit()

    resp = client.post(
        "/v1/engine/routes/check-drift",
        headers={"Authorization": "Bearer auth0|route"},
        params={"project_id": str(project.id)},
    )
    assert resp.status_code == 200
    assert len(resp.json()["rolled_back"]) == 1

    db_session.refresh(rule)
    db_session.refresh(rec)
    assert rule.enabled is False
    assert rec.status == "rolled_back"
    action = db_session.scalar(
        select(RecommendationAction).where(
            RecommendationAction.project_id == project.id,
            RecommendationAction.action_type == "rolled_back",
        )
    )
    assert action is not None and action.source == "system"


def test_no_rollback_when_quality_holds(client, provision, db_session, monkeypatch):
    monkeypatch.setattr(drift_mod, "MIN_ARM_SAMPLES", 4)
    project = _project(db_session, provision)
    rule, _ = _rule_with_rec(db_session, project)
    for _ in range(5):
        _record_q(db_session, project, "control", INCUMBENT, True)
    for _ in range(5):
        _record_q(db_session, project, "treatment", CANDIDATE, True)
    db_session.commit()

    resp = client.post(
        "/v1/engine/routes/check-drift",
        headers={"Authorization": "Bearer auth0|route"},
        params={"project_id": str(project.id)},
    )
    assert resp.json()["rolled_back"] == []
    db_session.refresh(rule)
    assert rule.enabled is True


def test_drift_needs_enough_samples(client, provision, db_session, monkeypatch):
    monkeypatch.setattr(drift_mod, "MIN_ARM_SAMPLES", 10)
    project = _project(db_session, provision)
    rule, _ = _rule_with_rec(db_session, project)
    # Degraded but too few samples to act on.
    for _ in range(3):
        _record_q(db_session, project, "control", INCUMBENT, True)
    for _ in range(3):
        _record_q(db_session, project, "treatment", CANDIDATE, False)
    db_session.commit()

    resp = client.post(
        "/v1/engine/routes/check-drift",
        headers={"Authorization": "Bearer auth0|route"},
        params={"project_id": str(project.id)},
    )
    assert resp.json()["rolled_back"] == []
    db_session.refresh(rule)
    assert rule.enabled is True


@pytest.mark.anyio
async def test_holdback_keeps_control_on_incumbent(async_client, async_provision, async_db_session, monkeypatch):
    monkeypatch.setattr(settings, "proxy_cache_enabled", False)
    ws = await async_provision(sub="auth0|route4", email="route4@example.com")
    project = await async_db_session.get(Project, uuid.UUID(ws["project_id"]))
    monkeypatch.setattr(settings, "proxy_openai_keys", {str(project.id): "sk-test"})
    await _seed_prices(async_db_session, project)
    async_db_session.add(
        _policy(project, enabled=True, holdback_percent=Decimal("1.0"))  # always control
    )
    await async_db_session.flush()

    seen: dict = {}
    _mock_openai(monkeypatch, seen)
    resp = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {ws['api_key']}"},
        json={"model": INCUMBENT, "messages": [{"role": "user", "content": "hi"}], "stream": False},
    )
    assert resp.status_code == 200
    # Held back: the incumbent answered, tagged as the control arm.
    assert seen["model"] == INCUMBENT
    assert resp.headers.get("X-Varsten-Arm") == "control"
    assert "X-Varsten-Routed" not in resp.headers
    event = await async_db_session.scalar(select(UsageEvent).where(UsageEvent.project_id == project.id))
    assert event.event_metadata.get("arm") == "control" and event.event_metadata.get("holdback") is True


@pytest.mark.anyio
async def test_bypass_disables_routing(async_client, async_provision, async_db_session, monkeypatch):
    monkeypatch.setattr(settings, "proxy_cache_enabled", False)
    ws = await async_provision(sub="auth0|route3", email="route3@example.com")
    project = await async_db_session.get(Project, uuid.UUID(ws["project_id"]))
    monkeypatch.setattr(settings, "proxy_openai_keys", {str(project.id): "sk-test"})
    project.proxy_bypass_enabled = True
    async_db_session.add(_policy(project, enabled=True))
    await async_db_session.flush()

    seen: dict = {}
    _mock_openai(monkeypatch, seen)
    resp = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {ws['api_key']}"},
        json={"model": INCUMBENT, "messages": [{"role": "user", "content": "hi"}], "stream": False},
    )
    assert resp.status_code == 200
    # Kill switch / bypass means the incumbent is used unchanged.
    assert seen["model"] == INCUMBENT
    assert "X-Varsten-Routed" not in resp.headers
