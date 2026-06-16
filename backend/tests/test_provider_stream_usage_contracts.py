import json
from pathlib import Path

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "provider_contracts"


def _sse_blocks(name: str) -> list[bytes]:
    raw = (FIXTURE_DIR / name).read_text()
    return [f"{block}\n\n".encode() for block in raw.split("\n\n") if block.strip()]


def _latest_usage(translator) -> tuple[int, int]:
    usage = translator.current_usage
    return usage.input_tokens, usage.output_tokens


def test_anthropic_stream_usage_is_captured_from_message_start_before_yielding():
    from app.proxy.providers.anthropic import AnthropicAdapter

    translator = AnthropicAdapter().stream_translator()
    first_block = _sse_blocks("anthropic_messages_stream.sse")[0]
    emitted = list(translator.push(first_block))

    assert _latest_usage(translator) == (17, 1)
    assert emitted


def test_anthropic_stream_usage_is_updated_from_message_delta_before_finish():
    from app.proxy.providers.anthropic import AnthropicAdapter

    translator = AnthropicAdapter().stream_translator()
    usage_snapshots: list[tuple[int, int]] = []
    for block in _sse_blocks("anthropic_messages_stream.sse"):
        list(translator.push(block))
        usage_snapshots.append(_latest_usage(translator))

    assert (17, 1) in usage_snapshots
    assert usage_snapshots[-1] == (17, 6)
    assert _latest_usage(translator) == (17, 6)


def test_unknown_anthropic_stream_events_do_not_erase_usage():
    from app.proxy.providers.anthropic import AnthropicAdapter

    translator = AnthropicAdapter().stream_translator()
    list(translator.push(_sse_blocks("anthropic_messages_stream.sse")[0]))
    assert _latest_usage(translator) == (17, 1)

    unknown = b'event: future_event\ndata: {"type":"future_event","value":"ignored"}\n\n'
    list(translator.push(unknown))

    assert _latest_usage(translator) == (17, 1)


def test_gemini_stream_usage_metadata_is_normalized_when_present():
    from app.proxy.providers.gemini import GeminiAdapter

    translator = GeminiAdapter().stream_translator()
    first_block = _sse_blocks("gemini_stream_generate_content.sse")[0]
    list(translator.push(first_block))

    assert _latest_usage(translator) == (17, 1)


def test_final_stream_without_usage_preserves_last_known_usage():
    from app.proxy.providers.gemini import GeminiAdapter

    translator = GeminiAdapter().stream_translator()
    first_payload = {
        "candidates": [{"content": {"role": "model", "parts": [{"text": "hello"}]}, "index": 0}],
        "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 1, "totalTokenCount": 6},
    }
    final_payload_without_usage = {
        "candidates": [
            {
                "content": {"role": "model", "parts": [{"text": " world"}]},
                "finishReason": "STOP",
                "index": 0,
            }
        ]
    }

    list(translator.push(f"data: {json.dumps(first_payload)}\n\n".encode()))
    list(translator.push(f"data: {json.dumps(final_payload_without_usage)}\n\n".encode()))

    completion = translator.finish()
    assert _latest_usage(translator) == (5, 1)
    assert completion.usage.input_tokens == 5
    assert completion.usage.output_tokens == 1


def test_anthropic_nonstream_usage_is_normalized_from_response_fixture():
    from app.proxy.providers.anthropic import AnthropicAdapter

    envelope = json.loads((FIXTURE_DIR / "anthropic_messages_response.json").read_text())
    completion = AnthropicAdapter().parse_completion(envelope["body"])

    assert completion.model == "claude-3-5-sonnet-20241022"
    assert completion.usage.input_tokens == 17
    assert completion.usage.output_tokens == 13


def test_gemini_nonstream_usage_is_normalized_from_response_fixture():
    from app.proxy.providers.gemini import GeminiAdapter

    envelope = json.loads((FIXTURE_DIR / "gemini_generate_content_response.json").read_text())
    completion = GeminiAdapter().parse_completion(envelope["body"])

    assert completion.model == "gemini-3.5-flash"
    assert completion.usage.input_tokens == 17
    assert completion.usage.output_tokens == 13


def test_anthropic_and_gemini_adapters_are_registered():
    from app.proxy.providers import get_adapter

    assert get_adapter("anthropic").provider == "anthropic"
    assert get_adapter("gemini").provider == "gemini"
