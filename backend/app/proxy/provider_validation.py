"""Validate a provider API key with a cheap authenticated probe.

Run at connect time, before the key is stored, so a bad key fails immediately with
a clear message instead of failing every proxied request later. The probe is a
read-only list call (no spend). It is a synchronous one-off (the connect endpoint
runs on the sync stack), short-timed, and total: any transport error becomes a
"could not validate" result, never an exception into the request.
"""

from dataclasses import dataclass

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("varsten.proxy.provider_validation")

SUPPORTED_PROVIDERS = ("openai", "anthropic", "gemini")


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    message: str | None = None


def _probe(provider: str, api_key: str) -> httpx.Response:
    timeout = settings.provider_key_validation_timeout_seconds
    if provider == "openai":
        url = f"{settings.openai_base_url.rstrip('/')}/v1/models"
        return httpx.get(url, headers={"Authorization": f"Bearer {api_key}"}, timeout=timeout)
    if provider == "anthropic":
        url = f"{settings.anthropic_base_url.rstrip('/')}/v1/models"
        headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
        return httpx.get(url, headers=headers, timeout=timeout)
    # gemini
    url = f"{settings.gemini_base_url.rstrip('/')}/v1beta/models"
    return httpx.get(url, params={"key": api_key}, timeout=timeout)


def validate_provider_key(provider: str, api_key: str) -> ValidationResult:
    """Probe the provider with the key. ok=True only on a clear success; a clear
    rejection (401/403) is a hard failure; anything else is "could not validate"
    (also ok=False, but with a retry-friendly message)."""
    provider = provider.strip().lower()
    if not settings.provider_key_validation_enabled:
        return ValidationResult(True, None)
    if provider not in SUPPORTED_PROVIDERS:
        return ValidationResult(False, "unsupported provider")
    if not api_key:
        return ValidationResult(False, "missing api key")
    try:
        resp = _probe(provider, api_key)
    except httpx.RequestError:
        logger.warning("provider key validation could not reach provider", extra={"provider": provider})
        return ValidationResult(False, "Could not reach the provider to validate this key. Try again.")
    if resp.status_code == 200:
        return ValidationResult(True, None)
    if resp.status_code in (401, 403):
        return ValidationResult(False, "The provider rejected this key. Check that it is correct and active.")
    return ValidationResult(False, f"The provider returned status {resp.status_code} while validating this key.")
