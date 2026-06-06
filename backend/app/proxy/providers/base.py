"""The provider adapter seam.

An LLMAdapter translates between Varsten's canonical (OpenAI-shaped) form and ONE
upstream provider's wire format. The proxy router talks only to this interface, so
adding Anthropic, Gemini, or Bedrock is a new adapter plus a registry entry, with
zero changes to the router. Adapters own only the upstream side; rendering back to
the OpenAI client dialect is the shared concern in canonical.py.
"""

from abc import ABC, abstractmethod
from collections.abc import Iterator

from app.proxy.providers.canonical import CanonicalCompletion


class StreamTranslator(ABC):
    """Drives one streaming response. The router feeds upstream byte chunks to
    push() and forwards whatever bytes it yields to the client (already in OpenAI
    SSE form); after the upstream stream ends it calls finish() for the assembled
    completion to meter and cache. One instance per request; holds accumulation
    state. A same-dialect (OpenAI) translator passes bytes through untouched for
    zero added latency; a cross-dialect translator emits translated OpenAI SSE."""

    @abstractmethod
    def push(self, upstream_chunk: bytes) -> Iterator[bytes]:
        """Consume one upstream chunk; yield zero or more client OpenAI-SSE chunks."""

    @abstractmethod
    def finish(self) -> CanonicalCompletion:
        """The assembled completion, after the upstream stream is exhausted."""


class LLMAdapter(ABC):
    """One upstream provider, behind a uniform interface. Stateless: a single
    instance is registered and shared; per-request state lives in the translator."""

    provider: str

    @abstractmethod
    def endpoint(self) -> str:
        """The upstream chat-completions URL."""

    @abstractmethod
    def headers(self, api_key: str) -> dict[str, str]:
        """Auth + content headers for the upstream call."""

    @abstractmethod
    def prepare_request(self, body: dict, *, model: str, stream: bool) -> dict:
        """Translate an OpenAI-shaped request body into this provider's wire request,
        applying the (possibly routed) model and the stream flag. Delivery-agnostic:
        the same translated request is what gets forwarded now, serialized into a
        batch line, or redirected by an approve-mode routing policy."""

    @abstractmethod
    def parse_completion(self, raw: dict) -> CanonicalCompletion:
        """Translate a non-streaming provider response into the canonical form."""

    @abstractmethod
    def stream_translator(self) -> StreamTranslator:
        """A fresh per-request translator for the streaming path."""
