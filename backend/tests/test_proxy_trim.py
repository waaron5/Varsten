"""Token-trim lever: the execution side.

Covers the pure deterministic transform, policy activation/deactivation via the
apply path, hot-path execution (the proxy actually forwards a trimmed body and
tags the holdback arm), and objective drift auto-rollback. OpenAI is mocked.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models import ModelPrice, Project, ProxyPolicy, Recommendation, UsageEvent
from app.proxy import circuit
from app.proxy import drift as drift_mod
from app.proxy import router as proxy_router
from app.proxy.execution import activate_execution, deactivate_execution
from app.proxy.trim import LEVER, apply_trim, resolve_trim, trim_messages

MODEL = "gpt-4o"


@pytest.fixture(autouse=True)
def reset_circuit():
    circuit.reset_all()
    yield
    circuit.reset_all()


def _project(db, provision) -> Project:
    ws = provision(sub="auth0|trim", email="trim@example.com")
    return db.get(Project, uuid.UUID(ws["project_id"]))


def _trim_rec(db, project) -> Recommendation:
    rec = Recommendation(
        organization_id=project.organization_id,
        project_id=project.id,
        dedupe_key=f"trim-{uuid.uuid4()}",
        type="token_trim",
        lever="token_trim",
        title="Trim context for support",
        description="x",
        rationale="y",
        risk_level="medium",
        confidence="medium",
        related_model=MODEL,
        related_provider="openai",
        monthly_request_volume=1000,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


# --- pure transform -------------------------------------------------------------


def test_trim_prunes_old_turns_keeps_system():
    messages = [{"role": "system", "content": "be helpful"}]
    messages += [{"role": "user", "content": f"msg {i}"} for i in range(20)]
    trimmed, changed = trim_messages(messages, {"keep_last_turns": 5})
    assert changed
    # System survives, only the last 5 non-system turns remain.
    assert trimmed[0] == {"role": "system", "content": "be helpful"}
    assert len(trimmed) == 6
    assert trimmed[-1]["content"] == "msg 19"


def test_trim_dedupes_and_collapses_whitespace():
    messages = [
        {"role": "user", "content": "hello    world"},
        {"role": "user", "content": "hello    world"},
    ]
    trimmed, changed = trim_messages(messages, {"keep_last_turns": 0})
    assert changed
    assert len(trimmed) == 1
    assert trimmed[0]["content"] == "hello world"


def test_trim_noop_on_small_clean_prompt():
    messages = [{"role": "user", "content": "hi"}]
    trimmed, changed = trim_messages(messages)
    assert changed is False
    assert trimmed == messages


def test_trim_passes_through_multimodal_content():
    messages = [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "x"}}]}]
    trimmed, changed = trim_messages(messages)
    assert changed is False
    assert trimmed == messages


def test_apply_trim_does_not_mutate_original():
    body = {
        "model": MODEL,
        "messages": [
            {"role": "user", "content": "a    b"},
            {"role": "user", "content": "a    b"},
        ],
    }
    new_body, changed = apply_trim(body)
    assert changed
    assert len(body["messages"]) == 2  # original untouched
    assert len(new_body["messages"]) == 1


# --- policy lifecycle -----------------------------------------------------------


@pytest.mark.anyio
async def test_resolve_trim_only_when_enabled(async_provision, async_db_session):
    ws = await async_provision(sub="auth0|trim", email="trim@example.com")
    project = await async_db_session.get(Project, uuid.UUID(ws["project_id"]))
    policy = ProxyPolicy(
        organization_id=project.organization_id,
        project_id=project.id,
        lever=LEVER,
        target_type="model",
        target_key=MODEL,
        enabled=True,
        holdback_percent=Decimal("0.1"),
    )
    async_db_session.add(policy)
    await async_db_session.flush()
    assert await resolve_trim(async_db_session, project.id, MODEL) is not None
    assert await resolve_trim(async_db_session, project.id, "other") is None

    policy.enabled = False
    await async_db_session.flush()
    assert await resolve_trim(async_db_session, project.id, MODEL) is None


def test_activate_then_deactivate_trim(client, provision, db_session):
    project = _project(db_session, provision)
    rec = _trim_rec(db_session, project)
    activate_execution(db_session, project, rec, None)  # ungated: no gating run
    db_session.commit()
    policy = db_session.scalar(select(ProxyPolicy).where(ProxyPolicy.project_id == project.id))
    assert policy.lever == LEVER and policy.enabled and policy.target_key == MODEL

    deactivate_execution(db_session, rec)
    db_session.commit()
    db_session.refresh(policy)
    assert policy.enabled is False


def test_apply_through_engine_activates_trim(client, provision, db_session):
    project = _project(db_session, provision)
    rec = _trim_rec(db_session, project)
    resp = client.patch(
        f"/v1/engine/recommendations/{rec.id}",
        headers={"Authorization": "Bearer auth0|trim"},
        params={"project_id": str(project.id)},
        json={"status": "applied"},
    )
    assert resp.status_code == 200  # ungated: applies without an eval run
    policy = db_session.scalar(select(ProxyPolicy).where(ProxyPolicy.project_id == project.id))
    assert policy is not None and policy.lever == LEVER and policy.enabled


# --- hot path -------------------------------------------------------------------


def _mock_openai(monkeypatch, seen: dict):
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen["messages"] = payload["messages"]
        seen["model"] = payload["model"]
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-x",
                "object": "chat.completion",
                "model": payload["model"],
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60},
            },
        )

    real = httpx.AsyncClient
    monkeypatch.setattr(proxy_router.httpx, "AsyncClient", lambda *a, **k: real(transport=httpx.MockTransport(handler)))


def _redundant_messages() -> list[dict]:
    msgs = [{"role": "system", "content": "be    helpful"}]
    msgs += [{"role": "user", "content": f"turn {i}"} for i in range(30)]
    return msgs


@pytest.mark.anyio
async def test_proxy_trims_treatment_body(async_client, async_provision, async_db_session, monkeypatch):
    monkeypatch.setattr(settings, "proxy_cache_enabled", False)
    ws = await async_provision(sub="auth0|trim2", email="trim2@example.com")
    project = await async_db_session.get(Project, uuid.UUID(ws["project_id"]))
    monkeypatch.setattr(settings, "proxy_openai_keys", {str(project.id): "sk-test"})
    async_db_session.add(
        ProxyPolicy(
            organization_id=project.organization_id,
            project_id=project.id,
            lever=LEVER,
            target_type="model",
            target_key=MODEL,
            enabled=True,
            holdback_percent=Decimal("0"),  # always treatment
        )
    )
    await async_db_session.flush()

    seen: dict = {}
    _mock_openai(monkeypatch, seen)
    resp = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {ws['api_key']}"},
        json={"model": MODEL, "messages": _redundant_messages(), "stream": False},
    )
    assert resp.status_code == 200
    assert resp.headers.get("X-Varsten-Trim") == "applied"
    assert resp.headers.get("X-Varsten-Arm") == "treatment"
    # The forwarded body was trimmed: far fewer messages than the 31 sent.
    assert len(seen["messages"]) < 31


@pytest.mark.anyio
async def test_proxy_holdback_leaves_control_untrimmed(async_client, async_provision, async_db_session, monkeypatch):
    monkeypatch.setattr(settings, "proxy_cache_enabled", False)
    ws = await async_provision(sub="auth0|trim3", email="trim3@example.com")
    project = await async_db_session.get(Project, uuid.UUID(ws["project_id"]))
    monkeypatch.setattr(settings, "proxy_openai_keys", {str(project.id): "sk-test"})
    async_db_session.add(
        ProxyPolicy(
            organization_id=project.organization_id,
            project_id=project.id,
            lever=LEVER,
            target_type="model",
            target_key=MODEL,
            enabled=True,
            holdback_percent=Decimal("1.0"),  # always control
        )
    )
    await async_db_session.flush()

    seen: dict = {}
    _mock_openai(monkeypatch, seen)
    resp = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {ws['api_key']}"},
        json={"model": MODEL, "messages": _redundant_messages(), "stream": False},
    )
    assert resp.status_code == 200
    assert "X-Varsten-Trim" not in resp.headers
    assert resp.headers.get("X-Varsten-Arm") == "control"
    # Control arm is held back untrimmed: the full body went upstream.
    assert len(seen["messages"]) == 31


# --- drift auto-rollback --------------------------------------------------------


def _record_trim_arm(db, project, arm, input_tokens, ok):
    # Sync ORM seed mirroring record_proxy_usage for a trim experiment (from == to
    # == MODEL), so the sync drift/reporting endpoints can read it. Cost is derived
    # from the token counts at the MODEL catalog rate these tests seed
    # (0.00001 in / 0.00003 out), so the reporting A/B numbers line up.
    cost = (Decimal(input_tokens) * Decimal("0.00001") + Decimal(10) * Decimal("0.00003")).quantize(
        Decimal("0.00000001")
    )
    meta = {
        "proxy": True,
        "cache": "miss",
        "holdback": True,
        "arm": arm,
        "experiment_from": MODEL,
        "experiment_to": MODEL,
        "quality_ok": ok,
    }
    db.add(
        UsageEvent(
            project_id=project.id,
            organization_id=project.organization_id,
            api_key_id=None,
            provider="openai",
            model=MODEL,
            operation="chat_completion",
            request_type="chat_completion",
            feature="proxy",
            environment="production",
            input_tokens=input_tokens,
            output_tokens=10,
            cached_input_tokens=0,
            total_tokens=input_tokens + 10,
            cost_usd=cost,
            cost_source="catalog",
            pricing_status="priced",
            currency="USD",
            status="success",
            success=True,
            event_metadata=meta,
            occurred_at=datetime.now(UTC),
        )
    )


def test_trim_drift_auto_rollback(client, provision, db_session, monkeypatch):
    monkeypatch.setattr(drift_mod, "MIN_ARM_SAMPLES", 4)
    project = _project(db_session, provision)
    rec = _trim_rec(db_session, project)
    policy = ProxyPolicy(
        organization_id=project.organization_id,
        project_id=project.id,
        lever=LEVER,
        target_type="model",
        target_key=MODEL,
        enabled=True,
        holdback_percent=Decimal("0.1"),
        source_recommendation_id=rec.id,
    )
    db_session.add(policy)
    db_session.commit()

    # Control (untrimmed) healthy; treatment (trimmed) degraded.
    for _ in range(5):
        _record_trim_arm(db_session, project, "control", 1000, True)
    for _ in range(5):
        _record_trim_arm(db_session, project, "treatment", 600, False)
    db_session.commit()

    resp = client.post(
        "/v1/engine/routes/check-drift",
        headers={"Authorization": "Bearer auth0|trim"},
        params={"project_id": str(project.id)},
    )
    assert resp.status_code == 200
    assert len(resp.json()["rolled_back"]) == 1
    db_session.refresh(policy)
    db_session.refresh(rec)
    assert policy.enabled is False
    assert rec.status == "rolled_back"


def test_engine_update_trim_pauses_and_caps_holdback(client, provision, db_session):
    project = _project(db_session, provision)
    policy = ProxyPolicy(
        organization_id=project.organization_id,
        project_id=project.id,
        lever=LEVER,
        target_type="model",
        target_key=MODEL,
        enabled=True,
        holdback_percent=Decimal("0.05"),
    )
    db_session.add(policy)
    db_session.commit()

    resp = client.patch(
        f"/v1/engine/trims/{policy.id}",
        headers={"Authorization": "Bearer auth0|trim"},
        params={"project_id": str(project.id)},
        json={"enabled": False, "holdback_percent": "0.2"},
    )
    assert resp.status_code == 200
    db_session.refresh(policy)
    assert policy.enabled is False and policy.holdback_percent == Decimal("0.2")

    bad = client.patch(
        f"/v1/engine/trims/{policy.id}",
        headers={"Authorization": "Bearer auth0|trim"},
        params={"project_id": str(project.id)},
        json={"holdback_percent": "0.9"},
    )
    assert bad.status_code == 422


def test_engine_trims_reports_ab(client, provision, db_session):
    project = _project(db_session, provision)
    at = datetime.now(UTC) - timedelta(days=1)
    db_session.add(
        ModelPrice(
            model_key=MODEL,
            provider="openai",
            currency="USD",
            input_cost_per_token=Decimal("0.00001"),
            output_cost_per_token=Decimal("0.00003"),
            source="catalog",
            effective_at=at,
        )
    )
    db_session.add(
        ProxyPolicy(
            organization_id=project.organization_id,
            project_id=project.id,
            lever=LEVER,
            target_type="model",
            target_key=MODEL,
            enabled=True,
            holdback_percent=Decimal("0.1"),
            activated_at=datetime.now(UTC),
        )
    )
    # Control untrimmed (1000 in), treatment trimmed (600 in): measured token delta.
    for _ in range(2):
        _record_trim_arm(db_session, project, "control", 1000, True)
    for _ in range(3):
        _record_trim_arm(db_session, project, "treatment", 600, True)
    db_session.commit()

    resp = client.get(
        "/v1/engine/trims",
        headers={"Authorization": "Bearer auth0|trim"},
        params={"project_id": str(project.id)},
    )
    assert resp.status_code == 200
    row = resp.json()[0]
    assert row["model"] == MODEL
    assert row["control_requests"] == 2 and row["treatment_requests"] == 3
    # control cost = 1000*1e-5 + 10*3e-5 = 0.0103; treatment = 600*1e-5 + 10*3e-5 = 0.0063
    assert Decimal(row["control_avg_cost_usd"]) == Decimal("0.0103")
    assert Decimal(row["treatment_avg_cost_usd"]) == Decimal("0.0063")
    assert Decimal(row["savings_per_request_usd"]) == Decimal("0.004")
