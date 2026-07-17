import json
import uuid
from typing import Any

import pytest
from botocore.exceptions import ClientError

from app.core.config import settings
from app.proxy.keys import (
    ProviderKeyCache,
    ProviderKeyStoreUnsupported,
    SecretsManagerProviderKeyResolver,
    delete_provider_key_for_project,
    provider_key_for_project,
    store_provider_key_for_project,
)


class FakeSecretsManager:
    def __init__(self) -> None:
        self.secrets: dict[str, str] = {}
        self.created: list[str] = []
        self.updated: list[str] = []
        self.deleted: list[str] = []
        self.create_requests: list[dict[str, Any]] = []

    def get_secret_value(self, *, SecretId: str) -> dict[str, str]:
        if SecretId not in self.secrets:
            raise ClientError(
                {"Error": {"Code": "ResourceNotFoundException", "Message": "not found"}},
                "GetSecretValue",
            )
        return {"SecretString": self.secrets[SecretId]}

    def create_secret(
        self,
        *,
        Name: str,
        SecretString: str,
        KmsKeyId: str | None = None,
        Tags: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        if Name in self.secrets:
            raise ClientError(
                {"Error": {"Code": "ResourceExistsException", "Message": "exists"}},
                "CreateSecret",
            )
        self.created.append(Name)
        self.create_requests.append({"Name": Name, "KmsKeyId": KmsKeyId, "Tags": Tags})
        self.secrets[Name] = SecretString
        return {"Name": Name}

    def put_secret_value(self, *, SecretId: str, SecretString: str) -> dict[str, Any]:
        self.updated.append(SecretId)
        self.secrets[SecretId] = SecretString
        return {"Name": SecretId}

    def delete_secret(self, *, SecretId: str, ForceDeleteWithoutRecovery: bool) -> dict[str, Any]:
        if SecretId not in self.secrets:
            raise ClientError(
                {"Error": {"Code": "ResourceNotFoundException", "Message": "not found"}},
                "DeleteSecret",
            )
        assert ForceDeleteWithoutRecovery is True
        self.deleted.append(SecretId)
        del self.secrets[SecretId]
        return {"Name": SecretId}


def test_env_provider_key_resolver_supports_generic_and_legacy_maps(monkeypatch):
    project_id = uuid.uuid4()
    monkeypatch.setattr(settings, "provider_key_backend", "env")
    monkeypatch.setattr(
        settings,
        "proxy_provider_keys",
        {
            "anthropic": {str(project_id): "sk-ant-test"},
            str(project_id): {"gemini": "AIza-gemini-test"},
        },
    )
    monkeypatch.setattr(settings, "proxy_openai_keys", {str(project_id): "sk-openai-test"})

    assert provider_key_for_project(project_id, "anthropic") == "sk-ant-test"
    assert provider_key_for_project(project_id, "gemini") == "AIza-gemini-test"
    assert provider_key_for_project(project_id, "openai") == "sk-openai-test"


def test_provider_key_cache_clear_invalidates_one_provider():
    calls = {"n": 0}
    project_id = uuid.uuid4()

    def fetcher(project_id: uuid.UUID, provider: str) -> str:
        calls["n"] += 1
        return f"{provider}-{calls['n']}"

    cache = ProviderKeyCache(fetcher=fetcher, ttl_seconds=300)

    assert cache.get(project_id, "anthropic") == "anthropic-1"
    assert cache.get(project_id, "anthropic") == "anthropic-1"
    assert calls["n"] == 1

    cache.clear(project_id, "anthropic")

    assert cache.get(project_id, "anthropic") == "anthropic-2"
    assert calls["n"] == 2


def test_env_provider_key_store_is_explicitly_unsupported(monkeypatch):
    monkeypatch.setattr(settings, "provider_key_backend", "env")

    with pytest.raises(ProviderKeyStoreUnsupported):
        store_provider_key_for_project(uuid.uuid4(), "openai", "sk-test")


def test_env_provider_key_delete_is_explicitly_unsupported(monkeypatch):
    monkeypatch.setattr(settings, "provider_key_backend", "env")

    with pytest.raises(ProviderKeyStoreUnsupported):
        delete_provider_key_for_project(uuid.uuid4(), "openai")


def test_localdb_provider_key_resolver_falls_back_to_env_when_no_connection(monkeypatch):
    project_id = uuid.uuid4()
    monkeypatch.setattr(settings, "provider_key_backend", "localdb")
    monkeypatch.setattr(settings, "proxy_openai_keys", {str(project_id): "sk-openai-test"})

    assert provider_key_for_project(project_id, "openai") == "sk-openai-test"


def test_secrets_manager_resolver_reads_json_secret(monkeypatch):
    project_id = uuid.uuid4()
    fake = FakeSecretsManager()
    monkeypatch.setattr(settings, "provider_key_secret_prefix", "varsten")
    monkeypatch.setattr(settings, "provider_key_secret_environment", "test")
    resolver = SecretsManagerProviderKeyResolver(client=fake)
    name = resolver.secret_name(project_id, "Anthropic")
    fake.secrets[name] = json.dumps({"api_key": "sk-ant-secret"})

    assert resolver.get(project_id, "anthropic") == "sk-ant-secret"
    assert resolver.get(project_id, "gemini") is None


def test_secrets_manager_resolver_creates_and_rotates_secret(monkeypatch):
    project_id = uuid.uuid4()
    fake = FakeSecretsManager()
    monkeypatch.setattr(settings, "provider_key_secret_prefix", "varsten")
    monkeypatch.setattr(settings, "provider_key_secret_environment", "test")
    monkeypatch.setattr(settings, "provider_key_kms_key_id", "arn:aws:kms:us-east-1:123456789012:key/test")
    resolver = SecretsManagerProviderKeyResolver(client=fake)

    name = resolver.store(project_id, "gemini", "AIza-first")
    assert fake.created == [name]
    assert fake.create_requests == [
        {
            "Name": name,
            "KmsKeyId": "arn:aws:kms:us-east-1:123456789012:key/test",
            "Tags": [
                {"Key": "VarstenDataClass", "Value": "provider-key"},
                {"Key": "VarstenProjectId", "Value": str(project_id)},
                {"Key": "VarstenProvider", "Value": "gemini"},
                {"Key": "Environment", "Value": "test"},
            ],
        }
    ]
    assert json.loads(fake.secrets[name]) == {"api_key": "AIza-first"}

    assert resolver.store(project_id, "gemini", "AIza-second") == name
    assert fake.updated == [name]
    assert json.loads(fake.secrets[name]) == {"api_key": "AIza-second"}


def test_secrets_manager_resolver_deletes_secret(monkeypatch):
    project_id = uuid.uuid4()
    fake = FakeSecretsManager()
    monkeypatch.setattr(settings, "provider_key_secret_prefix", "varsten")
    monkeypatch.setattr(settings, "provider_key_secret_environment", "test")
    resolver = SecretsManagerProviderKeyResolver(client=fake)

    name = resolver.store(project_id, "anthropic", "sk-ant")
    resolver.delete(project_id, "anthropic")

    assert fake.deleted == [name]
    assert name not in fake.secrets


def test_secrets_manager_resolver_delete_is_idempotent_when_secret_is_missing(monkeypatch):
    project_id = uuid.uuid4()
    fake = FakeSecretsManager()
    monkeypatch.setattr(settings, "provider_key_secret_prefix", "varsten")
    monkeypatch.setattr(settings, "provider_key_secret_environment", "test")
    resolver = SecretsManagerProviderKeyResolver(client=fake)

    resolver.delete(project_id, "gemini")

    assert fake.deleted == []
