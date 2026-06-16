"""Provider-key validation: status mapping + connect-endpoint integration."""

import httpx

from app.api.v1 import product_sections
from app.core.config import settings
from app.proxy import provider_validation
from app.proxy.provider_validation import ValidationResult, validate_provider_key
from tests.conftest import auth_headers


def _enable(monkeypatch):
    monkeypatch.setattr(settings, "provider_key_validation_enabled", True)


def test_validation_ok_on_200(monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setattr(provider_validation, "_probe", lambda p, k: httpx.Response(200, json={"data": []}))
    assert validate_provider_key("openai", "sk-good").ok is True


def test_validation_rejects_on_401(monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setattr(provider_validation, "_probe", lambda p, k: httpx.Response(401, json={"error": "bad"}))
    result = validate_provider_key("openai", "sk-bad")
    assert result.ok is False
    assert "rejected" in (result.message or "").lower()


def test_validation_soft_fails_on_500(monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setattr(provider_validation, "_probe", lambda p, k: httpx.Response(500))
    assert validate_provider_key("openai", "sk-x").ok is False


def test_validation_soft_fails_on_network_error(monkeypatch):
    _enable(monkeypatch)

    def boom(p, k):
        raise httpx.ConnectError("unreachable")

    monkeypatch.setattr(provider_validation, "_probe", boom)
    result = validate_provider_key("openai", "sk-x")
    assert result.ok is False
    assert "reach" in (result.message or "").lower()


def test_validation_disabled_passes(monkeypatch):
    monkeypatch.setattr(settings, "provider_key_validation_enabled", False)
    assert validate_provider_key("openai", "anything").ok is True


def _path(project_id: str, provider: str) -> str:
    return f"/v1/admin/connections/{provider}?project_id={project_id}"


def test_connect_rejects_invalid_key_without_storing(client, provision, db_session, monkeypatch):
    ws = provision(sub="auth0|val-bad", email="valbad@example.com")

    def fail_if_called(*a, **k):  # store must not run for an invalid key
        raise AssertionError("store_provider_key_for_project should not be called")

    monkeypatch.setattr(product_sections, "store_provider_key_for_project", fail_if_called)
    monkeypatch.setattr(
        product_sections, "validate_provider_key", lambda p, k: ValidationResult(False, "The provider rejected this key.")
    )

    resp = client.put(_path(ws["project_id"], "openai"), headers=auth_headers(ws["token"]), json={"api_key": "sk-bad"})
    assert resp.status_code == 422
    assert "rejected" in resp.json()["detail"].lower()


def test_connect_stores_valid_key(client, provision, db_session, monkeypatch):
    ws = provision(sub="auth0|val-ok", email="valok@example.com")
    monkeypatch.setattr(
        product_sections,
        "store_provider_key_for_project",
        lambda pid, provider, key: f"varsten/test/provider-keys/{pid}/{provider}",
    )
    monkeypatch.setattr(product_sections, "validate_provider_key", lambda p, k: ValidationResult(True, None))

    resp = client.put(_path(ws["project_id"], "openai"), headers=auth_headers(ws["token"]), json={"api_key": "sk-good"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "connected"
