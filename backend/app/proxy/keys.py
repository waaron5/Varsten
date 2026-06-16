"""Resolve and store per-project upstream provider keys.

The hot path calls provider_key_for_project(project_id, provider). In production
that key is stored in AWS Secrets Manager, but every read is protected by a
process-local TTL cache so cached tenant lookups stay sub-millisecond. The legacy
OpenAI env map remains as the dev/test fallback and rollback path.
"""

import json
import threading
import uuid
from collections.abc import Callable
from typing import Any

import boto3
from botocore.exceptions import ClientError
from cachetools import TTLCache

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("varsten.proxy.keys")


class ProviderKeyStoreUnsupported(RuntimeError):
    """Raised when the configured key backend cannot write provider keys."""


def _provider(provider: str) -> str:
    return provider.strip().lower()


class ProviderKeyCache:
    """Thread-safe TTL cache for decrypted provider keys.

    cachetools.TTLCache is not thread-safe by itself, so all access is guarded by
    a re-entrant lock. Fetches happen under the lock to prevent a thundering herd
    of Secrets Manager calls when a tenant's cache entry expires.
    """

    def __init__(
        self,
        fetcher: Callable[[uuid.UUID, str], str | None],
        *,
        ttl_seconds: int = 300,
        maxsize: int = 4096,
    ) -> None:
        self._fetcher = fetcher
        self._cache: TTLCache[tuple[str, str], str | None] = TTLCache(
            maxsize=max(1, maxsize),
            ttl=max(1, ttl_seconds),
        )
        self._lock = threading.RLock()

    def get(self, project_id: uuid.UUID, provider: str) -> str | None:
        key = (str(project_id), _provider(provider))
        with self._lock:
            try:
                return self._cache[key]
            except KeyError:
                value = self._fetcher(project_id, key[1])
                self._cache[key] = value
                return value

    def clear(self, project_id: uuid.UUID | None = None, provider: str | None = None) -> None:
        with self._lock:
            if project_id is None and provider is None:
                self._cache.clear()
                return
            normalized_provider = _provider(provider) if provider else None
            for key in list(self._cache.keys()):
                key_project, key_provider = key
                if project_id is not None and key_project != str(project_id):
                    continue
                if normalized_provider is not None and key_provider != normalized_provider:
                    continue
                self._cache.pop(key, None)


class EnvProviderKeyResolver:
    """Development/test resolver backed by JSON env maps."""

    def get(self, project_id: uuid.UUID, provider: str) -> str | None:
        project_key = str(project_id)
        provider_name = _provider(provider)

        provider_first = settings.proxy_provider_keys.get(provider_name)
        if provider_first and provider_first.get(project_key):
            return provider_first[project_key]

        project_first = settings.proxy_provider_keys.get(project_key)
        if project_first and project_first.get(provider_name):
            return project_first[provider_name]

        if provider_name == "openai":
            return settings.proxy_openai_keys.get(project_key)
        if provider_name == "anthropic":
            return settings.proxy_anthropic_keys.get(project_key)
        if provider_name == "gemini":
            return settings.proxy_gemini_keys.get(project_key)
        return None

    def store(self, project_id: uuid.UUID, provider: str, api_key: str) -> str:
        raise ProviderKeyStoreUnsupported("provider key writes require provider_key_backend='secretsmanager'")

    def delete(self, project_id: uuid.UUID, provider: str) -> None:
        raise ProviderKeyStoreUnsupported("provider key deletes require provider_key_backend='secretsmanager'")


class SecretsManagerProviderKeyResolver:
    """AWS Secrets Manager resolver.

    Secret value format:
        {"api_key": "..."}
    """

    def __init__(self, client: Any | None = None) -> None:
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            kwargs = {}
            if settings.provider_key_aws_region:
                kwargs["region_name"] = settings.provider_key_aws_region
            self._client = boto3.client("secretsmanager", **kwargs)
        return self._client

    def secret_name(self, project_id: uuid.UUID, provider: str) -> str:
        return (
            f"{settings.provider_key_secret_prefix}/"
            f"{settings.provider_key_secret_environment}/"
            f"provider-keys/{project_id}/{_provider(provider)}"
        )

    def get(self, project_id: uuid.UUID, provider: str) -> str | None:
        name = self.secret_name(project_id, provider)
        try:
            raw = self.client.get_secret_value(SecretId=name)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code != "ResourceNotFoundException":
                logger.warning(
                    "provider key secret read failed",
                    extra={"project_id": str(project_id), "provider": _provider(provider), "code": code},
                )
            return None

        secret = raw.get("SecretString")
        if secret is None and raw.get("SecretBinary") is not None:
            secret = raw["SecretBinary"].decode("utf-8")
        if not secret:
            return None
        try:
            data = json.loads(secret)
        except json.JSONDecodeError:
            logger.warning(
                "provider key secret is not valid json",
                extra={"project_id": str(project_id), "provider": _provider(provider)},
            )
            return None
        key = data.get("api_key")
        return key if isinstance(key, str) and key else None

    def store(self, project_id: uuid.UUID, provider: str, api_key: str) -> str:
        name = self.secret_name(project_id, provider)
        payload = json.dumps({"api_key": api_key}, separators=(",", ":"))
        try:
            self.client.create_secret(Name=name, SecretString=payload)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code != "ResourceExistsException":
                raise
            self.client.put_secret_value(SecretId=name, SecretString=payload)
        clear_provider_key_cache(project_id, provider)
        return name

    def delete(self, project_id: uuid.UUID, provider: str) -> None:
        name = self.secret_name(project_id, provider)
        try:
            self.client.delete_secret(SecretId=name, ForceDeleteWithoutRecovery=True)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code != "ResourceNotFoundException":
                raise
        clear_provider_key_cache(project_id, provider)


def _resolver():
    backend = settings.provider_key_backend.strip().lower()
    if backend == "secretsmanager":
        return SecretsManagerProviderKeyResolver()
    if backend == "env":
        return EnvProviderKeyResolver()
    logger.warning("unknown provider key backend; using env", extra={"backend": settings.provider_key_backend})
    return EnvProviderKeyResolver()


def _fetch_provider_key(project_id: uuid.UUID, provider: str) -> str | None:
    return _resolver().get(project_id, provider)


_provider_key_cache = ProviderKeyCache(
    _fetch_provider_key,
    ttl_seconds=settings.provider_key_cache_ttl_seconds,
    maxsize=settings.provider_key_cache_maxsize,
)


def clear_provider_key_cache(project_id: uuid.UUID | None = None, provider: str | None = None) -> None:
    _provider_key_cache.clear(project_id, provider)


def provider_key_for_project(project_id: uuid.UUID, provider: str) -> str | None:
    return _provider_key_cache.get(project_id, provider)


def store_provider_key_for_project(project_id: uuid.UUID, provider: str, api_key: str) -> str:
    if not api_key:
        raise ValueError("api_key must not be empty")
    ref = _resolver().store(project_id, provider, api_key)
    clear_provider_key_cache(project_id, provider)
    return ref


def delete_provider_key_for_project(project_id: uuid.UUID, provider: str) -> None:
    _resolver().delete(project_id, provider)
    clear_provider_key_cache(project_id, provider)


def openai_key_for_project(project_id: uuid.UUID) -> str | None:
    """Backward-compatible wrapper for existing OpenAI-only callers."""
    return provider_key_for_project(project_id, "openai")
