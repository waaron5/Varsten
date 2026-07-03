"""Prompt-cache orchestration detection (slice D1).

The proxy fingerprints each request's cacheable prefix (hash only, never text);
the prompt-cache recommendation then uses the route's *measured* prefix
stability: a stable prefix strengthens "enable caching" with evidence, an
unstable one flips it to "restructure the prompt", and no fingerprint data falls
back to the conservative default assumption.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models import ModelPrice, Project, Recommendation, RequestDecisionEvent, UsageEvent
from app.proxy import http_client
from app.proxy.prompt_prefix import stable_prefix_hash
from app.recommendations import _add_prompt_cache_recommendation
from app.savings import month_start

MODEL = "gpt-4o-mini"
FEATURE = "support_agent"


# --- fingerprint ----------------------------------------------------------------


def test_same_system_prompt_same_hash():
    body_a = {"messages": [{"role": "system", "content": "You are helpful."}, {"role": "user", "content": "a"}]}
    body_b = {"messages": [{"role": "system", "content": "You are helpful."}, {"role": "user", "content": "b"}]}
    assert stable_prefix_hash(body_a) == stable_prefix_hash(body_b)


def test_different_system_prompt_different_hash():
    body_a = {"messages": [{"role": "system", "content": "You are helpful. Now: 2026-07-03T10:00Z"}]}
    body_b = {"messages": [{"role": "system", "content": "You are helpful. Now: 2026-07-03T10:01Z"}]}
    assert stable_prefix_hash(body_a) != stable_prefix_hash(body_b)


def test_tools_are_part_of_the_prefix():
    base = {"messages": [{"role": "system", "content": "x"}]}
    with_tools = {**base, "tools": [{"type": "function", "function": {"name": "lookup"}}]}
    assert stable_prefix_hash(base) != stable_prefix_hash(with_tools)


def test_no_prefix_material_yields_none():
    assert stable_prefix_hash({"messages": [{"role": "user", "content": "hi"}]}) is None
    assert stable_prefix_hash({}) is None
    assert stable_prefix_hash(None) is None


def test_anthropic_and_gemini_shapes():
    anthropic = {"system": "You are helpful.", "messages": [{"role": "user", "content": "hi"}]}
    gemini = {"systemInstruction": {"parts": [{"text": "You are helpful."}]}, "contents": []}
    assert stable_prefix_hash(anthropic) is not None
    assert stable_prefix_hash(gemini) is not None


def test_hash_is_content_free():
    secret = "SECRET-CUSTOMER-DATA-42"
    fingerprint = stable_prefix_hash({"messages": [{"role": "system", "content": secret}]})
    assert fingerprint is not None
    assert secret not in fingerprint
    assert len(fingerprint) == 16


# --- persisted end-to-end -------------------------------------------------------


def _mock_openai(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/embeddings"):
            return httpx.Response(200, json={"data": [{"embedding": [0.1] * 1536, "index": 0}], "usage": {}})
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-mock",
                "object": "chat.completion",
                "model": MODEL,
                "choices": [
                    {"index": 0, "message": {"role": "assistant", "content": "Hello"}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
            },
        )

    monkeypatch.setattr(http_client, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))


@pytest.mark.anyio
async def test_decision_persists_prefix_hash(async_client, async_db_session, async_provision, monkeypatch):
    p = await async_provision()
    monkeypatch.setattr(settings, "proxy_openai_keys", {p["project_id"]: "sk-test"})
    _mock_openai(monkeypatch)

    body = {
        "model": MODEL,
        "messages": [{"role": "system", "content": "You are helpful."}, {"role": "user", "content": "hi"}],
    }
    res = await async_client.post(
        "/v1/chat/completions", headers={"Authorization": f"Bearer {p['api_key']}"}, json=body
    )
    assert res.status_code == 200

    decision = await async_db_session.scalar(
        select(RequestDecisionEvent).where(RequestDecisionEvent.project_id == uuid.UUID(p["project_id"]))
    )
    assert decision is not None
    assert decision.prefix_hash == stable_prefix_hash(body)
    # Hash, not content.
    assert "helpful" not in (decision.prefix_hash or "")
    assert "helpful" not in json.dumps(decision.event_metadata or {})


# --- detection ------------------------------------------------------------------


def _project(db_session, provision) -> Project:
    p = provision()
    return db_session.get(Project, uuid.UUID(p["project_id"]))


def _seed_price(db_session):
    db_session.add(
        ModelPrice(
            model_key=MODEL,
            provider="openai",
            currency="USD",
            input_cost_per_token=Decimal("0.00000015"),
            cache_read_input_token_cost=Decimal("0.000000075"),
            output_cost_per_token=Decimal("0.0000006"),
            source="catalog",
            effective_at=datetime.now(UTC) - timedelta(days=30),
        )
    )
    db_session.flush()


def _seed_usage(db_session, project, *, count=30, input_tokens=3000, cached=0):
    for _ in range(count):
        db_session.add(
            UsageEvent(
                project_id=project.id,
                organization_id=project.organization_id,
                provider="openai",
                model=MODEL,
                operation="chat_completion",
                request_type="chat_completion",
                feature=FEATURE,
                environment="production",
                input_tokens=input_tokens,
                cached_input_tokens=cached,
                output_tokens=100,
                total_tokens=input_tokens + 100,
                cost_usd=Decimal("0.001"),
                cost_source="catalog",
                pricing_status="priced",
                currency="USD",
                status="success",
                success=True,
                occurred_at=datetime.now(UTC),
            )
        )
    db_session.flush()


def _seed_decisions(db_session, project, hashes: list[str]):
    for i, prefix_hash in enumerate(hashes):
        db_session.add(
            RequestDecisionEvent(
                organization_id=project.organization_id,
                project_id=project.id,
                request_id=f"req_prefix_{i}",
                provider_requested="openai",
                model_requested=MODEL,
                decision_type="passthrough",
                route_key=FEATURE,  # canonical_route_key(feature=FEATURE)
                prefix_hash=prefix_hash,
            )
        )
    db_session.flush()


def _recs(db_session, project) -> dict[str, Recommendation]:
    rows = db_session.scalars(select(Recommendation).where(Recommendation.project_id == project.id)).all()
    return {r.type: r for r in rows}


def test_stable_prefix_uses_measured_share(db_session, provision):
    project = _project(db_session, provision)
    _seed_price(db_session)
    _seed_usage(db_session, project)
    # 24 of 25 fingerprints identical: measured stable.
    _seed_decisions(db_session, project, ["aaaa"] * 24 + ["bbbb"])
    db_session.commit()

    _add_prompt_cache_recommendation(db_session, project, month_start(datetime.now(UTC)), datetime.now(UTC))
    db_session.flush()

    recs = _recs(db_session, project)
    assert "prompt_cache" in recs
    rec = recs["prompt_cache"]
    assert rec.confidence == "high"
    assert "measured" in rec.description
    assert "96%" in rec.description


def test_unstable_prefix_recommends_restructure(db_session, provision):
    project = _project(db_session, provision)
    _seed_price(db_session)
    _seed_usage(db_session, project)
    # Every request a different fingerprint: the prefix churns.
    _seed_decisions(db_session, project, [f"hash{i}" for i in range(25)])
    db_session.commit()

    _add_prompt_cache_recommendation(db_session, project, month_start(datetime.now(UTC)), datetime.now(UTC))
    db_session.flush()

    recs = _recs(db_session, project)
    assert "prompt_prefix_restructure" in recs
    assert "prompt_cache" not in recs
    assert "Stabilize the prompt prefix" in recs["prompt_prefix_restructure"].title


def test_no_fingerprints_falls_back_to_default(db_session, provision):
    project = _project(db_session, provision)
    _seed_price(db_session)
    _seed_usage(db_session, project)
    db_session.commit()

    _add_prompt_cache_recommendation(db_session, project, month_start(datetime.now(UTC)), datetime.now(UTC))
    db_session.flush()

    recs = _recs(db_session, project)
    assert "prompt_cache" in recs
    rec = recs["prompt_cache"]
    # The flat assumption is honest about being an assumption.
    assert rec.confidence == "medium"
    assert "conservatively" in rec.description


def test_mostly_cached_route_not_recommended(db_session, provision):
    project = _project(db_session, provision)
    _seed_price(db_session)
    # 80% provider cache hit rate already: nothing to recommend.
    _seed_usage(db_session, project, input_tokens=3000, cached=2400)
    db_session.commit()

    _add_prompt_cache_recommendation(db_session, project, month_start(datetime.now(UTC)), datetime.now(UTC))
    db_session.flush()

    assert _recs(db_session, project) == {}
