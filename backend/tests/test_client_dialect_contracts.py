import json
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "provider_contracts"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text())


def _classify(name: str):
    from app.proxy.client_dialects import ClientDialect, classify_client_dialect

    envelope = _fixture(name)
    parsed = classify_client_dialect(
        method=envelope["method"],
        path=envelope["path"],
        headers=envelope["headers"],
        body=envelope["body"],
    )
    return ClientDialect, parsed


def test_openai_chat_completions_route_is_openai_client_dialect():
    ClientDialect, parsed = _classify("openai_chat_completion_request.json")

    assert parsed.dialect is ClientDialect.OPENAI
    assert parsed.operation == "chat_completions"
    assert parsed.model == "gpt-4o-mini"


def test_anthropic_messages_route_is_anthropic_client_dialect():
    ClientDialect, parsed = _classify("anthropic_messages_request.json")

    assert parsed.dialect is ClientDialect.ANTHROPIC
    assert parsed.operation == "messages"
    assert parsed.model == "claude-3-5-sonnet-20241022"


def test_gemini_native_generate_content_route_is_gemini_client_dialect():
    ClientDialect, parsed = _classify("gemini_generate_content_request.json")

    assert parsed.dialect is ClientDialect.GEMINI_NATIVE
    assert parsed.operation == "generate_content"
    assert parsed.model == "gemini-3.5-flash"


def test_gemini_openai_compat_route_is_strictly_openai_client_dialect():
    ClientDialect, parsed = _classify("gemini_openai_chat_completion_request.json")

    assert parsed.dialect is ClientDialect.OPENAI
    assert parsed.operation == "chat_completions"
    assert parsed.model == "gemini-3.5-flash"
    # Strict abstraction constraint: the dialect parser only identifies request
    # shape. It must not decide that Gemini is the upstream destination.
    assert not hasattr(parsed, "provider") or parsed.provider is None


def test_client_dialect_parser_preserves_headers_for_router_policy():
    _, parsed = _classify("anthropic_messages_tool_request.json")

    assert parsed.headers["anthropic-version"] == "2023-06-01"
    assert parsed.headers["anthropic-beta"] == "tools-2024-04-04"


def test_client_dialect_parser_attaches_content_free_request_facts():
    _, parsed = _classify("anthropic_messages_request.json")
    system_text = "You are a concise assistant."
    user_text = "Write one sentence about Varsten."

    assert parsed.request_facts.prompt_chars == len(system_text) + len(user_text)
    assert parsed.request_facts.message_count == 1
    assert parsed.request_facts.has_tools is False
    assert parsed.request_facts.source == "provider_body"
    assert system_text not in str(parsed.request_facts)
    assert user_text not in str(parsed.request_facts)


@pytest.mark.parametrize(
    "fixture_name,expected_message_count",
    [
        ("openai_chat_completion_tools_request.json", 1),
        ("anthropic_messages_tool_request.json", 3),
        ("gemini_function_call_request.json", 1),
    ],
)
def test_client_dialect_request_facts_capture_tool_signals_across_sdk_shapes(
    fixture_name,
    expected_message_count,
):
    _, parsed = _classify(fixture_name)

    assert parsed.request_facts.message_count == expected_message_count
    assert parsed.request_facts.has_tools is True
    assert parsed.request_facts.freshness_signal is True


@pytest.mark.parametrize(
    "fixture_name,expected_dialect,expected_operation,expected_model",
    [
        ("openai_chat_completion_tools_request.json", "OPENAI", "chat_completions", "gpt-4o-mini"),
        ("anthropic_count_tokens_request.json", "ANTHROPIC", "count_tokens", "claude-3-5-sonnet-20241022"),
        ("anthropic_message_batch_create_request.json", "ANTHROPIC", "message_batch_create", None),
        ("gemini_count_tokens_request.json", "GEMINI_NATIVE", "count_tokens", "gemini-3.5-flash"),
        ("gemini_function_call_request.json", "GEMINI_NATIVE", "generate_content", "gemini-3.5-flash"),
        ("gemini_batch_create_request.json", "GEMINI_NATIVE", "batch_create", "gemini-3.5-flash"),
        ("gemini_openai_tools_request.json", "OPENAI", "chat_completions", "gemini-3.5-flash"),
    ],
)
def test_client_dialect_parser_classifies_request_fixture_variants(
    fixture_name,
    expected_dialect,
    expected_operation,
    expected_model,
):
    ClientDialect, parsed = _classify(fixture_name)

    assert parsed.dialect is getattr(ClientDialect, expected_dialect)
    assert parsed.operation == expected_operation
    assert parsed.model == expected_model


def test_anthropic_batch_preserves_distinct_models_for_router_policy():
    _, parsed = _classify("anthropic_message_batch_create_request.json")

    assert parsed.models == ("claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022")
