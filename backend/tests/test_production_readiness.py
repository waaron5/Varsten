"""Production self-checks: config validation and the readiness probe.

These guard the boot-time contract that a production deploy is not allowed to run
on dev-safe defaults (no auth, env-vaulted keys, localhost CORS, no Sentry), and
that orchestration can tell a healthy instance from one that cannot reach the DB.
"""

import pytest

from app.core.config import Settings, assert_production_ready, validate_production


def _prod_settings(**overrides) -> Settings:
    base = {
        "database_url": "postgresql+psycopg://u:p@db:5432/varsten",
        "app_env": "production",
        "auth0_domain": "varsten.us.auth0.com",
        "auth0_audience": "https://api.varsten.ai",
        "provider_key_backend": "secretsmanager",
        "provider_key_aws_region": "us-east-1",
        "cors_origins": ["https://app.varsten.ai"],
        "sentry_dsn": "https://examplePublicKey@o0.ingest.sentry.io/0",
    }
    base.update(overrides)
    return Settings(**base)


def test_fully_configured_production_settings_pass():
    assert validate_production(_prod_settings()) == []
    # Does not raise.
    assert_production_ready(_prod_settings())


def test_missing_auth_is_flagged():
    problems = validate_production(_prod_settings(auth0_domain="", auth0_audience=""))
    assert any("AUTH0" in p for p in problems)


def test_env_vaulted_keys_rejected_in_production():
    problems = validate_production(_prod_settings(provider_key_backend="env"))
    assert any("PROVIDER_KEY_BACKEND" in p for p in problems)


def test_secretsmanager_without_region_flagged():
    problems = validate_production(_prod_settings(provider_key_aws_region=""))
    assert any("PROVIDER_KEY_AWS_REGION" in p for p in problems)


def test_localhost_cors_rejected_in_production():
    problems = validate_production(_prod_settings(cors_origins=["https://app.varsten.ai", "http://localhost:3000"]))
    assert any("CORS_ORIGINS" in p and "localhost" in p for p in problems)


def test_missing_sentry_flagged():
    problems = validate_production(_prod_settings(sentry_dsn=""))
    assert any("SENTRY_DSN" in p for p in problems)


def test_assert_raises_on_bad_production_config():
    bad = _prod_settings(auth0_domain="", auth0_audience="", provider_key_backend="env")
    with pytest.raises(RuntimeError) as exc:
        assert_production_ready(bad)
    assert "production-ready" in str(exc.value)


def test_non_production_env_skips_checks():
    # A development deploy with dev-safe defaults must never be blocked.
    dev = Settings(database_url="postgresql+psycopg://u:p@localhost:5432/varsten", app_env="development")
    assert_production_ready(dev)  # no raise


def test_readiness_probe_ok(client):
    resp = client.get("/health/ready")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "database": "ok"}


def test_liveness_probe_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
