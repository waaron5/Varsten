"""Cheaper-model routing: the execution side of the lever.

Covers rule activation/deactivation on apply/dismiss, hot-path resolution,
naive-vs-optimized metering, and the proxy actually rewriting the upstream model.
OpenAI is mocked via httpx MockTransport.
"""
import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models import (
    EvalRun,
    ModelPrice,
    Project,
    ProxyRoutingRule,
    Recommendation,
    UsageEvent,
)
from app.models.eval import RUN_COMPLETED, VERDICT_SAFE
from app.proxy import circuit
from app.proxy import router as proxy_router
from app.proxy.ledger import record_proxy_usage
from app.proxy.routing import (
    activate_rule,
    deactivate_rules_for_recommendation,
    resolve_effective_model,
)

INCUMBENT = "gpt-4o"
CANDIDATE = "gpt-4o-mini"


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


def _seed_prices(db, project):
    at = datetime.now(timezone.utc) - timedelta(days=1)
    db.add_all([
        ModelPrice(
            model_key=INCUMBENT, provider="openai", currency="USD",
            input_cost_per_token=Decimal("0.000005"), output_cost_per_token=Decimal("0.000015"),
            source="catalog", effective_at=at,
        ),
        ModelPrice(
            model_key=CANDIDATE, provider="openai", currency="USD",
            input_cost_per_token=Decimal("0.0000006"), output_cost_per_token=Decimal("0.0000024"),
            source="catalog", effective_at=at,
        ),
    ])
    db.commit()


# --- rule lifecycle -------------------------------------------------------------

def test_resolve_effective_model_only_when_enabled(client, provision, db_session):
    project = _project(db_session, provision)
    rule = ProxyRoutingRule(
        organization_id=project.organization_id, project_id=project.id,
        incumbent_model=INCUMBENT, candidate_model=CANDIDATE, enabled=True,
    )
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
    rule = db_session.scalar(select(ProxyRoutingRule).where(ProxyRoutingRule.project_id == project.id))
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
            organization_id=project.organization_id, project_id=project.id,
            recommendation_id=rec.id, lever="cheaper_model", route_key=INCUMBENT,
            incumbent_model=INCUMBENT, candidate_model=CANDIDATE,
            status=RUN_COMPLETED, verdict=VERDICT_SAFE, cost_delta_usd=Decimal("100"),
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
    rule = db_session.scalar(select(ProxyRoutingRule).where(ProxyRoutingRule.project_id == project.id))
    assert rule is not None and rule.enabled and rule.candidate_model == CANDIDATE


# --- metering -------------------------------------------------------------------

def test_routed_usage_meters_measured_savings(client, provision, db_session):
    project = _project(db_session, provision)
    _seed_prices(db_session, project)
    event = record_proxy_usage(
        db_session, project, None,
        model=CANDIDATE, input_tokens=1000, output_tokens=500,
        cached_input_tokens=0, cache_hit=False, naive_model=INCUMBENT,
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
        return httpx.Response(200, json={
            "id": "chatcmpl-x", "object": "chat.completion", "model": payload["model"],
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500},
        })

    real = httpx.AsyncClient
    monkeypatch.setattr(proxy_router.httpx, "AsyncClient", lambda *a, **k: real(transport=httpx.MockTransport(handler)))


def test_proxy_routes_request_to_candidate(client, provision, db_session, monkeypatch):
    monkeypatch.setattr(settings, "semantic_cache_enabled", False)  # skip embeddings
    ws = provision(sub="auth0|route2", email="route2@example.com")
    project = db_session.get(Project, uuid.UUID(ws["project_id"]))
    monkeypatch.setattr(settings, "proxy_openai_keys", {str(project.id): "sk-test"})
    _seed_prices(db_session, project)
    db_session.add(
        ProxyRoutingRule(
            organization_id=project.organization_id, project_id=project.id,
            incumbent_model=INCUMBENT, candidate_model=CANDIDATE, enabled=True,
        )
    )
    db_session.commit()

    seen: dict = {}
    _mock_openai(monkeypatch, seen)

    resp = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {ws['api_key']}"},
        json={"model": INCUMBENT, "messages": [{"role": "user", "content": "hi"}], "stream": False},
    )
    assert resp.status_code == 200
    # The proxy rewrote the upstream model to the cheaper candidate.
    assert seen["model"] == CANDIDATE
    assert resp.headers.get("X-Varsten-Routed") == f"{INCUMBENT}->{CANDIDATE}"

    event = db_session.scalar(
        select(UsageEvent).where(UsageEvent.project_id == project.id, UsageEvent.model == CANDIDATE)
    )
    assert event is not None and event.event_metadata.get("routed") is True


def test_bypass_disables_routing(client, provision, db_session, monkeypatch):
    monkeypatch.setattr(settings, "semantic_cache_enabled", False)
    ws = provision(sub="auth0|route3", email="route3@example.com")
    project = db_session.get(Project, uuid.UUID(ws["project_id"]))
    monkeypatch.setattr(settings, "proxy_openai_keys", {str(project.id): "sk-test"})
    project.proxy_bypass_enabled = True
    db_session.add(
        ProxyRoutingRule(
            organization_id=project.organization_id, project_id=project.id,
            incumbent_model=INCUMBENT, candidate_model=CANDIDATE, enabled=True,
        )
    )
    db_session.commit()

    seen: dict = {}
    _mock_openai(monkeypatch, seen)
    resp = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {ws['api_key']}"},
        json={"model": INCUMBENT, "messages": [{"role": "user", "content": "hi"}], "stream": False},
    )
    assert resp.status_code == 200
    # Kill switch / bypass means the incumbent is used unchanged.
    assert seen["model"] == INCUMBENT
    assert "X-Varsten-Routed" not in resp.headers
