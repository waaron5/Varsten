"""Parse incoming SDK wire shapes without choosing an upstream provider.

The client dialect layer answers only: "what request shape did the client send?"
It must not decide where the request should be routed. In particular, Gemini's
OpenAI-compatible endpoint is classified as the OpenAI dialect because its wire
shape is OpenAI chat completions; the router later decides whether the upstream
destination is Gemini, OpenAI, or another provider.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit

from app.engine.request_facts import normalize_request_facts
from app.engine.types import RequestFacts


class ClientDialect(StrEnum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI_NATIVE = "gemini_native"


class UnsupportedClientDialect(ValueError):
    """Raised when a request path/method is not a supported client SDK shape."""


@dataclass(frozen=True)
class ParsedClientRequest:
    dialect: ClientDialect
    operation: str
    method: str
    path: str
    headers: dict[str, str]
    body: dict[str, Any]
    request_facts: RequestFacts = field(init=False)
    model: str | None = None
    models: tuple[str, ...] = field(default_factory=tuple)
    stream: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_facts", normalize_request_facts(self.body))


_GEMINI_MODEL_ACTION = re.compile(r"^/(?:v1|v1beta)/models/(?P<model>[^:]+):(?P<action>[A-Za-z]+)$")


def classify_client_dialect(
    *,
    method: str,
    path: str,
    headers: dict[str, str],
    body: dict[str, Any],
) -> ParsedClientRequest:
    return ClientDialectAdapter().parse(method=method, path=path, headers=headers, body=body)


class ClientDialectAdapter:
    """Classify supported SDK dialects from request shape only."""

    def parse(
        self,
        *,
        method: str,
        path: str,
        headers: dict[str, str],
        body: dict[str, Any],
    ) -> ParsedClientRequest:
        clean_method = method.upper()
        clean_path = _path_only(path)
        normalized_headers = {key.lower(): value for key, value in headers.items()}
        if clean_method != "POST":
            raise UnsupportedClientDialect(f"unsupported client dialect method: {clean_method}")

        parsed = (
            self._parse_openai_compatible(clean_method, clean_path, normalized_headers, body)
            or self._parse_anthropic(clean_method, clean_path, normalized_headers, body)
            or self._parse_gemini_native(clean_method, clean_path, normalized_headers, body)
        )
        if parsed is None:
            raise UnsupportedClientDialect(f"unsupported client dialect path: {clean_path}")
        return parsed

    def _parse_openai_compatible(
        self,
        method: str,
        path: str,
        headers: dict[str, str],
        body: dict[str, Any],
    ) -> ParsedClientRequest | None:
        if path not in {"/v1/chat/completions", "/v1beta/openai/chat/completions", "/v1/openai/chat/completions"}:
            return None
        return ParsedClientRequest(
            dialect=ClientDialect.OPENAI,
            operation="chat_completions",
            method=method,
            path=path,
            headers=headers,
            body=body,
            model=_body_model(body),
            models=_single_model_tuple(_body_model(body)),
            stream=bool(body.get("stream")),
        )

    def _parse_anthropic(
        self,
        method: str,
        path: str,
        headers: dict[str, str],
        body: dict[str, Any],
    ) -> ParsedClientRequest | None:
        if path == "/v1/messages":
            operation = "messages"
            model = _body_model(body)
            models = _single_model_tuple(model)
        elif path == "/v1/messages/count_tokens":
            operation = "count_tokens"
            model = _body_model(body)
            models = _single_model_tuple(model)
        elif path == "/v1/messages/batches":
            operation = "message_batch_create"
            models = _anthropic_batch_models(body)
            model = models[0] if len(models) == 1 else None
        else:
            return None

        return ParsedClientRequest(
            dialect=ClientDialect.ANTHROPIC,
            operation=operation,
            method=method,
            path=path,
            headers=headers,
            body=body,
            model=model,
            models=models,
            stream=bool(body.get("stream")),
        )

    def _parse_gemini_native(
        self,
        method: str,
        path: str,
        headers: dict[str, str],
        body: dict[str, Any],
    ) -> ParsedClientRequest | None:
        if path in {"/v1beta/batches", "/v1/batches"}:
            model = _normalize_gemini_model(_body_model(body))
            return ParsedClientRequest(
                dialect=ClientDialect.GEMINI_NATIVE,
                operation="batch_create",
                method=method,
                path=path,
                headers=headers,
                body=body,
                model=model,
                models=_single_model_tuple(model),
            )

        match = _GEMINI_MODEL_ACTION.match(path)
        if match is None:
            return None

        action = match.group("action")
        operation = {
            "generateContent": "generate_content",
            "streamGenerateContent": "stream_generate_content",
            "countTokens": "count_tokens",
        }.get(action)
        if operation is None:
            return None

        model = _normalize_gemini_model(match.group("model"))
        return ParsedClientRequest(
            dialect=ClientDialect.GEMINI_NATIVE,
            operation=operation,
            method=method,
            path=path,
            headers=headers,
            body=body,
            model=model,
            models=_single_model_tuple(model),
            stream=operation == "stream_generate_content",
        )


def _path_only(path: str) -> str:
    parsed = urlsplit(path)
    clean = parsed.path or path
    return clean.rstrip("/") or "/"


def _body_model(body: dict[str, Any]) -> str | None:
    model = body.get("model")
    return model if isinstance(model, str) and model else None


def _single_model_tuple(model: str | None) -> tuple[str, ...]:
    return (model,) if model else ()


def _normalize_gemini_model(model: str | None) -> str | None:
    if model is None:
        return None
    return model.removeprefix("models/")


def _anthropic_batch_models(body: dict[str, Any]) -> tuple[str, ...]:
    models: list[str] = []
    for request in body.get("requests") or []:
        if not isinstance(request, dict):
            continue
        params = request.get("params")
        if not isinstance(params, dict):
            continue
        model = params.get("model")
        if isinstance(model, str) and model and model not in models:
            models.append(model)
    return tuple(models)
