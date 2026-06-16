import json
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "provider_contracts"
MANIFEST = json.loads((FIXTURE_DIR / "manifest.json").read_text())


def _json_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text())


def _parse_sse(raw: str) -> list[dict]:
    events: list[dict] = []
    event_name = ""
    data_lines: list[str] = []
    for line in raw.splitlines():
        if not line.strip():
            if data_lines:
                events.append({"event": event_name, "data": "\n".join(data_lines)})
            event_name = ""
            data_lines = []
            continue
        if line.startswith("event:"):
            event_name = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:") :].strip())
    if data_lines:
        events.append({"event": event_name, "data": "\n".join(data_lines)})
    return events


def _event_json(event: dict) -> dict | None:
    data = event["data"]
    if data == "[DONE]":
        return None
    return json.loads(data)


def _body(envelope: dict) -> dict:
    body = envelope.get("body")
    assert isinstance(body, dict)
    return body


def test_manifest_covers_every_provider_contract_fixture():
    files = {p.name for p in FIXTURE_DIR.iterdir() if p.name != "manifest.json"}
    assert set(MANIFEST) == files


@pytest.mark.parametrize("name", sorted(name for name in MANIFEST if name.endswith(".json")))
def test_json_contract_fixtures_are_parseable_http_envelopes(name):
    meta = MANIFEST[name]
    envelope = _json_fixture(name)

    assert envelope["provider"] == meta["provider"]
    assert envelope["client_dialect"] == meta["client_dialect"]
    assert envelope["direction"] in {"request", "response"}
    assert isinstance(envelope["headers"], dict)
    assert isinstance(envelope["body"], dict)

    if envelope["direction"] == "request":
        assert envelope["method"] == "POST"
        assert envelope["path"].startswith("/")
    else:
        assert 100 <= envelope["status"] <= 599


@pytest.mark.parametrize("name", sorted(name for name in MANIFEST if name.endswith(".sse")))
def test_sse_contract_fixtures_are_parseable_event_streams(name):
    events = _parse_sse((FIXTURE_DIR / name).read_text())
    assert events
    for event in events:
        if event["data"] != "[DONE]":
            assert isinstance(_event_json(event), dict)


@pytest.mark.parametrize("name,meta", sorted(MANIFEST.items()))
def test_provider_contract_fixtures_have_required_wire_fields(name, meta):
    if name.endswith(".sse"):
        return

    envelope = _json_fixture(name)
    body = _body(envelope)
    provider = meta["provider"]
    operation = meta["operation"]
    direction = envelope["direction"]

    if provider == "openai" or meta["client_dialect"] == "openai":
        if direction == "request":
            assert "model" in body and isinstance(body.get("messages"), list)
            if operation in {"tools", "openai_tools"}:
                assert isinstance(body.get("tools"), list)
        elif meta.get("error"):
            assert "error" in body
        else:
            assert isinstance(body.get("choices"), list)
            assert isinstance(body.get("usage"), dict)

    if provider == "anthropic":
        if direction == "request" and operation.startswith("messages"):
            assert "model" in body and "max_tokens" in body and isinstance(body.get("messages"), list)
            if operation == "messages_tool":
                assert isinstance(body.get("tools"), list)
                assert any(
                    block.get("type") == "tool_result"
                    for message in body["messages"]
                    for block in (message.get("content") if isinstance(message.get("content"), list) else [])
                )
        elif operation == "count_tokens":
            assert ("model" in body and isinstance(body.get("messages"), list)) or "input_tokens" in body
        elif operation == "message_batch_create":
            assert isinstance(body.get("requests"), list)
            assert all("custom_id" in req and "params" in req for req in body["requests"])
        elif meta.get("error"):
            assert body.get("type") == "error" and isinstance(body.get("error"), dict)
        elif direction == "response":
            if operation == "message_batch_result":
                assert "custom_id" in body and "result" in body
            else:
                assert body.get("type") == "message"
                assert isinstance(body.get("content"), list)
                assert isinstance(body.get("usage"), dict)

    if provider == "gemini" and meta["client_dialect"] == "gemini_native":
        if direction == "request":
            if operation == "batch_create":
                assert "model" in body and "src" in body
            else:
                assert isinstance(body.get("contents"), list)
                if operation == "function_call":
                    assert isinstance(body.get("tools"), list)
        elif meta.get("error"):
            assert isinstance(body.get("error"), dict)
        elif operation == "count_tokens":
            assert isinstance(body.get("totalTokens"), int)
        elif operation == "batch_result":
            assert "metadata" in body and "response" in body
        else:
            assert isinstance(body.get("candidates"), list)
            assert isinstance(body.get("usageMetadata"), dict)


def test_anthropic_stream_usage_fixture_does_not_depend_on_terminal_usage():
    events = _parse_sse((FIXTURE_DIR / "anthropic_messages_stream.sse").read_text())
    typed = [(event["event"], _event_json(event)) for event in events]

    stop_index = next(i for i, (event_name, _) in enumerate(typed) if event_name == "message_stop")
    usage_indices = [
        i
        for i, (event_name, payload) in enumerate(typed)
        if event_name in {"message_start", "message_delta"} and payload and payload.get("usage")
    ]

    assert usage_indices
    assert max(usage_indices) < stop_index
    assert typed[stop_index][1] == {"type": "message_stop"}


@pytest.mark.parametrize("name,meta", sorted(MANIFEST.items()))
def test_stream_fixtures_include_usage_before_or_during_completion(name, meta):
    if not name.endswith(".sse") or not meta.get("usage_required_before_terminal"):
        return

    events = _parse_sse((FIXTURE_DIR / name).read_text())
    payloads = [_event_json(event) for event in events]

    if meta["provider"] == "anthropic":
        stop_index = next(i for i, event in enumerate(events) if event["event"] == "message_stop")
        usage_indices = [i for i, payload in enumerate(payloads) if payload and payload.get("usage")]
        assert usage_indices and max(usage_indices) < stop_index
    elif meta["client_dialect"] == "openai":
        done_index = next(i for i, event in enumerate(events) if event["data"] == "[DONE]")
        usage_indices = [i for i, payload in enumerate(payloads) if payload and payload.get("usage")]
        assert usage_indices and max(usage_indices) < done_index
    elif meta["provider"] == "gemini":
        usage_indices = [i for i, payload in enumerate(payloads) if payload and payload.get("usageMetadata")]
        finish_indices = [
            i
            for i, payload in enumerate(payloads)
            if payload
            for candidate in payload.get("candidates", [])
            if candidate.get("finishReason")
        ]
        assert usage_indices
        assert not finish_indices or max(usage_indices) <= max(finish_indices)
