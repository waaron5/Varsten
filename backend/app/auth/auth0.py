"""Auth0 access-token validation.

Validates RS256 JWTs issued by the configured Auth0 tenant for our API audience,
verifying signature (via the tenant JWKS), issuer, audience, and expiry.
"""

from functools import lru_cache

import jwt
from jwt import PyJWKClient

from app.core.config import settings


class Auth0NotConfigured(Exception):
    """Raised when Auth0 settings are missing, so the caller can return 503."""


@lru_cache(maxsize=1)
def _jwks_client() -> PyJWKClient:
    # Cached: the JWKS client keeps its own short-lived key cache and only
    # refetches when it sees an unknown key id.
    return PyJWKClient(f"https://{settings.auth0_domain}/.well-known/jwks.json")


def _signing_key(token: str):
    # Seam for tests to inject a local public key without network access.
    return _jwks_client().get_signing_key_from_jwt(token).key


def verify_access_token(token: str) -> dict:
    """Return the validated claims, or raise.

    Raises Auth0NotConfigured if the tenant is unset, or jwt.PyJWTError
    (InvalidSignatureError, ExpiredSignatureError, InvalidAudienceError,
    InvalidIssuerError, ...) for an invalid token.
    """
    if not settings.auth0_domain or not settings.auth0_audience:
        raise Auth0NotConfigured("AUTH0_DOMAIN and AUTH0_AUDIENCE must be set")

    signing_key = _signing_key(token)
    return jwt.decode(
        token,
        signing_key,
        algorithms=["RS256"],
        audience=settings.auth0_audience,
        issuer=f"https://{settings.auth0_domain}/",
    )
