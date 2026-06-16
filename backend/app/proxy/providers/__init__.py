"""Provider adapter registry.

get_adapter(provider) returns the registered LLMAdapter for a provider string.
Adding a provider is: implement an LLMAdapter, then register() it here. The proxy
router resolves adapters only through get_adapter, so a new provider needs no
router changes.
"""

from app.proxy.providers.anthropic import AnthropicAdapter
from app.proxy.providers.base import LLMAdapter, StreamTranslator
from app.proxy.providers.canonical import CanonicalCompletion, CanonicalUsage
from app.proxy.providers.gemini import GeminiAdapter
from app.proxy.providers.openai import OpenAIAdapter

__all__ = [
    "CanonicalCompletion",
    "CanonicalUsage",
    "LLMAdapter",
    "StreamTranslator",
    "get_adapter",
    "register",
]


class UnknownProvider(Exception):
    """Raised when no adapter is registered for the requested provider."""


_REGISTRY: dict[str, LLMAdapter] = {}


def register(adapter: LLMAdapter) -> None:
    _REGISTRY[adapter.provider] = adapter


def get_adapter(provider: str) -> LLMAdapter:
    try:
        return _REGISTRY[provider]
    except KeyError as exc:
        raise UnknownProvider(provider) from exc


register(OpenAIAdapter())
register(AnthropicAdapter())
register(GeminiAdapter())
