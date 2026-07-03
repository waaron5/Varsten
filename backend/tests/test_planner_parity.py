"""Planner selection + parity shadow (slice A4).

The planner now selects a primary action (enforce / shadow / observe) and the
proxy records, for every metered request, whether the optimization it actually
applied was authorized by the planner (parity). Killing the planner must change
nothing but the trace — the request still succeeds and is still metered.
"""

import json
import uuid

import httpx
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.engine.classification import classify_request
from app.engine.planner import select_action
from app.engine.types import (
    CandidateOptimization,
    CandidateStatus,
    OptimizationPlan,
    OptimizationRisk,
    QualityGateStatus,
    SelectedAction,
)
from app.models import RequestDecisionEvent
from app.proxy import http_client
from app.proxy import router as proxy_router
from app.proxy.evidence import DecisionDraft, add_planner_parity_trace
from app.proxy.request_context import RequestContext

CHAT = "gpt-4o-mini"


def _cand(lever: str, status: CandidateStatus) -> CandidateOptimization:
    return CandidateOptimization(
        lever=lever,
        status=status,
        quality_gate=QualityGateStatus.NOT_REQUIRED,
        risk=OptimizationRisk.LOW,
        reason_code=f"{lever}_reason",
    )


# --- select_action -------------------------------------------------------------


def test_select_enforces_highest_priority_eligible():
    candidates = (
        _cand("exact_cache", CandidateStatus.ELIGIBLE),
        _cand("model_routing", CandidateStatus.RECOMMENDABLE),
    )
    selected = select_action(candidates, optimize_enabled=True)
    assert selected.action == "exact_cache"
    assert selected.mode == "enforce"


def test_select_skips_rejected_to_next_priority():
    candidates = (
        _cand("exact_cache", CandidateStatus.REJECTED),
        _cand("model_routing", CandidateStatus.RECOMMENDABLE),
    )
    selected = select_action(candidates, optimize_enabled=True)
    assert selected.action == "model_routing"
    assert selected.mode == "enforce"


def test_select_falls_back_to_shadow():
    candidates = (
        _cand("exact_cache", CandidateStatus.REJECTED),
        _cand("model_routing", CandidateStatus.SHADOW_ONLY),
    )
    selected = select_action(candidates, optimize_enabled=True)
    assert selected.action == "model_routing"
    assert selected.mode == "shadow"


def test_select_observe_when_nothing_actionable():
    candidates = (
        _cand("exact_cache", CandidateStatus.REJECTED),
        _cand("model_routing", CandidateStatus.UNAVAILABLE),
    )
    selected = select_action(candidates, optimize_enabled=True)
    assert selected.action == "observe"
    assert selected.reason_code == "no_actionable_candidate"


def test_select_observe_when_optimization_disabled():
    candidates = (_cand("exact_cache", CandidateStatus.ELIGIBLE),)
    selected = select_action(candidates, optimize_enabled=False)
    assert selected.action == "observe"
    assert selected.reason_code == "optimization_disabled"


# --- parity --------------------------------------------------------------------


def _plan(candidates: tuple[CandidateOptimization, ...]) -> OptimizationPlan:
    classification = classify_request(
        {"messages": [{"role": "user", "content": "x"}]},
        RequestContext(task_type="classification.intent", task_confidence=0.9, risk_level="low"),
    )
    return OptimizationPlan(
        request_id="req_1",
        provider="openai",
        model=CHAT,
        classification=classification,
        candidates=candidates,
        selected=select_action(candidates, optimize_enabled=True),
    )


def _draft(plan: OptimizationPlan | None, *, bypassed: bool = False) -> DecisionDraft:
    draft = DecisionDraft(
        request_id="req_1",
        client_dialect="openai",
        provider_requested="openai",
        model_requested=CHAT,
        bypassed=bypassed,
    )
    draft.optimization_plan = plan
    return draft


def _parity_events(draft: DecisionDraft) -> list[dict]:
    return [e for e in draft.runtime_trace if e["stage"] == "planner_parity"]


def test_parity_match_for_authorized_applied_lever():
    draft = _draft(_plan((_cand("exact_cache", CandidateStatus.ELIGIBLE),)))
    add_planner_parity_trace(draft, cache_status="hit", arm=None, trim_applied=False, routed=False)
    events = _parity_events(draft)
    assert len(events) == 1
    assert events[0]["action"] == "match"
    assert events[0]["lever"] == "exact_cache"


def test_parity_mismatch_when_applied_lever_was_rejected():
    # Cache enforcement is in shadow, so the proxy can serve a hit the planner
    # rejected: exactly the drift parity is meant to catch.
    draft = _draft(_plan((_cand("exact_cache", CandidateStatus.REJECTED),)))
    add_planner_parity_trace(draft, cache_status="hit", arm=None, trim_applied=False, routed=False)
    events = _parity_events(draft)
    assert len(events) == 1
    assert events[0]["action"] == "mismatch"
    assert events[0]["reason_code"] == "applied_rejected"


def test_parity_match_for_passthrough():
    draft = _draft(_plan((_cand("exact_cache", CandidateStatus.ELIGIBLE),)))
    add_planner_parity_trace(draft, cache_status="miss", arm=None, trim_applied=False, routed=False)
    events = _parity_events(draft)
    assert len(events) == 1
    assert events[0]["action"] == "match"
    assert events[0]["reason_code"] == "passthrough"


def test_parity_skipped_when_bypassed_or_no_plan():
    draft = _draft(_plan((_cand("exact_cache", CandidateStatus.ELIGIBLE),)), bypassed=True)
    add_planner_parity_trace(draft, cache_status="hit", arm=None, trim_applied=False, routed=False)
    assert _parity_events(draft) == []

    draft2 = _draft(None)
    add_planner_parity_trace(draft2, cache_status="hit", arm=None, trim_applied=False, routed=False)
    assert _parity_events(draft2) == []


def test_selected_action_object():
    assert isinstance(select_action((), optimize_enabled=True), SelectedAction)


# --- fault injection: killing the planner changes nothing but the trace --------


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
async def test_request_succeeds_when_planner_raises(async_client, async_db_session, async_provision, monkeypatch):
    p = await async_provision()
    monkeypatch.setattr(settings, "proxy_openai_keys", {p["project_id"]: "sk-test"})
    _mock_openai(monkeypatch)

    def _boom(*args, **kwargs):
        raise RuntimeError("planner exploded")

    monkeypatch.setattr(proxy_router, "build_observe_only_plan", _boom)

    res = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {p['api_key']}"},
        json={"model": CHAT, "messages": [{"role": "user", "content": "hi"}]},
    )
    # Planner failure is fully absorbed: the request still succeeds and is metered.
    assert res.status_code == 200
    assert res.json()["choices"][0]["message"]["content"] == "Hello world"

    decision = await async_db_session.scalar(
        select(RequestDecisionEvent).where(RequestDecisionEvent.project_id == uuid.UUID(p["project_id"]))
    )
    assert decision is not None
    # No plan means no plan metadata and no parity trace — nothing but the trace changed.
    meta = decision.event_metadata or {}
    assert "optimization_plan" not in meta
    parity = [e for e in meta.get("runtime_trace", []) if e.get("stage") == "planner_parity"]
    assert parity == []
    assert json.dumps(meta) is not None  # metadata is serializable
