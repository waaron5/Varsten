"""Trace/session model + agent-loop detection (slice D3).

A client trace id groups one agent workflow's calls; identical whole-request
fingerprints inside a trace are redundant calls. Detection measures the waste
from the ledger and surfaces a recommendation — Varsten never edits a workflow.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.engine.agent_loops import detect_agent_loops
from app.models import Project, Recommendation, RequestDecisionEvent
from app.proxy import http_client
from app.proxy.prompt_prefix import full_request_fingerprint
from app.proxy.request_context import parse_request_context
from app.recommendations import _add_agent_loop_recommendation
from app.savings import month_start

MODEL = "gpt-4o-mini"
ROUTE = "research_agent"


# --- context parsing -------------------------------------------------------------


def test_trace_id_parsed_from_header():
    ctx = parse_request_context({"X-Varsten-Trace-Id": "trace-abc-123"})
    assert ctx.trace_id == "trace-abc-123"


def test_trace_id_parsed_from_metadata_json():
    ctx = parse_request_context({"X-Varsten-Metadata": '{"trace_id": "trace-json-1", "feature": "agent"}'})
    assert ctx.trace_id == "trace-json-1"
    assert ctx.feature == "agent"


def test_fingerprint_identical_for_identical_bodies():
    body = {"model": MODEL, "messages": [{"role": "user", "content": "look up X"}]}
    assert full_request_fingerprint(body) == full_request_fingerprint(dict(body))
    assert full_request_fingerprint(body) != full_request_fingerprint({**body, "temperature": 0.5})
    assert full_request_fingerprint({}) is None


# --- persisted end-to-end ---------------------------------------------------------


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
async def test_decision_persists_trace_and_fingerprint(async_client, async_db_session, async_provision, monkeypatch):
    p = await async_provision()
    monkeypatch.setattr(settings, "proxy_openai_keys", {p["project_id"]: "sk-test"})
    _mock_openai(monkeypatch)

    body = {"model": MODEL, "messages": [{"role": "user", "content": "hi"}]}
    res = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {p['api_key']}", "X-Varsten-Trace-Id": "trace-e2e-1"},
        json=body,
    )
    assert res.status_code == 200

    decision = await async_db_session.scalar(
        select(RequestDecisionEvent).where(RequestDecisionEvent.project_id == uuid.UUID(p["project_id"]))
    )
    assert decision is not None
    assert decision.trace_id == "trace-e2e-1"
    assert decision.request_fingerprint == full_request_fingerprint(body)


# --- detection --------------------------------------------------------------------


def _project(db_session, provision) -> Project:
    p = provision()
    return db_session.get(Project, uuid.UUID(p["project_id"]))


def _seed_trace(db_session, project, trace_id: str, fingerprints: list[str], *, cost="0.01"):
    for i, fp in enumerate(fingerprints):
        db_session.add(
            RequestDecisionEvent(
                organization_id=project.organization_id,
                project_id=project.id,
                request_id=f"req_{trace_id}_{i}",
                provider_requested="openai",
                model_requested=MODEL,
                decision_type="passthrough",
                route_key=ROUTE,
                trace_id=trace_id,
                request_fingerprint=fp,
                realized_actual_cost_usd=Decimal(cost),
            )
        )
    db_session.flush()


def test_detects_repeated_calls_across_traces(db_session, provision):
    project = _project(db_session, provision)
    # Three traces, each asking "fp1" twice (one redundant repeat per trace).
    for t in range(3):
        _seed_trace(db_session, project, f"trace-{t}", ["fp1", "fp1", "fp_other"])
    db_session.commit()

    findings = detect_agent_loops(db_session, project, month_start(datetime.now(UTC)))
    assert len(findings) == 1
    top = findings[0]
    assert top.route_key == ROUTE
    assert top.affected_traces == 3
    assert top.redundant_calls == 3  # one repeat per trace
    # Each looping group cost 0.02 over 2 calls; the repeat's half is waste.
    assert top.wasted_cost_usd == Decimal("0.03")


def test_distinct_calls_are_not_loops(db_session, provision):
    project = _project(db_session, provision)
    for t in range(3):
        _seed_trace(db_session, project, f"trace-{t}", ["a", "b", "c"])
    db_session.commit()

    assert detect_agent_loops(db_session, project, month_start(datetime.now(UTC))) == []


def test_too_few_affected_traces_not_surfaced(db_session, provision):
    project = _project(db_session, provision)
    # Only two looping traces: below the pattern threshold.
    for t in range(2):
        _seed_trace(db_session, project, f"trace-{t}", ["fp1", "fp1"])
    db_session.commit()

    assert detect_agent_loops(db_session, project, month_start(datetime.now(UTC))) == []


def test_recommendation_emitted_with_measured_evidence(db_session, provision):
    project = _project(db_session, provision)
    for t in range(4):
        _seed_trace(db_session, project, f"trace-{t}", ["fp1", "fp1"])
    db_session.commit()

    _add_agent_loop_recommendation(db_session, project, month_start(datetime.now(UTC)), datetime.now(UTC))
    db_session.flush()

    rec = db_session.scalar(
        select(Recommendation).where(Recommendation.project_id == project.id, Recommendation.type == "agent_loop")
    )
    assert rec is not None
    assert rec.lever is None  # a workflow fix, not an engine lever
    assert rec.status == "open"
    assert rec.target_key == ROUTE
    assert "4 traces" in rec.description
    assert rec.estimated_monthly_savings_usd > 0
