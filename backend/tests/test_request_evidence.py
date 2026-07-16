"""Moat foundation: capture-complete request evidence.

Covers the request-context header convention, the business/task context landing
on usage_events, and a RequestDecisionEvent being written for every metered proxy
path (passthrough, cache hit, routed treatment, holdback control, route-ineligible)
- all best-effort, tenant-isolated, and never able to fail the client request.

OpenAI is mocked via an httpx MockTransport so no real key or network is needed.
"""

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.models import EngineOutcomePrior, ProxyPolicy, RequestDecisionEvent, UsageEvent
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


def _low_risk_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "X-Varsten-Metadata": json.dumps(
            {"task_type": "classification.intent", "task_confidence": 0.95, "risk_level": "low"}
        ),
    }


def _money(value: str | None) -> Decimal | None:
    return Decimal(value) if value is not None else None


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
    plan = d.event_metadata["optimization_plan"]
    assert plan["planner_version"] == "planner_v1_observe_only"
    # No lever is enforceable for this medium-risk request (cache needs an explicit
    # policy, no routing/trim policy present), so the planner selects observe.
    assert plan["selected"] == {"action": "observe", "mode": "observe_only", "reason_code": "no_actionable_candidate"}
    assert plan["classification"]["task_type"] == "support_reply.billing"
    assert plan["classification"]["risk_level"] == "medium"
    assert plan["classification"]["prompt_chars"] == len("Hi")
    assert "Hi" not in json.dumps(plan)
    trace = d.event_metadata["runtime_trace"]
    assert {"cache_lookup", "routing", "trim", "cache_store_decision"} <= {event["stage"] for event in trace}
    assert any(event["lever"] == "exact_cache" and event["action"] == "miss" for event in trace)
    assert any(
        event["lever"] == "model_routing" and event["reason_code"] == "routing_no_applicable_policy" for event in trace
    )
    assert "Hi" not in json.dumps(trace)
    proof = d.event_metadata["savings_proof"]
    assert proof["method"] == "none"
    assert proof["confidence"] == "not_applicable"
    assert proof["actual_cost_usd"] is not None
    assert proof["gross_savings_usd"] is None
    assert proof["optimization_overhead_cost_usd"] is None
    assert proof["net_savings_usd"] is None
    assert proof["quality_status"] == "not_measured"
    assert "optimization_overhead_not_measured" in proof["reason_codes"]


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
    # feature is a pure business dimension now: with no client metadata it stays
    # NULL. Proxy traffic is identified by the source discriminator, not by
    # overloading feature with the literal "proxy".
    assert ue.feature is None
    assert ue.source == "proxy"
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
            lever="model_downshift",
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
    hit_resp = await async_client.post("/v1/chat/completions", headers=headers, json=_body())

    decisions = await _decisions(async_db_session, p["project_id"])
    statuses = sorted(d.decision_type for d in decisions)
    assert statuses == ["cache", "passthrough"]
    hit = next(d for d in decisions if d.decision_type == "cache")
    assert hit_resp.headers.get("X-Varsten-Request-Id") == hit.request_id
    assert hit.cache_status == "hit"
    assert hit.optimization_applied is True
    assert hit.realized_actual_cost_usd == Decimal("0") or hit.realized_actual_cost_usd is None
    plan = hit.event_metadata["optimization_plan"]
    assert plan["selected"]["action"] == "observe"
    exact_cache = next(c for c in plan["candidates"] if c["lever"] == "exact_cache")
    assert exact_cache["status"] == "rejected"
    assert exact_cache["reason_detail"]["cache_gate"] == {
        "mode": "shadow",
        "decision": "reject",
        "enforced": False,
        "reason_code": "cache_gate_shadow_reject",
        "blockers": ["risky_or_unknown"],
    }
    trace = hit.event_metadata["runtime_trace"]
    assert any(event["lever"] == "exact_cache" and event["action"] == "hit" for event in trace)
    proof = hit.event_metadata["savings_proof"]
    assert proof["method"] == "cache_avoidance"
    assert _money(proof["actual_cost_usd"]) == hit.realized_actual_cost_usd
    assert _money(proof["actual_cost_usd"]) == Decimal("0")
    assert _money(proof["baseline_cost_usd"]) == hit.realized_naive_cost_usd
    assert _money(proof["gross_savings_usd"]) == hit.realized_savings_usd
    assert proof["optimization_overhead_cost_usd"] is None
    assert proof["net_savings_usd"] is None
    assert proof["confidence"] in {"measured_priced", "measured_pricing_uncertain", "unmeasured"}
    assert proof["quality_status"] == "not_measured"
    assert proof["pricing_status"] == hit.pricing_status
    assert proof["cost_source"] == hit.cost_source
    assert "optimization_overhead_not_measured" in proof["reason_codes"]


@pytest.mark.anyio
async def test_evidence_routed_treatment(async_client, async_provision, async_db_session, monkeypatch, mock_openai):
    p = await async_provision()
    _configure_key(monkeypatch, p["project_id"])
    _add_routing_policy(async_db_session, p, holdback="0.0")  # always treatment
    await async_db_session.flush()
    monkeypatch.setattr("app.proxy.routing.random.random", lambda: 0.99)

    resp = await async_client.post("/v1/chat/completions", headers=_low_risk_headers(p["api_key"]), json=_body())
    assert resp.status_code == 200
    assert resp.headers.get("X-Varsten-Arm") == "treatment"

    decisions = await _decisions(async_db_session, p["project_id"])
    d = decisions[0]
    assert d.arm == "treatment"
    assert d.decision_type == "experiment_treatment"
    assert d.route_eligible is True
    assert d.optimization_applied is True
    assert d.lever == "model_downshift"
    assert d.model_counterfactual == CHAT
    route_candidate = next(
        c for c in d.event_metadata["optimization_plan"]["candidates"] if c["lever"] == "model_routing"
    )
    assert route_candidate["policy_id"] == str(d.policy_id)
    trace = d.event_metadata["runtime_trace"]
    assert any(
        event["stage"] == "routing"
        and event["lever"] == "model_downshift"
        and event["action"] == "applied"
        and event["reason_code"] == "routing_treatment"
        for event in trace
    )
    proof = d.event_metadata["savings_proof"]
    assert proof["method"] == "route_counterfactual"
    assert _money(proof["actual_cost_usd"]) == d.realized_actual_cost_usd
    assert _money(proof["baseline_cost_usd"]) == d.realized_naive_cost_usd
    assert _money(proof["gross_savings_usd"]) == d.realized_savings_usd
    assert proof["optimization_overhead_cost_usd"] is None
    assert proof["net_savings_usd"] is None
    if d.realized_savings_usd is None:
        assert proof["confidence"] == "requires_aggregate_holdback"
        assert "aggregate_holdback_required" in proof["reason_codes"]
    else:
        assert proof["confidence"] in {"measured_priced", "measured_pricing_uncertain"}
    assert proof["quality_status"] == "passed"
    assert proof["pricing_status"] == d.pricing_status


@pytest.mark.anyio
async def test_planner_trace_uses_persisted_outcome_prior(
    async_client, async_provision, async_db_session, monkeypatch, mock_openai
):
    p = await async_provision()
    _configure_key(monkeypatch, p["project_id"])
    _add_routing_policy(async_db_session, p, holdback="0.0")
    async_db_session.add(
        EngineOutcomePrior(
            organization_id=uuid.UUID(p["org_id"]),
            project_id=uuid.UUID(p["project_id"]),
            lever="model_downshift",
            task_type="classification.intent",
            risk_level="low",
            provider_requested="openai",
            model_requested=CHAT,
            provider_chosen="openai",
            model_chosen="gpt-3.5-turbo",
            readiness_status="auto_apply_candidate",
            sample_count=25,
            measured_savings_count=25,
            total_gross_savings_usd=Decimal("1.25"),
            average_gross_savings_usd=Decimal("0.05"),
            quality_pass_rate=Decimal("1.0000"),
            feedback_acceptance_rate=Decimal("1.0000"),
            reason_codes=[],
            window_days=30,
            computed_at=datetime.now(UTC),
        )
    )
    await async_db_session.flush()

    resp = await async_client.post("/v1/chat/completions", headers=_low_risk_headers(p["api_key"]), json=_body())
    assert resp.status_code == 200

    d = (await _decisions(async_db_session, p["project_id"]))[0]
    route_candidate = next(
        c for c in d.event_metadata["optimization_plan"]["candidates"] if c["lever"] == "model_routing"
    )
    assert route_candidate["status"] == "recommendable"
    assert route_candidate["reason_code"] == "outcome_prior_recommendable"
    prior = route_candidate["reason_detail"]["outcome_prior"]
    assert prior["readiness_status"] == "auto_apply_candidate"
    assert prior["sample_count"] == 25
    assert route_candidate["estimated_savings_usd"] == "0.05000000"


@pytest.mark.anyio
async def test_evidence_holdback_control(async_client, async_provision, async_db_session, monkeypatch, mock_openai):
    p = await async_provision()
    _configure_key(monkeypatch, p["project_id"])
    _add_routing_policy(async_db_session, p, holdback="1.0")  # always control
    await async_db_session.flush()
    monkeypatch.setattr("app.proxy.routing.random.random", lambda: 0.0)

    resp = await async_client.post("/v1/chat/completions", headers=_low_risk_headers(p["api_key"]), json=_body())
    assert resp.status_code == 200
    assert resp.headers.get("X-Varsten-Arm") == "control"

    d = (await _decisions(async_db_session, p["project_id"]))[0]
    assert d.arm == "control"
    assert d.decision_type == "experiment_control"
    assert d.route_eligible is True
    assert d.optimization_applied is False
    proof = d.event_metadata["savings_proof"]
    assert proof["method"] == "holdback_observation"
    assert proof["confidence"] == "requires_aggregate_holdback"
    assert proof["gross_savings_usd"] is None
    assert proof["optimization_overhead_cost_usd"] is None
    assert proof["net_savings_usd"] is None
    assert proof["quality_status"] == "passed"
    assert "aggregate_holdback_required" in proof["reason_codes"]
    trace = d.event_metadata["runtime_trace"]
    assert any(event["stage"] == "routing" and event["action"] == "control" for event in trace)


@pytest.mark.anyio
async def test_evidence_routing_policy_blocked_for_unknown_task(
    async_client, async_provision, async_db_session, monkeypatch, mock_openai
):
    p = await async_provision()
    _configure_key(monkeypatch, p["project_id"])
    _add_routing_policy(async_db_session, p, holdback="0.0")
    await async_db_session.flush()

    resp = await async_client.post(
        "/v1/chat/completions", headers={"Authorization": f"Bearer {p['api_key']}"}, json=_body()
    )

    assert resp.status_code == 200
    assert "X-Varsten-Arm" not in resp.headers
    d = (await _decisions(async_db_session, p["project_id"]))[0]
    assert d.decision_type == "passthrough"
    assert d.route_eligible is False
    assert d.route_ineligible_reason == "routing_blocked_by_risk"
    proof = d.event_metadata["savings_proof"]
    assert proof["method"] == "none"
    assert proof["confidence"] == "not_applicable"
    assert proof["gross_savings_usd"] is None
    assert proof["optimization_overhead_cost_usd"] is None
    assert proof["net_savings_usd"] is None
    assert proof["quality_status"] == "not_measured"
    trace = d.event_metadata["runtime_trace"]
    assert any(
        event["stage"] == "routing"
        and event["action"] == "skipped"
        and event["reason_code"] == "routing_blocked_by_risk"
        and event["enforced"] is True
        for event in trace
    )


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
    trace = d.event_metadata["runtime_trace"]
    assert any(
        event["stage"] == "routing"
        and event["action"] == "skipped"
        and event["reason_code"] == "server_side_tool"
        and event["enforced"] is True
        for event in trace
    )


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
    trace = d.event_metadata["runtime_trace"]
    assert any(
        event["stage"] == "cache_lookup"
        and event["lever"] == "exact_cache"
        and event["reason_code"] == "optimization_disabled"
        for event in trace
    )


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
