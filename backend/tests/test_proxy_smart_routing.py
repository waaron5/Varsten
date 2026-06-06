"""Smart-routing lever: deterministic per-request predicate routing.

Covers the pure eligibility predicate, hot-path behaviour (an easy request is
routed to the candidate, a hard one stays on the incumbent and never enters the
A/B), predicate seeding on activation, and the eval harness filtering its replay
corpus to the predicate-eligible subset.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models import ModelPrice, Project, ProxyPolicy, Recommendation
from app.proxy import circuit
from app.proxy import router as proxy_router
from app.proxy.execution import activate_execution
from app.proxy.predicate import DEFAULT_PREDICATE, is_eligible
from app.proxy.routing import SMART_ROUTING, resolve_route

INCUMBENT = "gpt-4o"
CANDIDATE = "gpt-4o-mini"


@pytest.fixture(autouse=True)
def reset_circuit():
    circuit.reset_all()
    yield
    circuit.reset_all()


def _project(db, provision) -> Project:
    ws = provision(sub="auth0|smart", email="smart@example.com")
    return db.get(Project, uuid.UUID(ws["project_id"]))


def _smart_policy(project, **kw) -> ProxyPolicy:
    params = {"candidate_model": CANDIDATE, "predicate": dict(DEFAULT_PREDICATE)}
    return ProxyPolicy(
        organization_id=project.organization_id,
        project_id=project.id,
        lever=SMART_ROUTING,
        target_type="model",
        target_key=INCUMBENT,
        params=params,
        **kw,
    )


# --- pure predicate -------------------------------------------------------------


def test_predicate_routes_small_plain_prompt():
    body = {"messages": [{"role": "user", "content": "short question"}]}
    assert is_eligible(body, DEFAULT_PREDICATE) is True


def test_predicate_keeps_large_prompt_on_incumbent():
    body = {"messages": [{"role": "user", "content": "x" * 7000}]}
    assert is_eligible(body, DEFAULT_PREDICATE) is False


def test_predicate_keeps_tool_calls_on_incumbent():
    body = {"messages": [{"role": "user", "content": "hi"}], "tools": [{"type": "function"}]}
    assert is_eligible(body, DEFAULT_PREDICATE) is False


def test_predicate_keeps_structured_output_on_incumbent():
    body = {"messages": [{"role": "user", "content": "hi"}], "response_format": {"type": "json_schema"}}
    assert is_eligible(body, DEFAULT_PREDICATE) is False


def test_predicate_keeps_long_generation_on_incumbent():
    body = {"messages": [{"role": "user", "content": "hi"}], "max_tokens": 4000}
    assert is_eligible(body, DEFAULT_PREDICATE) is False


def test_predicate_none_means_always_eligible():
    body = {"messages": [{"role": "user", "content": "x" * 99999}], "tools": [1]}
    assert is_eligible(body, None) is True


# --- resolution honours the predicate ------------------------------------------


def test_resolve_route_routes_eligible_request(client, provision, db_session):
    project = _project(db_session, provision)
    db_session.add(_smart_policy(project, enabled=True))
    db_session.commit()
    easy = {"messages": [{"role": "user", "content": "hi"}]}
    decision = resolve_route(db_session, project.id, INCUMBENT, easy)
    assert decision is not None and decision.candidate_model == CANDIDATE


def test_resolve_route_skips_ineligible_request(client, provision, db_session):
    project = _project(db_session, provision)
    db_session.add(_smart_policy(project, enabled=True))
    db_session.commit()
    hard = {"messages": [{"role": "user", "content": "x" * 9000}]}
    assert resolve_route(db_session, project.id, INCUMBENT, hard) is None


# --- activation seeds the predicate --------------------------------------------


def test_activation_seeds_default_predicate(client, provision, db_session):
    project = _project(db_session, provision)
    rec = Recommendation(
        organization_id=project.organization_id,
        project_id=project.id,
        dedupe_key=f"sr-{uuid.uuid4()}",
        type="smart_routing",
        lever="smart_routing",
        title="Route some traffic",
        description="x",
        risk_level="medium",
        confidence="medium",
        related_model=INCUMBENT,
        related_provider="openai",
        monthly_request_volume=1000,
    )
    db_session.add(rec)
    db_session.commit()

    # A gating run stand-in carrying the candidate model.
    class _Run:
        candidate_model = CANDIDATE

    activate_execution(db_session, project, rec, _Run())
    db_session.commit()
    policy = db_session.scalar(select(ProxyPolicy).where(ProxyPolicy.project_id == project.id))
    assert policy.lever == SMART_ROUTING
    assert policy.candidate_model == CANDIDATE
    assert policy.params.get("predicate", {}).get("max_prompt_chars") == DEFAULT_PREDICATE["max_prompt_chars"]


# --- hot path -------------------------------------------------------------------


def _seed_prices(db):
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
    db.commit()


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
                "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
            },
        )

    real = httpx.AsyncClient
    monkeypatch.setattr(proxy_router.httpx, "AsyncClient", lambda *a, **k: real(transport=httpx.MockTransport(handler)))


def _setup_proxy(provision, db_session, monkeypatch, sub):
    monkeypatch.setattr(settings, "semantic_cache_enabled", False)
    ws = provision(sub=sub, email=f"{sub}@example.com")
    project = db_session.get(Project, uuid.UUID(ws["project_id"]))
    monkeypatch.setattr(settings, "proxy_openai_keys", {str(project.id): "sk-test"})
    _seed_prices(db_session)
    db_session.add(_smart_policy(project, enabled=True, holdback_percent=Decimal("0")))
    db_session.commit()
    return ws


def test_proxy_routes_easy_request_to_candidate(client, provision, db_session, monkeypatch):
    ws = _setup_proxy(provision, db_session, monkeypatch, "auth0|smart2")
    seen: dict = {}
    _mock_openai(monkeypatch, seen)
    resp = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {ws['api_key']}"},
        json={"model": INCUMBENT, "messages": [{"role": "user", "content": "hi"}], "stream": False},
    )
    assert resp.status_code == 200
    assert seen["model"] == CANDIDATE
    assert resp.headers.get("X-Varsten-Routed") == f"{INCUMBENT}->{CANDIDATE}"


def test_proxy_keeps_hard_request_on_incumbent(client, provision, db_session, monkeypatch):
    ws = _setup_proxy(provision, db_session, monkeypatch, "auth0|smart3")
    seen: dict = {}
    _mock_openai(monkeypatch, seen)
    resp = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {ws['api_key']}"},
        json={"model": INCUMBENT, "messages": [{"role": "user", "content": "x" * 9000}], "stream": False},
    )
    assert resp.status_code == 200
    # Predicate rejected it: incumbent answered, no routing, not in the experiment.
    assert seen["model"] == INCUMBENT
    assert "X-Varsten-Routed" not in resp.headers
    assert "X-Varsten-Arm" not in resp.headers


# --- eval filters to the eligible subset ----------------------------------------


def test_eval_filters_corpus_to_eligible_subset(client, provision, db_session, monkeypatch):
    import asyncio

    from app.eval import runner
    from app.models import EvalRun, ReplaySample
    from app.models.eval import SOURCE_TRAFFIC

    project = _project(db_session, provision)
    _seed_prices(db_session)

    def _sample(content, **params):
        return ReplaySample(
            organization_id=project.organization_id,
            project_id=project.id,
            route_key=INCUMBENT,
            source=SOURCE_TRAFFIC,
            incumbent_model=INCUMBENT,
            request_messages=[{"role": "user", "content": content}],
            request_params=params,
            incumbent_response={
                "choices": [{"message": {"role": "assistant", "content": "ans"}, "finish_reason": "stop"}]
            },
            input_tokens=10,
            output_tokens=5,
        )

    # Two eligible (small) samples, two ineligible (huge / tool call).
    db_session.add_all(
        [
            _sample("easy one"),
            _sample("easy two"),
            _sample("x" * 9000),
            _sample("hi", tools=[{"type": "function"}]),
        ]
    )
    run = EvalRun(
        organization_id=project.organization_id,
        project_id=project.id,
        recommendation_id=None,
        lever="smart_routing",
        route_key=INCUMBENT,
        incumbent_model=INCUMBENT,
        candidate_model=CANDIDATE,
    )
    db_session.add(run)
    db_session.commit()

    replayed: list = []

    async def fake_replay(messages, params, model, key):
        replayed.append(messages)
        return {
            "choices": [{"message": {"role": "assistant", "content": "ans"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 8, "completion_tokens": 4},
        }

    async def fake_judge(*a, **k):
        return "tie"

    asyncio.run(runner.run_eval(db_session, run, key="sk-test", replay_fn=fake_replay, judge_fn=fake_judge))
    # Only the two eligible samples were replayed through the candidate.
    assert len(replayed) == 2
