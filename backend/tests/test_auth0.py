"""Offline tests for Auth0 access-token validation.

Generates a local RS256 keypair and injects the public key in place of the
tenant JWKS, so the full verify path (signature, issuer, audience, expiry) is
exercised without any network access or a live Auth0 tenant.
"""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.auth import auth0
from app.auth.auth0 import Auth0NotConfigured, verify_access_token
from app.core.config import settings

DOMAIN = "varsten-test.us.auth0.com"
AUDIENCE = "https://api.varsten.test"
ISSUER = f"https://{DOMAIN}/"


@pytest.fixture(scope="module")
def keypair():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def other_keypair():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(autouse=True)
def configure_and_inject(monkeypatch, keypair):
    monkeypatch.setattr(settings, "auth0_domain", DOMAIN)
    monkeypatch.setattr(settings, "auth0_audience", AUDIENCE)
    # Replace the JWKS lookup with our local public key.
    monkeypatch.setattr(auth0, "_signing_key", lambda token: keypair.public_key())


def make_token(keypair, **overrides) -> str:
    now = datetime.now(tz=UTC)
    payload = {
        "sub": "auth0|abc123",
        "aud": AUDIENCE,
        "iss": ISSUER,
        "iat": now,
        "exp": now + timedelta(hours=1),
    }
    payload.update(overrides)
    return jwt.encode(payload, keypair, algorithm="RS256")


def test_valid_token_returns_claims(keypair):
    claims = verify_access_token(make_token(keypair))
    assert claims["sub"] == "auth0|abc123"
    assert claims["aud"] == AUDIENCE


def test_expired_token_rejected(keypair):
    now = datetime.now(tz=UTC)
    token = make_token(keypair, iat=now - timedelta(hours=2), exp=now - timedelta(hours=1))
    with pytest.raises(jwt.ExpiredSignatureError):
        verify_access_token(token)


def test_wrong_audience_rejected(keypair):
    token = make_token(keypair, aud="https://api.someone-else.test")
    with pytest.raises(jwt.InvalidAudienceError):
        verify_access_token(token)


def test_wrong_issuer_rejected(keypair):
    token = make_token(keypair, iss="https://evil.example.com/")
    with pytest.raises(jwt.InvalidIssuerError):
        verify_access_token(token)


def test_bad_signature_rejected(other_keypair):
    # Signed by a key whose public half is not the one we trust.
    token = make_token(other_keypair)
    with pytest.raises(jwt.InvalidSignatureError):
        verify_access_token(token)


def test_unconfigured_raises(monkeypatch, keypair):
    monkeypatch.setattr(settings, "auth0_domain", "")
    with pytest.raises(Auth0NotConfigured):
        verify_access_token(make_token(keypair))
