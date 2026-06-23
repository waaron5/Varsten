import uuid

from sqlalchemy import select

from app.api.v1 import product_sections
from app.api.v1 import projects as project_routes
from app.models import ProviderConnection
from app.proxy.keys import ProviderKeyStoreUnsupported


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _admin_connection_path(project_id: str, provider: str) -> str:
    return f"/v1/admin/connections/{provider}?project_id={project_id}"


def _project_connection_path(project_id: str) -> str:
    return f"/v1/projects/{project_id}/connections"


def test_admin_provider_connection_upsert_vaults_key_without_returning_secret(
    client,
    db_session,
    provision,
    monkeypatch,
):
    ws = provision(sub="auth0|provider-owner", email="provider-owner@example.com")
    calls: list[tuple[str, str, str]] = []

    def store_key(project_id: uuid.UUID, provider: str, api_key: str) -> str:
        calls.append((str(project_id), provider, api_key))
        return f"varsten/test/provider-keys/{project_id}/{provider}"

    monkeypatch.setattr(product_sections, "store_provider_key_for_project", store_key)

    res = client.put(
        _admin_connection_path(ws["project_id"], "anthropic"),
        headers=_bearer(ws["token"]),
        json={"api_key": "sk-ant-test"},
    )

    assert res.status_code == 200
    body = res.json()
    assert body["provider"] == "anthropic"
    assert body["connection_method"] == "secrets_manager"
    assert body["status"] == "connected"
    assert body["key_vaulted"] is True
    assert body["last_verified_at"] is not None
    assert "api_key" not in body
    assert "secret_ref" not in body
    assert calls == [(ws["project_id"], "anthropic", "sk-ant-test")]

    connection = db_session.scalar(
        select(ProviderConnection).where(
            ProviderConnection.project_id == uuid.UUID(ws["project_id"]),
            ProviderConnection.provider == "anthropic",
        )
    )
    assert connection is not None
    assert connection.secret_ref == f"varsten/test/provider-keys/{ws['project_id']}/anthropic"
    assert connection.last_error is None


def test_project_provider_connection_endpoint_vaults_key_without_returning_secret(
    client,
    provision,
    monkeypatch,
):
    ws = provision(sub="auth0|project-provider-owner", email="project-provider-owner@example.com")
    calls: list[tuple[str, str, str]] = []

    def store_key(project_id: uuid.UUID, provider: str, api_key: str) -> str:
        calls.append((str(project_id), provider, api_key))
        return f"varsten/test/provider-keys/{project_id}/{provider}"

    monkeypatch.setattr(project_routes, "store_provider_key_for_project", store_key)

    res = client.post(
        _project_connection_path(ws["project_id"]),
        headers=_bearer(ws["token"]),
        json={"provider": "gemini", "api_key": "AIza-test"},
    )

    assert res.status_code == 200
    body = res.json()
    assert body["provider"] == "gemini"
    assert body["status"] == "connected"
    assert body["key_vaulted"] is True
    assert "api_key" not in body
    assert "secret_ref" not in body
    assert calls == [(ws["project_id"], "gemini", "AIza-test")]


def test_project_provider_connection_reports_manual_setup_capability(
    client,
    provision,
    monkeypatch,
):
    ws = provision(sub="auth0|project-provider-manual", email="project-provider-manual@example.com")

    def reject_store(project_id: uuid.UUID, provider: str, api_key: str) -> str:
        raise ProviderKeyStoreUnsupported("Manual setup required.", backend="env")

    monkeypatch.setattr(project_routes, "store_provider_key_for_project", reject_store)

    res = client.post(
        _project_connection_path(ws["project_id"]),
        headers=_bearer(ws["token"]),
        json={"provider": "openai", "api_key": "sk-test"},
    )

    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "provider_key_storage_unavailable"
    assert res.json()["detail"]["backend"] == "env"


def test_admin_provider_connection_rejects_unsupported_provider(client, provision, monkeypatch):
    ws = provision(sub="auth0|provider-reject", email="provider-reject@example.com")

    def fail_if_called(project_id: uuid.UUID, provider: str, api_key: str) -> str:
        raise AssertionError("unsupported providers must not reach the vault")

    monkeypatch.setattr(product_sections, "store_provider_key_for_project", fail_if_called)

    res = client.put(
        _admin_connection_path(ws["project_id"], "bedrock"),
        headers=_bearer(ws["token"]),
        json={"api_key": "sk-test"},
    )

    assert res.status_code == 422


def test_admin_provider_connection_disconnect_deletes_key_and_clears_metadata(
    client,
    db_session,
    provision,
    monkeypatch,
):
    ws = provision(sub="auth0|provider-disconnect", email="provider-disconnect@example.com")
    stored: list[tuple[str, str, str]] = []
    deleted: list[tuple[str, str]] = []

    def store_key(project_id: uuid.UUID, provider: str, api_key: str) -> str:
        stored.append((str(project_id), provider, api_key))
        return f"varsten/test/provider-keys/{project_id}/{provider}"

    def delete_key(project_id: uuid.UUID, provider: str) -> None:
        deleted.append((str(project_id), provider))

    monkeypatch.setattr(product_sections, "store_provider_key_for_project", store_key)
    monkeypatch.setattr(product_sections, "delete_provider_key_for_project", delete_key)

    put = client.put(
        _admin_connection_path(ws["project_id"], "gemini"),
        headers=_bearer(ws["token"]),
        json={"api_key": "AIza-test"},
    )
    assert put.status_code == 200
    assert put.json()["status"] == "connected"

    res = client.delete(_admin_connection_path(ws["project_id"], "gemini"), headers=_bearer(ws["token"]))

    assert res.status_code == 200
    body = res.json()
    assert body["provider"] == "gemini"
    assert body["status"] == "not_connected"
    assert body["key_vaulted"] is False
    assert body["last_verified_at"] is None
    assert "api_key" not in body
    assert "secret_ref" not in body
    assert stored == [(ws["project_id"], "gemini", "AIza-test")]
    assert deleted == [(ws["project_id"], "gemini")]

    connection = db_session.scalar(
        select(ProviderConnection).where(
            ProviderConnection.project_id == uuid.UUID(ws["project_id"]),
            ProviderConnection.provider == "gemini",
        )
    )
    assert connection is not None
    assert connection.status == "not_connected"
    assert connection.secret_ref is None
    assert connection.last_verified_at is None
    assert connection.last_error is None


def test_admin_provider_connection_disconnect_rejects_ingestion_api_key(client, provision, monkeypatch):
    ws = provision(sub="auth0|provider-delete-api-key", email="provider-delete-api-key@example.com")

    def fail_if_called(project_id: uuid.UUID, provider: str) -> None:
        raise AssertionError("ingestion api keys must not delete provider secrets")

    monkeypatch.setattr(product_sections, "delete_provider_key_for_project", fail_if_called)

    res = client.delete(
        f"/v1/admin/connections/openai?project_id={ws['project_id']}",
        headers=_bearer(ws["api_key"]),
    )

    assert res.status_code == 401


def test_admin_provider_connection_disconnect_reports_unwritable_key_backend(client, provision, monkeypatch):
    ws = provision(sub="auth0|provider-delete-env", email="provider-delete-env@example.com")

    def reject_delete(project_id: uuid.UUID, provider: str) -> None:
        raise ProviderKeyStoreUnsupported("provider key deletes require provider_key_backend='secretsmanager'")

    monkeypatch.setattr(product_sections, "delete_provider_key_for_project", reject_delete)

    res = client.delete(_admin_connection_path(ws["project_id"], "openai"), headers=_bearer(ws["token"]))

    assert res.status_code == 400
    assert "secretsmanager" in res.json()["detail"]


def test_admin_provider_connection_disconnect_persists_delete_failure_status(
    client,
    db_session,
    provision,
    monkeypatch,
):
    ws = provision(sub="auth0|provider-delete-fail", email="provider-delete-fail@example.com")

    def fail_delete(project_id: uuid.UUID, provider: str) -> None:
        raise RuntimeError("kms unavailable")

    monkeypatch.setattr(product_sections, "delete_provider_key_for_project", fail_delete)

    res = client.delete(_admin_connection_path(ws["project_id"], "anthropic"), headers=_bearer(ws["token"]))

    assert res.status_code == 502
    connection = db_session.scalar(
        select(ProviderConnection).where(
            ProviderConnection.project_id == uuid.UUID(ws["project_id"]),
            ProviderConnection.provider == "anthropic",
        )
    )
    assert connection is not None
    assert connection.status == "error"
    assert connection.last_error == "provider key delete failed"


def test_admin_provider_connection_rejects_ingestion_api_key(client, provision, monkeypatch):
    ws = provision(sub="auth0|provider-api-key", email="provider-api-key@example.com")

    def fail_if_called(project_id: uuid.UUID, provider: str, api_key: str) -> str:
        raise AssertionError("ingestion api keys must not write provider secrets")

    monkeypatch.setattr(product_sections, "store_provider_key_for_project", fail_if_called)

    res = client.put(
        f"/v1/admin/connections/openai?project_id={ws['project_id']}",
        headers=_bearer(ws["api_key"]),
        json={"api_key": "sk-test"},
    )

    assert res.status_code == 401


def test_admin_provider_connection_reports_unwritable_key_backend(client, provision, monkeypatch):
    ws = provision(sub="auth0|provider-env", email="provider-env@example.com")

    def reject_store(project_id: uuid.UUID, provider: str, api_key: str) -> str:
        raise ProviderKeyStoreUnsupported("provider key writes require provider_key_backend='secretsmanager'")

    monkeypatch.setattr(product_sections, "store_provider_key_for_project", reject_store)

    res = client.put(
        _admin_connection_path(ws["project_id"], "openai"),
        headers=_bearer(ws["token"]),
        json={"api_key": "sk-test"},
    )

    assert res.status_code == 400
    assert "secretsmanager" in res.json()["detail"]


def test_admin_provider_connection_persists_store_failure_status(client, db_session, provision, monkeypatch):
    ws = provision(sub="auth0|provider-fail", email="provider-fail@example.com")

    def fail_store(project_id: uuid.UUID, provider: str, api_key: str) -> str:
        raise RuntimeError("kms unavailable")

    monkeypatch.setattr(product_sections, "store_provider_key_for_project", fail_store)

    res = client.put(
        _admin_connection_path(ws["project_id"], "gemini"),
        headers=_bearer(ws["token"]),
        json={"api_key": "AIza-test"},
    )

    assert res.status_code == 502
    connection = db_session.scalar(
        select(ProviderConnection).where(
            ProviderConnection.project_id == uuid.UUID(ws["project_id"]),
            ProviderConnection.provider == "gemini",
        )
    )
    assert connection is not None
    assert connection.status == "error"
    assert connection.last_error == "provider key store failed"
    assert connection.secret_ref is None
