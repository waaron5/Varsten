"""Moat foundation: capture-complete request evidence.

Covers the request-context header convention, the business/task context landing
on usage_events, and a RequestDecisionEvent being written for every metered proxy
path (passthrough, cache hit, routed treatment, holdback control, route-ineligible)
- all best-effort, tenant-isolated, and never able to fail the client request.

OpenAI is mocked via an httpx MockTransport so no real key or network is needed.
"""

import json
import uuid
from decimal import Decimal
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.models import ProxyPolicy, RequestDecisionEvent, UsageEvent
from app.proxy import circuit, evidence, http_client
from app.proxy.request_context import parse_request_context

CHAT = "gpt-4o-mini"


@pytest.fixture(autouse=True)
def reset_circuit():
    circuit.reset_all()
    yield
    circuit.reset_all()


@pytest.fixture
def mock_openai(monkeypatch):
    """Mock upstream that echoes the requested model and records forwarded headers
    so tests can assert Varsten control headers never leak upstream."""
    seen: dict[str, Any] = {"completions": 0, "headers": []}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["completions"] += 1
        seen["headers"].append({k.lower(): v for k, v in request.headers.items()})
        payload = json.loads(request.content)
        model = payload.get("model", CHAT)
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-mock",
                "object": "chat.completion",
                "model": model,
                "choices": [
                    {"index": 0, "message": {"role": "assistant", "content": "Hello world"}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
            },
        )

    monkeypatch.setattr(http_client, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return seen


def _configure_key(monkeypatch, project_id: str):
    monkeypatch.setattr(settings, "proxy_openai_keys", {project_id: "sk-test"})


def _body(**extra):
    return {"model": CHAT, "messages": [{"role": "user", "content": "Hi"}], **extra}


async def _decisions(db, project_id) -> list[RequestDecisionEvent]:
    rows = await db.scalars(
        select(RequestDecisionEvent).where(RequestDecisionEvent.project_id == uuid.UUID(str(project_id)))
    )
    return list(rows)


# --- unit: header parsing ----------------------------------------------------


def test_parse_metadata_json_happy_path():
    ctx = parse_request_context(
        {
            "X-Varsten-Metadata": json.dumps(
                {
                    "feature": "support_reply",
                    "workflow": "billing_support",
                    "customer_id": "cust_123",
                    "team": "support",
                    "task_type": "support_reply.billing",
                    "task_confidence": 0.9,
                    "risk_level": "medium",
                    "quality_threshold": "customer_safe",
                    "custom_dim": "abc",
                }
            )
        }
    )
    assert ctx.feature == "support_reply"
    assert ctx.workflow == "billing_support"
    assert ctx.customer_id == "cust_123"
    assert ctx.task_type == "support_reply.billing"
    assert ctx.task_confidence == 0.9
    assert ctx.risk_level == "medium"
    assert ctx.extra == {"custom_dim": "abc"}
    assert not ctx.is_empty


def test_individual_headers_override_json():
    ctx = parse_request_context(
        {
            "X-Varsten-Metadata": json.dumps({"feature": "from_json"}),
            "X-Varsten-Feature": "from_header",
            "X-Varsten-Task-Type": "extraction",
        }
    )
    assert ctx.feature == "from_header"
    assert ctx.task_type == "extraction"


def test_malformed_metadata_is_ignored():
    ctx = parse_request_context({"X-Varsten-Metadata": "{not valid json"})
    assert ctx.is_empty


def test_oversized_metadata_is_ignored(monkeypatch):
    monkeypatch.setattr(settings, "proxy_metadata_max_bytes", 64)
    ctx = parse_request_context({"X-Varsten-Metadata": json.dumps({"feature": "x" * 500})})
    assert ctx.is_empty


def test_confidence_is_clamped_and_junk_dropped():
    assert parse_request_context({"X-Varsten-Task-Confidence": "5"}).task_confidence == 1.0
    assert parse_request_context({"X-Varsten-Task-Confidence": "-2"}).task_confidence == 0.0
    assert parse_request_context({"X-Varsten-Task-Confidence": "abc"}).task_confidence is None


# --- integration: context lands on usage_events + evidence -------------------


@pytest.mark.anyio
async def test_context_populates_usage_event_and_evidence(
    async_client, async_provision, async_db_session, monkeypatch, mock_openai
):
    p = await async_provision()
    _configure_key(monkeypatch, p["project_id"])

    meta = {
        "feature": "support_reply",
        "workflow": "billing_support",
        "customer_id": "cust_123",
        "external_user_id": "user_456",
        "team": "support",
        "department": "customer_success",
        "environment": "staging",
        "task_type": "support_reply.billing",
        "task_confidence": 1.0,
        "risk_level": "medium",
        "quality_threshold": "customer_safe",
    }
    resp = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {p['api_key']}", "X-Varsten-Metadata": json.dumps(meta)},
        json=_body(),
    )
    assert resp.status_code == 200
    assert resp.headers.get("X-Varsten-Request-Id")

    ue = (
        await async_db_session.scalars(select(UsageEvent).where(UsageEvent.project_id == uuid.UUID(p["project_id"])))
    ).one()
    assert ue.feature == "support_reply"
    assert ue.workflow == "billing_support"
    assert ue.customer_id == "cust_123"
    assert ue.external_user_id == "user_456"
    assert ue.team == "support"
    assert ue.department == "customer_success"
    assert ue.environment == "staging"
    assert ue.event_metadata.get("task_type") == "support_reply.billing"
    assert ue.event_metadata.get("risk_level") == "medium"
    assert ue.event_metadata.get("quality_threshold") == "customer_safe"

    decisions = await _decisions(async_db_session, p["project_id"])
    assert len(decisions) == 1
    d = decisions[0]
    assert d.decision_type == "passthrough"
    assert d.feature == "support_reply"
    assert d.task_type == "support_reply.billing"
    assert d.risk_level == "medium"
    assert d.model_requested == CHAT
    assert d.model_chosen == CHAT
    assert d.usage_event_id == ue.id
    assert d.request_id == resp.headers["X-Varsten-Request-Id"]


@pytest.mark.anyio
async def test_no_metadata_preserves_defaults(
    async_client, async_provision, async_db_session, monkeypatch, mock_openai
):
    p = await async_provision()
    _configure_key(monkeypatch, p["project_id"])
    resp = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {p['api_key']}"},
        json=_body(),
    )
    assert resp.status_code == 200
    ue = (
        await async_db_session.scalars(select(UsageEvent).where(UsageEvent.project_id == uuid.UUID(p["project_id"])))
    ).one()
    assert ue.feature == "proxy"
    assert ue.environment == "production"
    assert ue.workflow is None


@pytest.mark.anyio
async def test_malformed_metadata_does_not_fail_request(async_client, async_provision, monkeypatch, mock_openai):
    p = await async_provision()
    _configure_key(monkeypatch, p["project_id"])
    resp = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {p['api_key']}", "X-Varsten-Metadata": "{broken"},
        json=_body(),
    )
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_varsten_headers_not_forwarded_upstream(async_client, async_provision, monkeypatch, mock_openai):
    p = await async_provision()
    _configure_key(monkeypatch, p["project_id"])
    await async_client.post(
        "/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {p['api_key']}",
            "X-Varsten-Metadata": json.dumps({"feature": "x"}),
            "X-Varsten-Feature": "x",
        },
        json=_body(),
    )
    assert mock_openai["completions"] == 1
    forwarded = mock_openai["headers"][0]
    assert not any(k.startswith("x-varsten-") for k in forwarded)


# --- integration: evidence per optimization path ------------------------------


def _add_routing_policy(db, p, *, holdback: str, candidate="gpt-3.5-turbo"):
    db.add(
        ProxyPolicy(
            organization_id=uuid.UUID(p["org_id"]),
            project_id=uuid.UUID(p["project_id"]),
            lever="cheaper_model",
            target_type="model",
            target_key=CHAT,
            enabled=True,
            holdback_percent=Decimal(holdback),
            params={"candidate_model": candidate},
        )
    )


@pytest.mark.anyio
async def test_evidence_cache_hit(async_client, async_provision, async_db_session, monkeypatch, mock_openai):
    p = await async_provision()
    _configure_key(monkeypatch, p["project_id"])
    headers = {"Authorization": f"Bearer {p['api_key']}"}
    # First call: miss + store. Second identical call: exact-hash hit.
    await async_client.post("/v1/chat/completions", headers=headers, json=_body())
    await async_client.post("/v1/chat/completions", headers=headers, json=_body())

    decisions = await _decisions(async_db_session, p["project_id"])
    statuses = sorted(d.decision_type for d in decisions)
    assert statuses == ["cache", "passthrough"]
    hit = next(d for d in decisions if d.decision_type == "cache")
    assert hit.cache_status == "hit"
    assert hit.optimization_applied is True
    assert hit.realized_actual_cost_usd == Decimal("0") or hit.realized_actual_cost_usd is None


@pytest.mark.anyio
async def test_evidence_routed_treatment(async_client, async_provision, async_db_session, monkeypatch, mock_openai):
    p = await async_provision()
    _configure_key(monkeypatch, p["project_id"])
    _add_routing_policy(async_db_session, p, holdback="0.0")  # always treatment
    await async_db_session.flush()
    monkeypatch.setattr("app.proxy.routing.random.random", lambda: 0.99)

    resp = await async_client.post(
        "/v1/chat/completions", headers={"Authorization": f"Bearer {p['api_key']}"}, json=_body()
    )
    assert resp.status_code == 200
    assert resp.headers.get("X-Varsten-Arm") == "treatment"

    decisions = await _decisions(async_db_session, p["project_id"])
    d = decisions[0]
    assert d.arm == "treatment"
    assert d.decision_type == "experiment_treatment"
    assert d.route_eligible is True
    assert d.optimization_applied is True
    assert d.lever == "cheaper_model"
    assert d.model_counterfactual == CHAT


@pytest.mark.anyio
async def test_evidence_holdback_control(async_client, async_provision, async_db_session, monkeypatch, mock_openai):
    p = await async_provision()
    _configure_key(monkeypatch, p["project_id"])
    _add_routing_policy(async_db_session, p, holdback="1.0")  # always control
    await async_db_session.flush()
    monkeypatch.setattr("app.proxy.routing.random.random", lambda: 0.0)

    resp = await async_client.post(
        "/v1/chat/completions", headers={"Authorization": f"Bearer {p['api_key']}"}, json=_body()
    )
    assert resp.status_code == 200
    assert resp.headers.get("X-Varsten-Arm") == "control"

    d = (await _decisions(async_db_session, p["project_id"]))[0]
    assert d.arm == "control"
    assert d.decision_type == "experiment_control"
    assert d.route_eligible is True
    assert d.optimization_applied is False


@pytest.mark.anyio
async def test_evidence_route_ineligible(async_client, async_provision, async_db_session, monkeypatch, mock_openai):
    p = await async_provision()
    _configure_key(monkeypatch, p["project_id"])
    # Candidate on a different provider + a server-side tool -> cross-provider
    # translation is ineligible, so the incumbent runs and evidence records why.
    async_db_session.add(
        ProxyPolicy(
            organization_id=uuid.UUID(p["org_id"]),
            project_id=uuid.UUID(p["project_id"]),
            lever="smart_routing",
            target_type="model",
            target_key=CHAT,
            enabled=True,
            holdback_percent=Decimal("0.0"),
            params={"candidate_model": "claude-3-5-haiku", "candidate_provider": "anthropic"},
        )
    )
    await async_db_session.flush()

    resp = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {p['api_key']}"},
        json=_body(tools=[{"type": "web_search"}]),
    )
    assert resp.status_code == 200
    d = (await _decisions(async_db_session, p["project_id"]))[0]
    assert d.route_eligible is False
    assert d.route_ineligible_reason == "server_side_tool"
    # The incumbent (openai) actually ran.
    assert d.model_chosen == CHAT


@pytest.mark.anyio
async def test_evidence_bypass(async_client, async_provision, async_db_session, monkeypatch, mock_openai):
    p = await async_provision()
    _configure_key(monkeypatch, p["project_id"])
    monkeypatch.setattr(settings, "proxy_kill_switch", True)
    resp = await async_client.post(
        "/v1/chat/completions", headers={"Authorization": f"Bearer {p['api_key']}"}, json=_body()
    )
    assert resp.status_code == 200
    d = (await _decisions(async_db_session, p["project_id"]))[0]
    assert d.decision_type == "bypass"
    assert d.bypassed is True
    assert d.bypass_reason == "kill_switch"


@pytest.mark.anyio
async def test_evidence_tenant_isolation(async_client, async_provision, async_db_session, monkeypatch, mock_openai):
    a = await async_provision(project_name="a")
    b = await async_provision(project_name="b")
    _configure_key(monkeypatch, a["project_id"])
    await async_client.post("/v1/chat/completions", headers={"Authorization": f"Bearer {a['api_key']}"}, json=_body())
    assert len(await _decisions(async_db_session, a["project_id"])) == 1
    assert len(await _decisions(async_db_session, b["project_id"])) == 0


@pytest.mark.anyio
async def test_evidence_failure_does_not_fail_request(
    async_client, async_provision, async_db_session, monkeypatch, mock_openai
):
    p = await async_provision()
    _configure_key(monkeypatch, p["project_id"])

    async def boom(*args, **kwargs):
        raise RuntimeError("evidence is down")

    monkeypatch.setattr(evidence, "record_request_decision", boom)
    # router imported the symbol directly; patch there too.
    monkeypatch.setattr("app.proxy.router.record_request_decision", boom)

    resp = await async_client.post(
        "/v1/chat/completions", headers={"Authorization": f"Bearer {p['api_key']}"}, json=_body()
    )
    assert resp.status_code == 200
    # Ledger still wrote even though evidence blew up.
    count = await async_db_session.scalar(
        select(func.count()).select_from(UsageEvent).where(UsageEvent.project_id == uuid.UUID(p["project_id"]))
    )
    assert count == 1
