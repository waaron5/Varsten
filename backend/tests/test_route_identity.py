"""Canonical route identity (slice A5).

One route key that learning segments, eval runs, and guardrails converge on,
derived from the most specific business handle the caller supplied and persisted
on every decision so evidence attaches to one route object.
"""

import uuid

import httpx
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.engine.outcomes import score_optimization_outcomes
from app.engine.route_identity import (
    DEFAULT_ROUTE,
    canonical_route_key,
    model_scoped_route_key,
    route_key_from_context,
    route_key_from_recommendation,
)
from app.models import Recommendation, RequestDecisionEvent
from app.proxy import http_client
from app.proxy.request_context import RequestContext

CHAT = "gpt-4o-mini"


# --- canonical key -------------------------------------------------------------


def test_priority_feature_over_everything():
    assert (
        canonical_route_key(feature="Support Reply", workflow="wf", request_type="chat", task_type="t")
        == "support_reply"
    )


def test_priority_falls_through_to_task_type():
    assert canonical_route_key(task_type="Classification.Intent") == "classification.intent"
    assert canonical_route_key(workflow="Billing Support") == "billing_support"
    assert canonical_route_key(request_type="chat_completion") == "chat_completion"


def test_default_when_no_context():
    assert canonical_route_key() == DEFAULT_ROUTE
    assert canonical_route_key(feature="   ") == DEFAULT_ROUTE


def test_normalization_is_stable():
    assert canonical_route_key(feature="  Support   Reply  ") == "support_reply"
    assert canonical_route_key(feature="SUPPORT_REPLY") == canonical_route_key(feature="support_reply")


def test_length_cap():
    key = canonical_route_key(feature="x" * 500)
    assert len(key) == 128


def test_from_context_and_model_scope():
    ctx = RequestContext(feature="chat_agent", task_type="agent.reply")
    assert route_key_from_context(ctx) == "chat_agent"
    assert route_key_from_context(None, request_type="chat") == "chat"
    assert model_scoped_route_key("chat_agent", CHAT) == f"chat_agent::{CHAT}"
    assert model_scoped_route_key("chat_agent", None) == "chat_agent"


def test_from_recommendation_uses_route_target_not_model():
    route_rec = Recommendation(
        organization_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        dedupe_key="route",
        type="model_downshift",
        lever="model_downshift",
        target_type="route",
        target_key="Support Reply",
        title="x",
        description="x",
        risk_level="medium",
        confidence="medium",
        related_model="gpt-4o",
    )
    model_rec = Recommendation(
        organization_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        dedupe_key="model",
        type="model_downshift",
        lever="model_downshift",
        target_type="model",
        target_key="gpt-4o",
        title="x",
        description="x",
        risk_level="medium",
        confidence="medium",
        related_model="gpt-4o",
    )

    assert route_key_from_recommendation(route_rec) == "support_reply"
    assert route_key_from_recommendation(model_rec) == DEFAULT_ROUTE


# --- learning segments carry the route key -------------------------------------


def _decision(idx: int, *, route_key=None, feature=None, task_type="classification.intent") -> dict:
    return {
        "id": f"d{idx}",
        "route_key": route_key,
        "feature": feature,
        "workflow": None,
        "request_type": None,
        "task_type": task_type,
        "provider_requested": "openai",
        "model_requested": "gpt-4o",
        "provider_chosen": "openai",
        "model_chosen": "gpt-4o-mini",
        "lever": "model_downshift",
        "cache_status": "miss",
        "optimization_applied": True,
        "risk_level": "low",
        "realized_savings_usd": "0.01",
        "pricing_status": "priced",
        "quality_ok": True,
    }


def test_segment_uses_persisted_route_key():
    rows = [_decision(i, route_key="support_reply") for i in range(6)]
    candidates = score_optimization_outcomes(rows, [])
    assert candidates[0]["segment"]["route_key"] == "support_reply"


def test_segment_derives_route_key_when_missing():
    # Older rows without the column fall back to feature/task_type.
    rows = [_decision(i, route_key=None, feature="Billing Support") for i in range(6)]
    candidates = score_optimization_outcomes(rows, [])
    assert candidates[0]["segment"]["route_key"] == "billing_support"


# --- persisted end-to-end ------------------------------------------------------


def _mock_openai(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/embeddings"):
            return httpx.Response(200, json={"data": [{"embedding": [0.1] * 1536, "index": 0}], "usage": {}})
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-mock",
                "object": "chat.completion",
                "model": CHAT,
                "choices": [
                    {"index": 0, "message": {"role": "assistant", "content": "Hello world"}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
            },
        )

    monkeypatch.setattr(http_client, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))


@pytest.mark.anyio
async def test_decision_persists_route_key_from_feature(async_client, async_db_session, async_provision, monkeypatch):
    p = await async_provision()
    monkeypatch.setattr(settings, "proxy_openai_keys", {p["project_id"]: "sk-test"})
    _mock_openai(monkeypatch)

    res = await async_client.post(
        "/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {p['api_key']}",
            "X-Varsten-Feature": "Support Reply",
        },
        json={"model": CHAT, "messages": [{"role": "user", "content": "hi"}]},
    )
    assert res.status_code == 200

    decision = await async_db_session.scalar(
        select(RequestDecisionEvent).where(RequestDecisionEvent.project_id == uuid.UUID(p["project_id"]))
    )
    assert decision is not None
    assert decision.route_key == "support_reply"


@pytest.mark.anyio
async def test_decision_route_key_defaults_without_context(
    async_client, async_db_session, async_provision, monkeypatch
):
    p = await async_provision()
    monkeypatch.setattr(settings, "proxy_openai_keys", {p["project_id"]: "sk-test"})
    _mock_openai(monkeypatch)

    res = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {p['api_key']}"},
        json={"model": CHAT, "messages": [{"role": "user", "content": "hi"}]},
    )
    assert res.status_code == 200

    decision = await async_db_session.scalar(
        select(RequestDecisionEvent).where(RequestDecisionEvent.project_id == uuid.UUID(p["project_id"]))
    )
    # request_type defaults to chat_completion, so the route key is that, not None.
    assert decision.route_key == "chat_completion"
