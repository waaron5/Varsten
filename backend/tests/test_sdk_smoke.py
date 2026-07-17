"""Opt-in smoke tests for official SDK drop-in compatibility.

These are intentionally not part of the default backend gate. They use real SDK
clients against a running Varsten server and may reach real upstream providers
depending on the project's configured keys and routing policies.
"""

import importlib
import os
from dataclasses import dataclass
from typing import Any

import pytest

pytestmark = pytest.mark.sdk_smoke


@dataclass(frozen=True)
class SmokeConfig:
    base_url: str
    api_key: str
    openai_model: str
    anthropic_model: str
    gemini_model: str


def _smoke_config() -> SmokeConfig:
    if os.getenv("VARSTEN_SDK_SMOKE") != "1":
        pytest.skip("set VARSTEN_SDK_SMOKE=1 to run live SDK smoke tests")
    base_url = os.getenv("VARSTEN_SDK_SMOKE_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    api_key = os.getenv("VARSTEN_SDK_SMOKE_API_KEY")
    if not api_key:
        pytest.fail("VARSTEN_SDK_SMOKE_API_KEY must be set to a Varsten vk_ API key")
    assert api_key is not None
    return SmokeConfig(
        base_url=base_url,
        api_key=api_key,
        openai_model=os.getenv("VARSTEN_SDK_SMOKE_OPENAI_MODEL", "gpt-4o-mini"),
        anthropic_model=os.getenv("VARSTEN_SDK_SMOKE_ANTHROPIC_MODEL", "claude-haiku-4-5-20251001"),
        gemini_model=os.getenv("VARSTEN_SDK_SMOKE_GEMINI_MODEL", "gemini-2.5-flash"),
    )


def _required_module(import_name: str, install_name: str) -> Any:
    try:
        return importlib.import_module(import_name)
    except ImportError:
        pytest.fail(f"{install_name} is required for VARSTEN_SDK_SMOKE=1")


def _nonempty(text: str | None) -> str:
    value = (text or "").strip()
    assert value
    return value


def _anthropic_text(response: Any) -> str:
    parts: list[str] = []
    for block in getattr(response, "content", []) or []:
        text = getattr(block, "text", None)
        if text is None and isinstance(block, dict):
            text = block.get("text")
        if text:
            parts.append(str(text))
    return "".join(parts)


def _anthropic_stream_text(events: Any) -> str:
    parts: list[str] = []
    for event in events:
        if getattr(event, "type", "") != "content_block_delta":
            continue
        delta = getattr(event, "delta", None)
        text = getattr(delta, "text", None)
        if text:
            parts.append(str(text))
    return "".join(parts)


def test_openai_sdk_chat_completion_and_stream_smoke():
    cfg = _smoke_config()
    openai = _required_module("openai", "openai")
    client = openai.OpenAI(api_key=cfg.api_key, base_url=f"{cfg.base_url}/v1")

    response = client.chat.completions.create(
        model=cfg.openai_model,
        messages=[{"role": "user", "content": "Reply with one short sentence about Varsten."}],
        max_tokens=24,
    )
    _nonempty(response.choices[0].message.content)

    chunks = client.chat.completions.create(
        model=cfg.openai_model,
        messages=[{"role": "user", "content": "Reply with one short sentence about Varsten."}],
        max_tokens=24,
        stream=True,
    )
    stream_text = "".join(
        chunk.choices[0].delta.content or "" for chunk in chunks if chunk.choices and chunk.choices[0].delta
    )
    _nonempty(stream_text)


def test_anthropic_sdk_messages_and_stream_smoke():
    cfg = _smoke_config()
    anthropic = _required_module("anthropic", "anthropic")
    client = anthropic.Anthropic(api_key=cfg.api_key, base_url=cfg.base_url)

    response = client.messages.create(
        model=cfg.anthropic_model,
        max_tokens=24,
        messages=[{"role": "user", "content": "Reply with one short sentence about Varsten."}],
    )
    _nonempty(_anthropic_text(response))

    events = client.messages.create(
        model=cfg.anthropic_model,
        max_tokens=24,
        messages=[{"role": "user", "content": "Reply with one short sentence about Varsten."}],
        stream=True,
    )
    _nonempty(_anthropic_stream_text(events))


def test_google_genai_sdk_generate_content_and_stream_smoke():
    cfg = _smoke_config()
    genai = _required_module("google.genai", "google-genai")
    types = _required_module("google.genai.types", "google-genai")
    client = genai.Client(
        api_key=cfg.api_key,
        http_options=types.HttpOptions(base_url=cfg.base_url, api_version="v1beta"),
    )

    response = client.models.generate_content(
        model=cfg.gemini_model,
        contents="Reply with one short sentence about Varsten.",
    )
    _nonempty(getattr(response, "text", ""))

    chunks = client.models.generate_content_stream(
        model=cfg.gemini_model,
        contents="Reply with one short sentence about Varsten.",
    )
    stream_text = "".join(getattr(chunk, "text", "") or "" for chunk in chunks)
    _nonempty(stream_text)
