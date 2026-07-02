import json
import uuid
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models import Project, ProxyPolicy, RequestDecisionEvent, UsageEvent
from app.proxy import circuit, http_client

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "provider_contracts"


@pytest.fixture(autouse=True)
def reset_circuit():
    circuit.reset_all()
    yield
    circuit.reset_all()


def _fixture_body(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text())["body"]


def _fixture_text(name: str) -> str:
    return (FIXTURE_DIR / name).read_text()


@pytest.fixture
def mock_native_providers(monkeypatch):
    state: dict = {"requests": []}

    def handler(request: httpx.Request) -> httpx.Response:
        state["requests"].append(request)
        path = request.url.path
        payload = json.loads(request.content) if request.content else {}
        if path == "/v1/messages":
            if payload.get("stream"):
                return httpx.Response(
                    200,
                    content=_fixture_text("anthropic_messages_stream.sse").encode(),
                    headers={"content-type": "text/event-stream"},
                )
            return httpx.Response(200, json=_fixture_body("anthropic_messages_response.json"))
        if path == "/v1/messages/count_tokens":
            return httpx.Response(200, json=_fixture_body("anthropic_count_tokens_response.json"))
        if path == "/v1/messages/batches":
            return httpx.Response(200, json=_fixture_body("anthropic_message_batch_result.json"))
        if path == "/v1beta/batches":
            return httpx.Response(200, json=_fixture_body("gemini_batch_result.json"))
        if path.endswith(":countTokens"):
            return httpx.Response(200, json=_fixture_body("gemini_count_tokens_response.json"))
        if path.endswith(":generateContent"):
            assert "contents" in payload
            return httpx.Response(200, json=_fixture_body("gemini_generate_content_response.json"))
        if path.endswith(":streamGenerateContent"):
            return httpx.Response(
                200,
                content=_fixture_text("gemini_stream_generate_content.sse").encode(),
                headers={"content-type": "text/event-stream"},
            )
        return httpx.Response(404, json={"error": {"message": f"unmocked path {path}"}})

    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(http_client, "_client", real_async_client(transport=httpx.MockTransport(handler)))
    return state


def _b(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _configure_native_keys(monkeypatch, project_id: str) -> None:
    monkeypatch.setattr(settings, "proxy_anthropic_keys", {project_id: "sk-ant-test"})
    monkeypatch.setattr(settings, "proxy_gemini_keys", {project_id: "sk-gemini-test"})


def _route_policy(project: Project, incumbent: str, candidate_model: str, candidate_provider: str) -> ProxyPolicy:
    return ProxyPolicy(
        organization_id=project.organization_id,
        project_id=project.id,
        lever="model_downshift",
        target_type="model",
        target_key=incumbent,
        params={"candidate_model": candidate_model, "candidate_provider": candidate_provider},
        holdback_percent=Decimal("0"),
        enabled=True,
    )


async def _usage_events(async_db_session, project_id: str) -> list[UsageEvent]:
    return (
        await async_db_session.scalars(
            select(UsageEvent).where(UsageEvent.project_id == project_id).order_by(UsageEvent.occurred_at.asc())
        )
    ).all()


async def _decisions(async_db_session, project_id: str) -> list[RequestDecisionEvent]:
    return (
        await async_db_session.scalars(
            select(RequestDecisionEvent)
            .where(RequestDecisionEvent.project_id == uuid.UUID(project_id))
            .order_by(RequestDecisionEvent.created_at.asc())
        )
    ).all()


@pytest.mark.anyio
async def test_anthropic_native_messages_preserves_wire_and_records_usage(
    async_client, async_db_session, async_provision, mock_native_providers, monkeypatch
):
    ws = await async_provision()
    _configure_native_keys(monkeypatch, ws["project_id"])
    body = _fixture_body("anthropic_messages_request.json")

    res = await async_client.post("/v1/messages", headers=_b(ws["api_key"]), json=body)

    assert res.status_code == 200
    payload = res.json()
    assert payload["type"] == "message"
    assert "choices" not in payload
    events = await _usage_events(async_db_session, ws["project_id"])
    assert len(events) == 1
    assert events[0].provider == "anthropic"
    assert events[0].input_tokens == 17
    assert events[0].output_tokens == 13
    decisions = await _decisions(async_db_session, ws["project_id"])
    assert len(decisions) == 1
    assert decisions[0].event_metadata["optimization_plan"]["selected"]["action"] == "observe"
    assert decisions[0].event_metadata["optimization_plan"]["classification"]["task_type"] is None


@pytest.mark.anyio
async def test_anthropic_native_accepts_sdk_x_api_key_header(
    async_client, async_db_session, async_provision, mock_native_providers, monkeypatch
):
    ws = await async_provision()
    _configure_native_keys(monkeypatch, ws["project_id"])
    body = _fixture_body("anthropic_messages_request.json")

    res = await async_client.post(
        "/v1/messages",
        headers={"x-api-key": ws["api_key"], "anthropic-version": "2023-06-01"},
        json=body,
    )

    assert res.status_code == 200
    assert res.json()["type"] == "message"
    assert mock_native_providers["requests"][-1].url.path == "/v1/messages"


@pytest.mark.anyio
async def test_anthropic_native_stream_is_raw_but_ledger_uses_stream_usage(
    async_client, async_db_session, async_provision, mock_native_providers, monkeypatch
):
    ws = await async_provision()
    _configure_native_keys(monkeypatch, ws["project_id"])
    body = {**_fixture_body("anthropic_messages_request.json"), "stream": True}

    res = await async_client.post("/v1/messages", headers=_b(ws["api_key"]), json=body)

    assert res.status_code == 200
    assert "event: message_start" in res.text
    assert "chat.completion.chunk" not in res.text
    events = await _usage_events(async_db_session, ws["project_id"])
    assert len(events) == 1
    assert events[0].provider == "anthropic"
    assert events[0].input_tokens == 17
    assert events[0].output_tokens == 6


@pytest.mark.anyio
async def test_gemini_native_generate_content_preserves_wire_and_records_usage(
    async_client, async_db_session, async_provision, mock_native_providers, monkeypatch
):
    ws = await async_provision()
    _configure_native_keys(monkeypatch, ws["project_id"])
    body = _fixture_body("gemini_generate_content_request.json")

    res = await async_client.post(
        "/v1beta/models/gemini-3.5-flash:generateContent",
        headers=_b(ws["api_key"]),
        json=body,
    )

    assert res.status_code == 200
    payload = res.json()
    assert "candidates" in payload
    assert "choices" not in payload
    events = await _usage_events(async_db_session, ws["project_id"])
    assert len(events) == 1
    assert events[0].provider == "gemini"
    assert events[0].input_tokens == 17
    assert events[0].output_tokens == 13


@pytest.mark.anyio
async def test_gemini_native_accepts_sdk_x_goog_api_key_header(
    async_client, async_db_session, async_provision, mock_native_providers, monkeypatch
):
    ws = await async_provision()
    _configure_native_keys(monkeypatch, ws["project_id"])
    body = _fixture_body("gemini_generate_content_request.json")

    res = await async_client.post(
        "/v1beta/models/gemini-3.5-flash:generateContent",
        headers={"x-goog-api-key": ws["api_key"]},
        json=body,
    )

    assert res.status_code == 200
    assert "candidates" in res.json()
    assert mock_native_providers["requests"][-1].url.path == "/v1beta/models/gemini-3.5-flash:generateContent"


@pytest.mark.anyio
async def test_gemini_openai_compatible_path_stays_openai_dialect_but_routes_to_gemini(
    async_client, async_db_session, async_provision, mock_native_providers, monkeypatch
):
    ws = await async_provision()
    _configure_native_keys(monkeypatch, ws["project_id"])
    body = _fixture_body("gemini_openai_chat_completion_request.json")

    res = await async_client.post("/v1beta/openai/chat/completions", headers=_b(ws["api_key"]), json=body)

    assert res.status_code == 200
    payload = res.json()
    assert payload["object"] == "chat.completion"
    assert payload["choices"][0]["message"]["content"].startswith("Varsten reduces")
    upstream = mock_native_providers["requests"][-1]
    assert upstream.url.path == "/v1beta/models/gemini-3.5-flash:generateContent"
    assert json.loads(upstream.content)["contents"]
    events = await _usage_events(async_db_session, ws["project_id"])
    assert len(events) == 1
    assert events[0].provider == "gemini"


@pytest.mark.anyio
async def test_anthropic_count_tokens_is_passthrough_without_ledger_row(
    async_client, async_db_session, async_provision, mock_native_providers, monkeypatch
):
    ws = await async_provision()
    _configure_native_keys(monkeypatch, ws["project_id"])
    project = await async_db_session.get(Project, uuid.UUID(ws["project_id"]))
    assert project is not None
    async_db_session.add(_route_policy(project, "claude-3-5-sonnet-20241022", "gemini-3.5-flash", "gemini"))
    await async_db_session.flush()
    body = _fixture_body("anthropic_count_tokens_request.json")

    res = await async_client.post("/v1/messages/count_tokens", headers=_b(ws["api_key"]), json=body)

    assert res.status_code == 200
    assert res.json() == _fixture_body("anthropic_count_tokens_response.json")
    upstream = mock_native_providers["requests"][-1]
    assert upstream.url.path == "/v1/messages/count_tokens"
    assert json.loads(upstream.content) == body
    assert await _usage_events(async_db_session, ws["project_id"]) == []


@pytest.mark.anyio
async def test_gemini_native_count_tokens_is_passthrough_without_ledger_row(
    async_client, async_db_session, async_provision, mock_native_providers, monkeypatch
):
    ws = await async_provision()
    _configure_native_keys(monkeypatch, ws["project_id"])
    project = await async_db_session.get(Project, uuid.UUID(ws["project_id"]))
    assert project is not None
    async_db_session.add(_route_policy(project, "gemini-3.5-flash", "gpt-4o", "openai"))
    await async_db_session.flush()
    body = _fixture_body("gemini_count_tokens_request.json")

    res = await async_client.post(
        "/v1beta/models/gemini-3.5-flash:countTokens",
        headers=_b(ws["api_key"]),
        json=body,
    )

    assert res.status_code == 200
    assert res.json() == _fixture_body("gemini_count_tokens_response.json")
    upstream = mock_native_providers["requests"][-1]
    assert upstream.url.path == "/v1beta/models/gemini-3.5-flash:countTokens"
    assert json.loads(upstream.content) == body
    assert await _usage_events(async_db_session, ws["project_id"]) == []


@pytest.mark.anyio
async def test_anthropic_native_message_batch_create_is_passthrough_without_ledger_row(
    async_client, async_db_session, async_provision, mock_native_providers, monkeypatch
):
    ws = await async_provision()
    _configure_native_keys(monkeypatch, ws["project_id"])
    body = _fixture_body("anthropic_message_batch_create_request.json")

    res = await async_client.post("/v1/messages/batches", headers=_b(ws["api_key"]), json=body)

    assert res.status_code == 200
    assert res.json() == _fixture_body("anthropic_message_batch_result.json")
    upstream = mock_native_providers["requests"][-1]
    assert upstream.url.path == "/v1/messages/batches"
    assert json.loads(upstream.content) == body
    assert await _usage_events(async_db_session, ws["project_id"]) == []


@pytest.mark.anyio
async def test_gemini_native_batch_create_is_passthrough_without_ledger_row(
    async_client, async_db_session, async_provision, mock_native_providers, monkeypatch
):
    ws = await async_provision()
    _configure_native_keys(monkeypatch, ws["project_id"])
    body = _fixture_body("gemini_batch_create_request.json")

    res = await async_client.post("/v1beta/batches", headers=_b(ws["api_key"]), json=body)

    assert res.status_code == 200
    assert res.json() == _fixture_body("gemini_batch_result.json")
    upstream = mock_native_providers["requests"][-1]
    assert upstream.url.path == "/v1beta/batches"
    assert json.loads(upstream.content) == body
    assert await _usage_events(async_db_session, ws["project_id"]) == []
