import json
import uuid
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models import OptimizationDecision, Project, ProxyPolicy, UsageEvent
from app.proxy import circuit, http_client

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "provider_contracts"

OPENAI_MODEL = "gpt-4o"
GEMINI_MODEL = "gemini-3.5-flash"
ANTHROPIC_MODEL = "claude-3-5-sonnet-20241022"

TOOL_STREAM_BODY = (
    'data: {"id":"x","object":"chat.completion.chunk","model":"gpt-4o","choices":[{"index":0,'
    '"delta":{"role":"assistant","content":null,"tool_calls":[{"index":0,"id":"call_1","type":"function",'
    '"function":{"name":"get_weather","arguments":""}}]},"finish_reason":null}]}\n\n'
    'data: {"id":"x","object":"chat.completion.chunk","model":"gpt-4o","choices":[{"index":0,'
    '"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\\"city\\":"}}]},"finish_reason":null}]}\n\n'
    'data: {"id":"x","object":"chat.completion.chunk","model":"gpt-4o","choices":[{"index":0,'
    '"delta":{"tool_calls":[{"index":0,"function":{"arguments":"\\"Paris\\"}"}}]},"finish_reason":null}]}\n\n'
    'data: {"id":"x","object":"chat.completion.chunk","model":"gpt-4o","choices":[{"index":0,'
    '"delta":{},"finish_reason":"tool_calls"}]}\n\n'
    'data: {"id":"x","object":"chat.completion.chunk","model":"gpt-4o","choices":[],'
    '"usage":{"prompt_tokens":20,"completion_tokens":8,"total_tokens":28}}\n\n'
    "data: [DONE]\n\n"
)


@pytest.fixture(autouse=True)
def reset_circuit():
    circuit.reset_all()
    yield
    circuit.reset_all()


def _fixture_body(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text())["body"]


def _fixture_text(name: str) -> str:
    return (FIXTURE_DIR / name).read_text()


def _b(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _sse_payloads(body: str) -> list[dict]:
    payloads = []
    for block in body.replace("\r\n", "\n").split("\n\n"):
        lines = []
        for raw_line in block.splitlines():
            line = raw_line.strip()
            if line.startswith("data:"):
                data = line[len("data:") :].strip()
                if data and data != "[DONE]":
                    lines.append(data)
        if lines:
            payloads.append(json.loads("\n".join(lines)))
    return payloads


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


def _configure_keys(monkeypatch, project_id: str) -> None:
    monkeypatch.setattr(settings, "proxy_openai_keys", {project_id: "sk-openai-test"})
    monkeypatch.setattr(settings, "proxy_gemini_keys", {project_id: "sk-gemini-test"})
    monkeypatch.setattr(settings, "proxy_anthropic_keys", {project_id: "sk-ant-test"})


def _mock_upstreams(monkeypatch, seen: list[tuple[str, dict]]):
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content) if request.content else {}
        seen.append((request.url.path, payload))
        if request.url.path == "/v1/chat/completions":
            if payload.get("stream"):
                body = TOOL_STREAM_BODY if payload.get("tools") else _fixture_text("openai_chat_completion_stream.sse")
                return httpx.Response(
                    200,
                    content=body.encode(),
                    headers={"content-type": "text/event-stream"},
                )
            model = payload.get("model") or OPENAI_MODEL
            return httpx.Response(
                200,
                json={
                    "id": "chatcmpl-cross",
                    "object": "chat.completion",
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "OpenAI incumbent"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 11, "completion_tokens": 3, "total_tokens": 14},
                },
            )
        if request.url.path.endswith(":streamGenerateContent"):
            return httpx.Response(
                200,
                content=_fixture_text("gemini_stream_generate_content.sse").encode(),
                headers={"content-type": "text/event-stream"},
            )
        if request.url.path.endswith(":generateContent"):
            return httpx.Response(200, json=_fixture_body("gemini_generate_content_response.json"))
        if request.url.path == "/v1/messages":
            return httpx.Response(200, json=_fixture_body("anthropic_messages_response.json"))
        return httpx.Response(404, json={"error": {"message": f"unmocked {request.url.path}"}})

    real = httpx.AsyncClient
    monkeypatch.setattr(http_client, "_client", real(transport=httpx.MockTransport(handler)))


async def _project(async_provision, async_db_session, monkeypatch, sub: str) -> tuple[dict, Project]:
    monkeypatch.setattr(settings, "proxy_cache_enabled", False)
    ws = await async_provision(sub=sub, email=f"{sub}@example.com")
    _configure_keys(monkeypatch, ws["project_id"])
    project = await async_db_session.get(Project, uuid.UUID(ws["project_id"]))
    assert project is not None
    return ws, project


@pytest.mark.anyio
async def test_openai_compatible_request_routes_to_cross_provider_gemini(
    async_client, async_db_session, async_provision, monkeypatch
):
    ws, project = await _project(async_provision, async_db_session, monkeypatch, "auth0|cross-gemini")
    async_db_session.add(_route_policy(project, OPENAI_MODEL, GEMINI_MODEL, "gemini"))
    await async_db_session.flush()
    seen: list[tuple[str, dict]] = []
    _mock_upstreams(monkeypatch, seen)

    res = await async_client.post(
        "/v1/chat/completions",
        headers=_b(ws["api_key"]),
        json={"model": OPENAI_MODEL, "messages": [{"role": "user", "content": "hi"}]},
    )

    assert res.status_code == 200
    assert seen[-1][0] == f"/v1beta/models/{GEMINI_MODEL}:generateContent"
    assert "contents" in seen[-1][1]
    assert res.headers["X-Varsten-Routed"] == f"openai:{OPENAI_MODEL}->gemini:{GEMINI_MODEL}"
    event = await async_db_session.scalar(select(UsageEvent).where(UsageEvent.project_id == project.id))
    assert event is not None
    assert event.provider == "gemini"
    assert event.model == GEMINI_MODEL
    assert event.event_metadata["routed_from_provider"] == "openai"
    assert event.event_metadata["routed_to_provider"] == "gemini"


@pytest.mark.anyio
async def test_anthropic_native_request_routes_to_gemini_and_returns_anthropic_shape(
    async_client, async_db_session, async_provision, monkeypatch
):
    ws, project = await _project(async_provision, async_db_session, monkeypatch, "auth0|cross-anthropic-gemini")
    async_db_session.add(_route_policy(project, ANTHROPIC_MODEL, GEMINI_MODEL, "gemini"))
    await async_db_session.flush()
    seen: list[tuple[str, dict]] = []
    _mock_upstreams(monkeypatch, seen)

    res = await async_client.post(
        "/v1/messages",
        headers={**_b(ws["api_key"]), "anthropic-version": "2023-06-01"},
        json=_fixture_body("anthropic_messages_request.json"),
    )

    assert res.status_code == 200
    assert seen[-1][0] == f"/v1beta/models/{GEMINI_MODEL}:generateContent"
    assert "contents" in seen[-1][1]
    payload = res.json()
    assert payload["type"] == "message"
    assert "choices" not in payload and "candidates" not in payload
    assert payload["content"][0]["type"] == "text"
    assert payload["content"][0]["text"].startswith("Varsten reduces")
    assert res.headers["X-Varsten-Routed"] == f"anthropic:{ANTHROPIC_MODEL}->gemini:{GEMINI_MODEL}"
    event = await async_db_session.scalar(select(UsageEvent).where(UsageEvent.project_id == project.id))
    assert event is not None
    assert event.provider == "gemini"
    assert event.event_metadata["routed_from_provider"] == "anthropic"
    assert event.event_metadata["routed_to_provider"] == "gemini"


@pytest.mark.anyio
async def test_gemini_native_request_routes_to_openai_and_returns_gemini_shape(
    async_client, async_db_session, async_provision, monkeypatch
):
    ws, project = await _project(async_provision, async_db_session, monkeypatch, "auth0|cross-gemini-openai")
    async_db_session.add(_route_policy(project, GEMINI_MODEL, OPENAI_MODEL, "openai"))
    await async_db_session.flush()
    seen: list[tuple[str, dict]] = []
    _mock_upstreams(monkeypatch, seen)

    res = await async_client.post(
        f"/v1beta/models/{GEMINI_MODEL}:generateContent",
        headers=_b(ws["api_key"]),
        json=_fixture_body("gemini_generate_content_request.json"),
    )

    assert res.status_code == 200
    assert seen[-1][0] == "/v1/chat/completions"
    assert "messages" in seen[-1][1]
    payload = res.json()
    assert "candidates" in payload
    assert "choices" not in payload
    assert payload["candidates"][0]["content"]["role"] == "model"
    assert payload["candidates"][0]["content"]["parts"][0]["text"] == "OpenAI incumbent"
    assert res.headers["X-Varsten-Routed"] == f"gemini:{GEMINI_MODEL}->openai:{OPENAI_MODEL}"
    event = await async_db_session.scalar(select(UsageEvent).where(UsageEvent.project_id == project.id))
    assert event is not None
    assert event.provider == "openai"
    assert event.event_metadata["routed_from_provider"] == "gemini"
    assert event.event_metadata["routed_to_provider"] == "openai"


@pytest.mark.anyio
async def test_anthropic_native_stream_routes_to_gemini_and_returns_anthropic_sse(
    async_client, async_db_session, async_provision, monkeypatch
):
    ws, project = await _project(async_provision, async_db_session, monkeypatch, "auth0|cross-anthropic-stream")
    async_db_session.add(_route_policy(project, ANTHROPIC_MODEL, GEMINI_MODEL, "gemini"))
    await async_db_session.flush()
    seen: list[tuple[str, dict]] = []
    _mock_upstreams(monkeypatch, seen)
    body = {**_fixture_body("anthropic_messages_request.json"), "stream": True}

    res = await async_client.post(
        "/v1/messages",
        headers={**_b(ws["api_key"]), "anthropic-version": "2023-06-01"},
        json=body,
    )

    assert res.status_code == 200
    assert seen[-1][0] == f"/v1beta/models/{GEMINI_MODEL}:streamGenerateContent"
    assert seen[-1][1]["contents"]
    assert "event: message_start" in res.text
    assert "event: content_block_delta" in res.text
    assert "event: message_delta" in res.text
    assert "event: message_stop" in res.text
    assert "chat.completion.chunk" not in res.text
    event = await async_db_session.scalar(select(UsageEvent).where(UsageEvent.project_id == project.id))
    assert event is not None
    assert event.provider == "gemini"
    assert event.input_tokens == 17
    assert event.output_tokens == 6
    assert event.event_metadata["routed_from_provider"] == "anthropic"
    assert event.event_metadata["routed_to_provider"] == "gemini"


@pytest.mark.anyio
async def test_gemini_native_stream_routes_to_openai_and_returns_gemini_sse(
    async_client, async_db_session, async_provision, monkeypatch
):
    ws, project = await _project(async_provision, async_db_session, monkeypatch, "auth0|cross-gemini-stream")
    async_db_session.add(_route_policy(project, GEMINI_MODEL, OPENAI_MODEL, "openai"))
    await async_db_session.flush()
    seen: list[tuple[str, dict]] = []
    _mock_upstreams(monkeypatch, seen)

    res = await async_client.post(
        f"/v1beta/models/{GEMINI_MODEL}:streamGenerateContent?alt=sse",
        headers=_b(ws["api_key"]),
        json=_fixture_body("gemini_generate_content_request.json"),
    )

    assert res.status_code == 200
    assert seen[-1][0] == "/v1/chat/completions"
    assert seen[-1][1]["stream"] is True
    assert '"candidates"' in res.text
    assert '"usageMetadata"' in res.text
    assert "chat.completion.chunk" not in res.text
    event = await async_db_session.scalar(select(UsageEvent).where(UsageEvent.project_id == project.id))
    assert event is not None
    assert event.provider == "openai"
    assert event.input_tokens == 19
    assert event.output_tokens == 6
    assert event.event_metadata["routed_from_provider"] == "gemini"
    assert event.event_metadata["routed_to_provider"] == "openai"


@pytest.mark.anyio
async def test_anthropic_native_tool_stream_routes_to_openai_and_returns_tool_use_sse(
    async_client, async_db_session, async_provision, monkeypatch
):
    ws, project = await _project(async_provision, async_db_session, monkeypatch, "auth0|cross-anthropic-tool-stream")
    async_db_session.add(_route_policy(project, ANTHROPIC_MODEL, OPENAI_MODEL, "openai"))
    await async_db_session.flush()
    seen: list[tuple[str, dict]] = []
    _mock_upstreams(monkeypatch, seen)
    body = {
        "model": ANTHROPIC_MODEL,
        "max_tokens": 256,
        "stream": True,
        "tools": [
            {
                "name": "get_weather",
                "description": "Return current weather for a city.",
                "input_schema": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                },
            }
        ],
        "messages": [{"role": "user", "content": "What is the weather in Paris?"}],
    }

    res = await async_client.post(
        "/v1/messages",
        headers={**_b(ws["api_key"]), "anthropic-version": "2023-06-01"},
        json=body,
    )

    assert res.status_code == 200
    assert seen[-1][0] == "/v1/chat/completions"
    assert seen[-1][1]["tools"][0]["function"]["name"] == "get_weather"
    payloads = _sse_payloads(res.text)
    starts = [payload for payload in payloads if payload.get("type") == "content_block_start"]
    tool_start = next(payload for payload in starts if payload["content_block"]["type"] == "tool_use")
    assert tool_start["content_block"]["name"] == "get_weather"
    assert tool_start["content_block"]["id"] == "call_1"
    deltas = [
        payload
        for payload in payloads
        if payload.get("type") == "content_block_delta" and payload.get("delta", {}).get("type") == "input_json_delta"
    ]
    assert "".join(delta["delta"]["partial_json"] for delta in deltas) == '{"city":"Paris"}'
    message_delta = next(payload for payload in payloads if payload.get("type") == "message_delta")
    assert message_delta["delta"]["stop_reason"] == "tool_use"
    assert message_delta["usage"]["output_tokens"] == 8
    event = await async_db_session.scalar(select(UsageEvent).where(UsageEvent.project_id == project.id))
    assert event is not None
    assert event.provider == "openai"
    assert event.input_tokens == 20
    assert event.output_tokens == 8


@pytest.mark.anyio
async def test_gemini_native_tool_stream_routes_to_openai_and_returns_function_call_sse(
    async_client, async_db_session, async_provision, monkeypatch
):
    ws, project = await _project(async_provision, async_db_session, monkeypatch, "auth0|cross-gemini-tool-stream")
    async_db_session.add(_route_policy(project, GEMINI_MODEL, OPENAI_MODEL, "openai"))
    await async_db_session.flush()
    seen: list[tuple[str, dict]] = []
    _mock_upstreams(monkeypatch, seen)

    res = await async_client.post(
        f"/v1beta/models/{GEMINI_MODEL}:streamGenerateContent?alt=sse",
        headers=_b(ws["api_key"]),
        json=_fixture_body("gemini_function_call_request.json"),
    )

    assert res.status_code == 200
    assert seen[-1][0] == "/v1/chat/completions"
    assert seen[-1][1]["tools"][0]["function"]["name"] == "get_weather"
    payloads = _sse_payloads(res.text)
    parts = [
        part
        for payload in payloads
        for candidate in payload.get("candidates", [])
        for part in candidate.get("content", {}).get("parts", [])
    ]
    function_call = next(part["functionCall"] for part in parts if "functionCall" in part)
    assert function_call["name"] == "get_weather"
    assert function_call["args"] == {"city": "Paris"}
    final = payloads[-1]
    assert final["usageMetadata"]["promptTokenCount"] == 20
    assert final["usageMetadata"]["candidatesTokenCount"] == 8
    event = await async_db_session.scalar(select(UsageEvent).where(UsageEvent.project_id == project.id))
    assert event is not None
    assert event.provider == "openai"
    assert event.input_tokens == 20
    assert event.output_tokens == 8


@pytest.mark.anyio
async def test_openai_multimodal_cross_provider_route_is_audited_and_kept_on_openai(
    async_client, async_db_session, async_provision, monkeypatch
):
    ws, project = await _project(async_provision, async_db_session, monkeypatch, "auth0|cross-openai-mm")
    async_db_session.add(_route_policy(project, OPENAI_MODEL, GEMINI_MODEL, "gemini"))
    await async_db_session.flush()
    seen: list[tuple[str, dict]] = []
    _mock_upstreams(monkeypatch, seen)
    request_id = "req_cross_multimodal"

    res = await async_client.post(
        "/v1/chat/completions",
        headers={**_b(ws["api_key"]), "X-Request-ID": request_id},
        json={
            "model": OPENAI_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "describe this"},
                        {"type": "image_url", "image_url": {"url": "https://example.test/image.png"}},
                    ],
                }
            ],
        },
    )

    assert res.status_code == 200
    assert seen[-1][0] == "/v1/chat/completions"
    assert "X-Varsten-Routed" not in res.headers
    decision = await async_db_session.scalar(
        select(OptimizationDecision).where(OptimizationDecision.request_id == request_id)
    )
    assert decision is not None
    assert decision.reason_code == "native_multimodal_unmapped"
    assert decision.requested_provider == "openai"
    assert decision.candidate_provider == "gemini"


@pytest.mark.anyio
async def test_anthropic_cache_control_cross_provider_route_is_audited_and_kept_on_anthropic(
    async_client, async_db_session, async_provision, monkeypatch
):
    ws, project = await _project(async_provision, async_db_session, monkeypatch, "auth0|cross-anthropic-cache")
    async_db_session.add(_route_policy(project, ANTHROPIC_MODEL, GEMINI_MODEL, "gemini"))
    await async_db_session.flush()
    seen: list[tuple[str, dict]] = []
    _mock_upstreams(monkeypatch, seen)
    request_id = "req_anthropic_cache_control"

    body = {
        "model": ANTHROPIC_MODEL,
        "max_tokens": 64,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Write one sentence about Varsten.",
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
            }
        ],
    }
    res = await async_client.post(
        "/v1/messages",
        headers={**_b(ws["api_key"]), "X-Request-ID": request_id, "anthropic-version": "2023-06-01"},
        json=body,
    )

    assert res.status_code == 200
    assert seen[-1][0] == "/v1/messages"
    assert res.json()["type"] == "message"
    decision = await async_db_session.scalar(
        select(OptimizationDecision).where(OptimizationDecision.request_id == request_id)
    )
    assert decision is not None
    assert decision.client_dialect == "anthropic"
    assert decision.reason_code == "anthropic_cache_control"
    assert decision.reason_detail == {"path": "/v1/messages", "field": "cache_control"}
