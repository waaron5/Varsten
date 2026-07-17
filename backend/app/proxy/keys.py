"""Resolve and store per-project upstream provider keys.

The hot path calls provider_key_for_project(project_id, provider). In production
that key is stored in AWS Secrets Manager, but every read is protected by a
process-local TTL cache so cached tenant lookups stay sub-millisecond. The legacy
OpenAI env map remains as the dev/test fallback and rollback path.
"""

import base64
import hashlib
import json
import threading
import uuid
from collections.abc import Callable
from typing import Any

import boto3
from botocore.exceptions import ClientError
from cachetools import TTLCache
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import SessionLocal

logger = get_logger("varsten.proxy.keys")


class ProviderKeyStoreUnsupported(RuntimeError):
    """Raised when the configured key backend cannot write provider keys."""

    code = "provider_key_storage_unavailable"

    def __init__(self, message: str, *, backend: str | None = None) -> None:
        super().__init__(message)
        self.backend = backend

    def detail(self) -> dict[str, str | None]:
        return {"code": self.code, "message": str(self), "backend": self.backend}


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
        raise ProviderKeyStoreUnsupported(
            "Provider key storage is not configured in this environment. A Varsten operator must finish setup manually.",
            backend="env",
        )

    def delete(self, project_id: uuid.UUID, provider: str) -> None:
        raise ProviderKeyStoreUnsupported(
            "Provider key storage is not configured in this environment. A Varsten operator must finish setup manually.",
            backend="env",
        )


class LocalDBProviderKeyResolver:
    """Local/dev encrypted database resolver.

    This keeps the self-serve path usable outside AWS without teaching production to
    accept plaintext env-vaulted writes. The ciphertext is stored as the
    provider_connection secret_ref and read through the same hot-path TTL cache.
    """

    PREFIX = "localdb:v1:"

    def _fernet(self) -> Fernet:
        raw = settings.provider_key_local_encryption_key.strip()
        if not raw:
            raise ProviderKeyStoreUnsupported(
                "Local provider key storage requires PROVIDER_KEY_LOCAL_ENCRYPTION_KEY.",
                backend="localdb",
            )
        try:
            key = raw.encode("utf-8")
            if len(key) == 44:
                return Fernet(key)
        except ValueError:
            logger.debug("provider_key_local_encryption_key is not raw Fernet key; deriving Fernet key from digest")
        digest = hashlib.sha256(raw.encode("utf-8")).digest()
        return Fernet(base64.urlsafe_b64encode(digest))

    def _encrypt_ref(self, api_key: str) -> str:
        token = self._fernet().encrypt(api_key.encode("utf-8")).decode("utf-8")
        return f"{self.PREFIX}{token}"

    def _decrypt_ref(self, ref: str) -> str | None:
        if not ref.startswith(self.PREFIX):
            return None
        token = ref[len(self.PREFIX) :].encode("utf-8")
        try:
            return self._fernet().decrypt(token).decode("utf-8")
        except (InvalidToken, ProviderKeyStoreUnsupported):
            logger.warning("local provider key decrypt failed")
            return None

    def get(self, project_id: uuid.UUID, provider: str) -> str | None:
        from app.models import ProviderConnection

        provider_name = _provider(provider)
        db = SessionLocal()
        try:
            connection = db.scalar(
                select(ProviderConnection).where(
                    ProviderConnection.project_id == project_id,
                    ProviderConnection.provider == provider_name,
                )
            )
            if connection is None:
                return EnvProviderKeyResolver().get(project_id, provider_name)
            if not connection.secret_ref:
                return None
            return self._decrypt_ref(connection.secret_ref)
        finally:
            db.close()

    def store(self, project_id: uuid.UUID, provider: str, api_key: str) -> str:
        from app.models import ProviderConnection

        provider_name = _provider(provider)
        secret_ref = self._encrypt_ref(api_key)
        db = SessionLocal()
        try:
            connection = db.scalar(
                select(ProviderConnection).where(
                    ProviderConnection.project_id == project_id,
                    ProviderConnection.provider == provider_name,
                )
            )
            if connection is not None:
                connection.secret_ref = secret_ref
                connection.connection_method = "local_db_encrypted"
            db.commit()
        finally:
            db.close()
        clear_provider_key_cache(project_id, provider_name)
        return secret_ref

    def delete(self, project_id: uuid.UUID, provider: str) -> None:
        from app.models import ProviderConnection

        provider_name = _provider(provider)
        db = SessionLocal()
        try:
            connection = db.scalar(
                select(ProviderConnection).where(
                    ProviderConnection.project_id == project_id,
                    ProviderConnection.provider == provider_name,
                )
            )
            if connection is not None:
                connection.secret_ref = None
                connection.connection_method = "local_db_encrypted"
            db.commit()
        finally:
            db.close()
        clear_provider_key_cache(project_id, provider_name)


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
        provider_name = _provider(provider)
        payload = json.dumps({"api_key": api_key}, separators=(",", ":"))
        create_args: dict[str, Any] = {
            "Name": name,
            "SecretString": payload,
            "Tags": [
                {"Key": "VarstenDataClass", "Value": "provider-key"},
                {"Key": "VarstenProjectId", "Value": str(project_id)},
                {"Key": "VarstenProvider", "Value": provider_name},
                {"Key": "Environment", "Value": settings.provider_key_secret_environment},
            ],
        }
        if settings.provider_key_kms_key_id:
            create_args["KmsKeyId"] = settings.provider_key_kms_key_id
        try:
            self.client.create_secret(**create_args)
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
    if backend in {"localdb", "local_db", "database"}:
        return LocalDBProviderKeyResolver()
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
