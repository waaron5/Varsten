"""Response-origin contract for the fail-open SDK.

Every response the proxy emits declares whether Varsten generated it or relayed a
provider result, via the ``X-Varsten-Origin`` header (and an ``origin`` field on
structured errors). A client SDK uses this to tell a Varsten-originated failure
(safe to fall back directly to the provider) from a faithfully relayed provider
error (must not retry, or it double-bills and hits the same sick provider).

The rule the SDK relies on:

- ``varsten`` + a failure status  -> fall back to the provider directly.
- ``provider`` (success or error) -> never fall back; the provider already answered.
- a header-less 5xx                -> treat as ``varsten`` (Varsten misbehaved).

Frozen in docs/design/SDK_FAILOPEN_DESIGN_FREEZE.md. Codes are a versioned
contract: changes are additive, existing codes never change meaning.
"""

from fastapi.responses import JSONResponse

ORIGIN_HEADER = "X-Varsten-Origin"
ORIGIN_VARSTEN = "varsten"
ORIGIN_PROVIDER = "provider"

# Stable machine codes the SDK switches on, decoupled from the prose ``message``.
CODE_CIRCUIT_OPEN = "circuit_open"
CODE_RATE_LIMITED = "rate_limited"
CODE_BUDGET_EXCEEDED = "budget_exceeded"
CODE_UPSTREAM_UNREACHABLE = "upstream_unreachable"
CODE_NO_PROVIDER_KEY = "no_provider_key"
CODE_INTERNAL_ERROR = "internal_error"


def with_provider_origin(headers: dict[str, str] | None = None) -> dict[str, str]:
    """A response-header dict tagged as a faithfully relayed provider result."""
    out = dict(headers or {})
    out[ORIGIN_HEADER] = ORIGIN_PROVIDER
    return out


def with_varsten_origin(headers: dict[str, str] | None = None) -> dict[str, str]:
    """A response-header dict tagged as Varsten-generated. Origin is forced last so
    a provider-origin base dict (e.g. the shared success headers) cannot win."""
    out = dict(headers or {})
    out[ORIGIN_HEADER] = ORIGIN_VARSTEN
    return out


def varsten_error(
    *,
    code: str,
    type_: str,
    message: str,
    status_code: int,
    extra_body: dict | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """A Varsten-originated error in the frozen schema, tagged origin=varsten.

    ``type_`` keeps the existing ``varsten_*`` strings for backward compatibility;
    ``code`` is the stable machine token the SDK switches on.
    """
    error = {"message": message, "type": type_, "code": code, "origin": ORIGIN_VARSTEN}
    if extra_body:
        error.update(extra_body)
    return JSONResponse({"error": error}, status_code=status_code, headers=with_varsten_origin(headers))
