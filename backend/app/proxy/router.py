"""Inline proxy: SDK-compatible AI provider mirror.

POST /v1/chat/completions
  - authenticate with the vk_ key, resolve the project's upstream provider key
  - on a semantic-cache hit, serve the stored completion ($0, no upstream call)
  - on a miss, stream the upstream response straight through (SSE preserved) while
    capturing token/billing metadata in volatile memory, then write the ledger
    row and (optionally) cache the result
"""

import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from typing import NamedTuple

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ApiKeyContext, require_api_key_context_async
from app.auth.entitlements import EntitlementState, entitlement_state_async
from app.core import ratelimit
from app.core.config import settings
from app.core.logging import get_logger, request_id_ctx
from app.db.session import get_async_db
from app.eval import capture as eval_capture
from app.models import Project
from app.proxy import budget_enforcement, cache, http_client, origin, quality, routing, trim
from app.proxy.circuit import get_breaker, is_upstream_failure
from app.proxy.client_dialects import (
    ClientDialect,
    ParsedClientRequest,
    UnsupportedClientDialect,
    classify_client_dialect,
)
from app.proxy.client_transforms import (
    render_completion_for_client,
    request_to_openai_shape,
    stream_renderer_for_client,
)
from app.proxy.embedding import embed, embedding_input
from app.proxy.evidence import DecisionDraft, record_request_decision
from app.proxy.keys import provider_key_for_project
from app.proxy.ledger import record_proxy_usage
from app.proxy.optimization_decisions import record_ineligible_decision_async
from app.proxy.providers import canonical, get_adapter
from app.proxy.request_context import parse_request_context
from app.proxy.routing_eligibility import cross_provider_ineligibility

router = APIRouter(tags=["proxy"])
beta_router = APIRouter(prefix="/v1beta", tags=["proxy"])
logger = get_logger("varsten.proxy")

SSE_MEDIA_TYPE = "text/event-stream"


@router.get("/health")
async def proxy_health() -> dict:
    """Liveness for the fail-open SDK's recovery probe and the onboarding connection
    test. Co-located under /v1 so the SDK can probe its own base URL. Touches no
    database, so a brief Postgres blip never flips this unhealthy and the SDK keeps
    treating Varsten as reachable for the optimized path."""
    return {"ok": True}


class OpenAICacheProbe(NamedTuple):
    response: Response | None
    embedding: list[float] | None


class OpenAIOptimizationState(NamedTuple):
    body: dict
    upstream_model: str
    upstream_provider: str
    routed_from: str | None
    routed_from_provider: str | None
    arm: str | None
    exp_from: str | None
    exp_to: str | None
    trim_applied: bool


def _is_bypassed(project: Project) -> bool:
    """The kill switch: global (operator) OR per-project (customer). When engaged,
    Varsten forwards straight through with no optimization, still metered."""
    return settings.proxy_kill_switch or project.proxy_bypass_enabled


def _rate_limited(api_key_id) -> JSONResponse | None:
    """Per-API-key fixed-window limit on the public proxy. Fail-open: returns a 429
    JSONResponse when over the limit, else None. Cheap enough for the hot path."""
    if not settings.rate_limit_enabled:
        return None
    if ratelimit.allow(f"proxy:{api_key_id}", settings.proxy_rate_limit_per_minute):
        return None
    return origin.varsten_error(
        code=origin.CODE_RATE_LIMITED,
        type_="varsten_rate_limited",
        message="rate limit exceeded",
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        headers={"Retry-After": "60", "X-Varsten-RateLimit": "exceeded"},
    )


async def _resolve_entitlement_state(db: AsyncSession, organization_id) -> EntitlementState:
    try:
        state = await entitlement_state_async(db, organization_id)
        legacy_observe_only = await observe_only_async(db, organization_id)
        if legacy_observe_only != state.observe_only:
            return state._replace(observe_only=legacy_observe_only)
        return state
    except Exception:
        logger.exception("entitlement lookup failed; treating as observe-only")
        return EntitlementState(
            plan_tier="free",
            observe_only=True,
            reason="entitlement_lookup_failed",
            monthly_requests=0,
            monthly_request_limit=settings.free_monthly_request_limit,
            requests_remaining=None,
            trial_ends_at=None,
            trial_expired=False,
        )


async def observe_only_async(db: AsyncSession, organization_id) -> bool:
    return (await entitlement_state_async(db, organization_id)).observe_only


def _entitlement_headers(state: EntitlementState) -> dict[str, str]:
    headers = {
        "X-Varsten-Observe-Only": "true" if state.observe_only else "false",
        "X-Varsten-Monthly-Requests": str(state.monthly_requests),
        "X-Varsten-Monthly-Request-Limit": str(state.monthly_request_limit),
    }
    if state.reason:
        headers["X-Varsten-Observe-Only-Reason"] = state.reason
    if state.requests_remaining is not None:
        headers["X-Varsten-Requests-Remaining"] = str(state.requests_remaining)
    if state.trial_ends_at is not None:
        headers["X-Varsten-Trial-Ends-At"] = state.trial_ends_at.isoformat()
    return headers


def _bypass_reason(project: Project) -> str:
    """Why a bypassed request was bypassed, for the decision-evidence record."""
    if settings.proxy_kill_switch:
        return "kill_switch"
    if project.proxy_bypass_enabled:
        return "project_bypass"
    return "unknown"


async def _budget_block(db: AsyncSession, project: Project, ctx, request_id: str) -> JSONResponse | None:
    """Block this forward when the request's workload owner is over a hard cap.

    Only called on the paid forward path (cache hits are already served), and only
    for optimization-enabled traffic. Fail-open lives in exhausted_hard_caps."""
    exhausted = await budget_enforcement.exhausted_hard_caps(db, project.id)
    cap = budget_enforcement.matched_cap(exhausted, ctx)
    if cap is None:
        return None
    owner_type, owner_key = cap
    logger.warning(
        "hard budget cap exceeded; blocking request",
        extra={"project_id": str(project.id), "owner_type": owner_type, "owner_key": owner_key},
    )
    return origin.varsten_error(
        code=origin.CODE_BUDGET_EXCEEDED,
        type_="varsten_budget_exceeded",
        message=f"hard budget cap exceeded for {owner_type} '{owner_key}'",
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        extra_body={"owner_type": owner_type, "owner_key": owner_key},
        headers={"X-Varsten-Budget": "exceeded", "X-Varsten-Request-Id": request_id},
    )


@router.post("/chat/completions")
async def chat_completions(
    request: Request,
    background_tasks: BackgroundTasks,
    api_context: ApiKeyContext = Depends(require_api_key_context_async),
    db: AsyncSession = Depends(get_async_db),
):
    return await _openai_dialect_completions(request, background_tasks, api_context, db)


@router.post("/openai/chat/completions")
async def gemini_v1_openai_chat_completions(
    request: Request,
    background_tasks: BackgroundTasks,
    api_context: ApiKeyContext = Depends(require_api_key_context_async),
    db: AsyncSession = Depends(get_async_db),
):
    return await _openai_dialect_completions(request, background_tasks, api_context, db, destination_provider="gemini")


@beta_router.post("/openai/chat/completions")
async def gemini_beta_openai_chat_completions(
    request: Request,
    background_tasks: BackgroundTasks,
    api_context: ApiKeyContext = Depends(require_api_key_context_async),
    db: AsyncSession = Depends(get_async_db),
):
    return await _openai_dialect_completions(request, background_tasks, api_context, db, destination_provider="gemini")


@router.post("/messages")
@router.post("/messages/count_tokens")
@router.post("/messages/batches")
async def anthropic_native(
    request: Request,
    api_context: ApiKeyContext = Depends(require_api_key_context_async),
    db: AsyncSession = Depends(get_async_db),
):
    return await _native_provider_passthrough(request, api_context, db, "anthropic", ClientDialect.ANTHROPIC)


@beta_router.post("/models/{model_action:path}")
@beta_router.post("/batches")
async def gemini_native(
    request: Request,
    api_context: ApiKeyContext = Depends(require_api_key_context_async),
    db: AsyncSession = Depends(get_async_db),
):
    return await _native_provider_passthrough(request, api_context, db, "gemini", ClientDialect.GEMINI_NATIVE)


async def _openai_dialect_completions(
    request: Request,
    background_tasks: BackgroundTasks,
    api_context: ApiKeyContext,
    db: AsyncSession,
    *,
    destination_provider: str | None = None,
):
    project = api_context.project
    api_key_id = api_context.api_key.id
    limited = _rate_limited(api_key_id)
    if limited is not None:
        return limited
    # Request receipt, for per-event latency (time-to-first-byte from the proxy's
    # view): the moment a cached payload is ready, or the upstream's response /
    # first stream chunk arrives. This is the latency a buyer feels.
    started = time.perf_counter()

    parsed = await _parse_client_request(request)
    if parsed.dialect != ClientDialect.OPENAI or parsed.operation != "chat_completions":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="unsupported proxy operation")

    # The upstream provider is resolved through the adapter registry. Future
    # routing policy selects this per-request; the router below stays provider-agnostic.
    adapter = get_adapter(destination_provider or settings.proxy_default_provider)

    client_key = provider_key_for_project(project.id, adapter.provider)
    if not client_key:
        return origin.varsten_error(
            code=origin.CODE_NO_PROVIDER_KEY,
            type_="varsten_no_provider_key",
            message="no provider key configured for this project",
            status_code=status.HTTP_502_BAD_GATEWAY,
        )

    body = parsed.body
    stream = parsed.stream
    model = parsed.model or ""
    bypass = _is_bypassed(project)
    # Observe-only (Free): meter and record, but never change behaviour — no cache
    # serve/store, no routing, no trim. Distinct from the kill-switch bypass.
    # Fail-open: treats the org as observe-only if the tier can't be resolved.
    entitlement = await _resolve_entitlement_state(db, project.organization_id)
    observe_only = entitlement.observe_only
    optimize_enabled = not bypass and not observe_only
    cache_key = cache.compute_cache_key(body)

    # Parse client-supplied business/task context once at the edge and start a
    # decision-evidence draft. Both are additive and fail-open: an absent or
    # malformed context yields the prior behaviour with an empty context.
    request_id = _request_id(request)
    draft = DecisionDraft(
        request_id=request_id,
        client_dialect=parsed.dialect.value,
        provider_requested=adapter.provider,
        model_requested=model,
        api_key_id=api_key_id,
        ctx=parse_request_context(dict(request.headers)),
        bypassed=bypass,
        bypass_reason=_bypass_reason(project) if bypass else None,
    )

    cache_probe = await _maybe_serve_openai_cache(
        db,
        project,
        api_key_id,
        client_key,
        body,
        model,
        cache_key,
        stream,
        background_tasks,
        started,
        not optimize_enabled,
        draft,
    )
    if cache_probe.response is not None:
        return cache_probe.response

    # Hard-cap budget enforcement on the paid forward path. Cache hits above were
    # served at $0 and are exempt; only optimization-enabled (Performance,
    # non-bypassed) traffic is gated, and the check is fail-open.
    if optimize_enabled:
        blocked = await _budget_block(db, project, draft.ctx, request_id)
        if blocked is not None:
            return blocked

    opt = await _resolve_openai_optimizations(
        db,
        project,
        parsed,
        adapter.provider,
        request_id,
        not optimize_enabled,
        draft,
    )
    body = opt.body
    if opt.upstream_provider != adapter.provider:
        adapter = get_adapter(opt.upstream_provider)
        client_key = provider_key_for_project(project.id, adapter.provider)
        if not client_key:
            return origin.varsten_error(
                code=origin.CODE_NO_PROVIDER_KEY,
                type_="varsten_no_provider_key",
                message="no provider key configured for this project",
                status_code=status.HTTP_502_BAD_GATEWAY,
            )

    # --- forward to OpenAI (cache miss, bypassed, or observe-only). store_cache is
    # off unless optimization is enabled (Performance and not kill-switched). ---
    mode = "bypass" if bypass else ("observe" if observe_only else "optimize")
    headers = {
        "X-Varsten-Mode": mode,
        "X-Varsten-Cache": "bypass" if bypass else ("off" if observe_only else "miss"),
        # Correlation id so the client can later attach outcome feedback to this
        # exact request (POST /v1/feedback).
        "X-Varsten-Request-Id": request_id,
        # Forward path: a relayed provider result (success or provider error). The
        # circuit-open branch below re-tags itself varsten via varsten_error.
        origin.ORIGIN_HEADER: origin.ORIGIN_PROVIDER,
        **_entitlement_headers(entitlement),
    }
    if opt.routed_from:
        headers["X-Varsten-Routed"] = _routed_header(
            opt.routed_from_provider or adapter.provider,
            opt.routed_from,
            opt.upstream_provider,
            opt.upstream_model,
        )
    if opt.trim_applied:
        headers["X-Varsten-Trim"] = "applied"
    if opt.arm:
        headers["X-Varsten-Arm"] = opt.arm

    # Circuit breaker: if the upstream has been failing, fail fast instead of
    # making this request wait the full timeout. Cache hits above are unaffected.
    breaker = get_breaker(project.id)
    if not breaker.allow():
        return origin.varsten_error(
            code=origin.CODE_CIRCUIT_OPEN,
            type_="varsten_circuit_open",
            message="upstream temporarily unavailable (circuit open)",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            headers={**headers, "X-Varsten-Circuit": "open"},
        )

    # Propagate the client's idempotency key to the upstream provider ONLY when we
    # forward the request unchanged. If we routed or trimmed, the upstream body
    # differs from what the SDK would send on a direct fallback, so reusing the key
    # could collide at the provider; omit it then (the fallback uses the key fresh).
    forward_idem = (
        request.headers.get("idempotency-key")
        if (opt.routed_from is None and not opt.trim_applied)
        else None
    )

    if stream:
        return StreamingResponse(
            _stream_through(
                db,
                project,
                api_key_id,
                client_key,
                adapter,
                body,
                model,
                cache_key,
                breaker,
                cache_probe.embedding,
                store_cache=optimize_enabled,
                upstream_model=opt.upstream_model,
                routed_from=opt.routed_from,
                routed_from_provider=opt.routed_from_provider,
                arm=opt.arm,
                exp_from=opt.exp_from,
                exp_to=opt.exp_to,
                started=started,
                draft=draft,
                idempotency_key=forward_idem,
            ),
            media_type=SSE_MEDIA_TYPE,
            headers=headers,
        )
    return await _forward_once(
        db,
        project,
        api_key_id,
        client_key,
        adapter,
        body,
        model,
        cache_key,
        breaker,
        cache_probe.embedding,
        store_cache=optimize_enabled,
        headers=headers,
        started=started,
        upstream_model=opt.upstream_model,
        routed_from=opt.routed_from,
        routed_from_provider=opt.routed_from_provider,
        arm=opt.arm,
        exp_from=opt.exp_from,
        exp_to=opt.exp_to,
        draft=draft,
        idempotency_key=forward_idem,
    )


async def _maybe_serve_openai_cache(
    db: AsyncSession,
    project: Project,
    api_key_id,
    client_key: str,
    body: dict,
    model: str,
    cache_key: str,
    stream: bool,
    background_tasks: BackgroundTasks,
    started: float,
    bypass: bool,
    draft: DecisionDraft,
) -> OpenAICacheProbe:
    # Exact cache stays ahead of semantic lookup: byte-identical repeats avoid
    # both provider and embedding calls. The whole path fails open.
    if bypass or not settings.proxy_cache_enabled:
        return OpenAICacheProbe(None, None)
    try:
        entry = await cache.get_cached(db, project.id, cache_key)
    except Exception:
        logger.exception("cache lookup failed; forwarding", extra={"project_id": str(project.id)})
        entry = None
    if entry is not None:
        return OpenAICacheProbe(
            _serve_cache_hit(db, project, api_key_id, entry, stream, "hit", background_tasks, started, draft),
            None,
        )

    if not settings.semantic_cache_enabled:
        return OpenAICacheProbe(None, None)
    try:
        embedding = await embed(embedding_input(body), client_key)
        sem = await cache.semantic_search(db, project.id, model, embedding, settings.semantic_cache_threshold)
    except Exception:
        logger.exception("semantic lookup failed; forwarding", extra={"project_id": str(project.id)})
        return OpenAICacheProbe(None, None)
    if sem is not None:
        return OpenAICacheProbe(
            _serve_cache_hit(db, project, api_key_id, sem, stream, "semantic", background_tasks, started, draft),
            embedding,
        )
    return OpenAICacheProbe(None, embedding)


async def _resolve_openai_optimizations(
    db: AsyncSession,
    project: Project,
    parsed: ParsedClientRequest,
    requested_provider: str,
    request_id: str,
    bypass: bool,
    draft: DecisionDraft,
) -> OpenAIOptimizationState:
    # A request joins at most one lever's holdback experiment so savings never
    # double-count: model routing first, token trim only when no route applies.
    model = parsed.model or ""
    body = parsed.body
    if bypass:
        return OpenAIOptimizationState(body, model, requested_provider, None, None, None, None, None, False)

    decision = await routing.resolve_route(db, project.id, model, body, requested_provider=requested_provider)
    if (
        decision
        and decision.candidate_model
        and (decision.candidate_model != model or decision.candidate_provider != requested_provider)
    ):
        ineligibility = cross_provider_ineligibility(
            parsed,
            requested_provider=requested_provider,
            candidate_provider=decision.candidate_provider,
        )
        if ineligibility is not None:
            draft.route_eligible = False
            draft.route_ineligible_reason = ineligibility.reason_code
            draft.lever = decision.lever
            await _record_routing_ineligibility(
                db,
                project,
                parsed,
                request_id=request_id,
                requested_provider=requested_provider,
                candidate_provider=decision.candidate_provider,
                candidate_model=decision.candidate_model,
                reason_code=ineligibility.reason_code,
                reason_detail=ineligibility.reason_detail,
            )
            return OpenAIOptimizationState(body, model, requested_provider, None, None, None, None, None, False)

        draft.route_eligible = True
        draft.lever = decision.lever
        draft.policy_id = decision.policy_id
        draft.source_recommendation_id = decision.source_recommendation_id
        arm = routing.assign_arm(decision.holdback_percent)
        routed_from = model if arm == routing.ARM_TREATMENT else None
        upstream_model = decision.candidate_model if arm == routing.ARM_TREATMENT else model
        upstream_provider = decision.candidate_provider if arm == routing.ARM_TREATMENT else requested_provider
        routed_from_provider = requested_provider if arm == routing.ARM_TREATMENT else None
        return OpenAIOptimizationState(
            body,
            upstream_model,
            upstream_provider,
            routed_from,
            routed_from_provider,
            arm,
            model,
            decision.candidate_model,
            False,
        )

    tdecision = await trim.resolve_trim(db, project.id, model)
    if not tdecision:
        return OpenAIOptimizationState(body, model, requested_provider, None, None, None, None, None, False)

    draft.lever = trim.LEVER
    arm = routing.assign_arm(tdecision.holdback_percent)
    if arm != routing.ARM_TREATMENT:
        return OpenAIOptimizationState(body, model, requested_provider, None, None, arm, model, model, False)
    trimmed_body, trim_applied = trim.apply_trim(body, tdecision.params)
    draft.trim_applied = trim_applied
    return OpenAIOptimizationState(
        trimmed_body,
        model,
        requested_provider,
        None,
        None,
        arm,
        model,
        model,
        trim_applied,
    )


def _request_id(request: Request) -> str:
    return request_id_ctx.get() or request.headers.get("x-request-id") or f"req_{uuid.uuid4().hex}"


def _with_idempotency(headers: dict[str, str], idempotency_key: str | None) -> dict[str, str]:
    """Add the client's Idempotency-Key to the upstream request headers so the
    provider can dedupe a direct SDK fallback retry against this proxied call.

    Only ever passed a key on the verbatim forward path (no route/trim change), so
    the same key can never reach the provider with a different request body."""
    if not idempotency_key:
        return headers
    return {**headers, "Idempotency-Key": idempotency_key}


def _routed_header(from_provider: str, from_model: str, to_provider: str, to_model: str) -> str:
    if from_provider == to_provider:
        return f"{from_model}->{to_model}"
    return f"{from_provider}:{from_model}->{to_provider}:{to_model}"


async def _record_routing_ineligibility(
    db: AsyncSession,
    project: Project,
    parsed: ParsedClientRequest,
    *,
    request_id: str,
    requested_provider: str,
    candidate_provider: str,
    candidate_model: str,
    reason_code: str,
    reason_detail: dict,
) -> None:
    await record_ineligible_decision_async(
        db,
        organization_id=project.organization_id,
        project_id=project.id,
        request_id=request_id,
        client_dialect=parsed.dialect.value,
        requested_provider=requested_provider,
        requested_model=parsed.model or "",
        candidate_provider=candidate_provider,
        candidate_model=candidate_model,
        reason_code=reason_code,
        reason_detail=reason_detail,
        commit=True,
    )


async def _meter_cache_hit(db, project, api_key_id, entry, latency_ms, cache_label, draft) -> None:
    """Record the hit and the $0 ledger row. Runs in a BackgroundTask after the
    response is sent (but before the request session is torn down), so the cache
    hit's time-to-first-byte never includes these DB commits. Best-effort: a
    failure here is logged, never surfaced to the client whose response already
    went out."""
    try:
        await cache.record_hit(db, entry)
        event = await record_proxy_usage(
            db,
            project,
            api_key_id,
            model=entry.model,
            input_tokens=entry.input_tokens,
            output_tokens=entry.output_tokens,
            cached_input_tokens=0,
            cache_hit=True,
            latency_ms=latency_ms,
            context=draft.ctx if draft else None,
        )
        if draft is not None:
            await record_request_decision(
                db,
                draft=draft,
                event=event,
                provider_chosen=draft.provider_requested,
                model_chosen=entry.model,
                cache_status=cache_label,
                latency_ms=latency_ms,
            )
    except Exception:
        logger.exception("cache-hit metering failed", extra={"project_id": str(project.id)})


def _serve_cache_hit(
    db, project, api_key_id, entry, stream, cache_label, background_tasks: BackgroundTasks, started, draft
):
    """Serve a cache entry (exact or semantic) immediately. Hit accounting and the
    $0 ledger row are deferred to a BackgroundTask so no DB commit sits on the
    critical path; the cached bytes are already in memory."""
    latency_ms = int((time.perf_counter() - started) * 1000)
    background_tasks.add_task(_meter_cache_hit, db, project, api_key_id, entry, latency_ms, cache_label, draft)
    # A cache hit is a successful (200) response Varsten served itself. Origin is
    # informational on a 2xx (the SDK only falls back on a failure status), tagged
    # honestly as varsten.
    headers = {"X-Varsten-Mode": "optimize", "X-Varsten-Cache": cache_label, origin.ORIGIN_HEADER: origin.ORIGIN_VARSTEN}
    if stream:
        return StreamingResponse(
            iter(list(canonical.to_openai_sse(entry.response_payload))),
            media_type=SSE_MEDIA_TYPE,
            headers=headers,
        )
    return JSONResponse(entry.response_payload, headers=headers)


async def _parse_client_request(request: Request) -> ParsedClientRequest:
    try:
        body = await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="request body must be json") from exc
    try:
        return classify_client_dialect(
            method=request.method,
            path=request.url.path,
            headers=dict(request.headers),
            body=body,
        )
    except UnsupportedClientDialect as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


async def _native_provider_passthrough(
    request: Request,
    api_context: ApiKeyContext,
    db: AsyncSession,
    provider: str,
    expected_dialect: ClientDialect,
):
    parsed = await _parse_client_request(request)
    if parsed.dialect != expected_dialect:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="unsupported proxy operation")

    project = api_context.project
    limited = _rate_limited(api_context.api_key.id)
    if limited is not None:
        return limited
    adapter = get_adapter(provider)
    bypass = _is_bypassed(project)
    # Free is observe-only: no cross-provider routing. Native is passthrough anyway,
    # so observe-only and the default behaviour coincide except for routing.
    entitlement = await _resolve_entitlement_state(db, project.organization_id)
    observe_only = entitlement.observe_only
    mode = "bypass" if bypass else "observe"
    request_id = _request_id(request)
    response_headers = {
        "X-Varsten-Mode": mode,
        "X-Varsten-Cache": "bypass",
        "X-Varsten-Request-Id": request_id,
        # Native passthrough: a relayed provider result. Circuit-open re-tags itself.
        origin.ORIGIN_HEADER: origin.ORIGIN_PROVIDER,
        **_entitlement_headers(entitlement),
    }
    draft = DecisionDraft(
        request_id=request_id,
        client_dialect=parsed.dialect.value,
        provider_requested=provider,
        model_requested=parsed.model or "",
        api_key_id=api_context.api_key.id,
        request_type=parsed.operation,
        ctx=parse_request_context(dict(request.headers)),
        bypassed=bypass,
        bypass_reason=_bypass_reason(project) if bypass else None,
    )
    # Hard-cap budget enforcement (native passthrough has no cache, so every
    # forward costs money). Only optimization-enabled traffic; fail-open.
    if not bypass and not observe_only:
        blocked = await _budget_block(db, project, draft.ctx, request_id)
        if blocked is not None:
            return blocked

    breaker = get_breaker(project.id)
    if not breaker.allow():
        return origin.varsten_error(
            code=origin.CODE_CIRCUIT_OPEN,
            type_="varsten_circuit_open",
            message="upstream temporarily unavailable (circuit open)",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            headers={**response_headers, "X-Varsten-Circuit": "open"},
        )

    started = time.perf_counter()
    if not bypass and not observe_only:
        routed_response = await _maybe_route_native_cross_provider(
            db,
            project,
            api_context.api_key.id,
            parsed,
            provider,
            request_id,
            breaker,
            started,
            draft,
        )
        if routed_response is not None:
            return routed_response

    client_key = provider_key_for_project(project.id, adapter.provider)
    if not client_key:
        return origin.varsten_error(
            code=origin.CODE_NO_PROVIDER_KEY,
            type_="varsten_no_provider_key",
            message="no provider key configured for this project",
            status_code=status.HTTP_502_BAD_GATEWAY,
        )

    upstream_url = _native_request_url(adapter.provider, parsed, request.url.query)
    upstream_headers = _native_headers(adapter.provider, adapter.headers(client_key), request)
    if parsed.stream:
        return StreamingResponse(
            _native_stream_through(
                db,
                project,
                api_context.api_key.id,
                adapter,
                parsed,
                upstream_url,
                upstream_headers,
                breaker,
                started,
                draft,
            ),
            media_type=SSE_MEDIA_TYPE,
            headers=response_headers,
        )
    return await _native_forward_once(
        db,
        project,
        api_context.api_key.id,
        adapter,
        parsed,
        upstream_url,
        upstream_headers,
        breaker,
        response_headers,
        started,
        draft,
    )


async def _maybe_route_native_cross_provider(
    db: AsyncSession,
    project: Project,
    api_key_id,
    parsed: ParsedClientRequest,
    requested_provider: str,
    request_id: str,
    breaker,
    started: float,
    draft: DecisionDraft,
) -> Response | None:
    if parsed.operation not in {"messages", "generate_content", "stream_generate_content"} or not parsed.model:
        await _audit_native_route_ineligibility(db, project, parsed, requested_provider, request_id)
        return None

    decision = await routing.resolve_route(
        db,
        project.id,
        parsed.model,
        parsed.body,
        requested_provider=requested_provider,
    )
    if decision is None or decision.candidate_provider == requested_provider:
        return None

    ineligibility = cross_provider_ineligibility(
        parsed,
        requested_provider=requested_provider,
        candidate_provider=decision.candidate_provider,
    )
    if ineligibility is not None:
        # The incumbent will forward below; tag the draft so its evidence row shows
        # the route was considered and rejected.
        draft.route_eligible = False
        draft.route_ineligible_reason = ineligibility.reason_code
        draft.lever = decision.lever
        await _record_routing_ineligibility(
            db,
            project,
            parsed,
            request_id=request_id,
            requested_provider=requested_provider,
            candidate_provider=decision.candidate_provider,
            candidate_model=decision.candidate_model,
            reason_code=ineligibility.reason_code,
            reason_detail=ineligibility.reason_detail,
        )
        return None

    arm = routing.assign_arm(decision.holdback_percent)
    if arm != routing.ARM_TREATMENT:
        return None

    draft.route_eligible = True
    draft.lever = decision.lever
    draft.policy_id = decision.policy_id
    draft.source_recommendation_id = decision.source_recommendation_id

    adapter = get_adapter(decision.candidate_provider)
    client_key = provider_key_for_project(project.id, adapter.provider)
    if not client_key:
        logger.warning(
            "candidate provider key missing; forwarding incumbent",
            extra={"project_id": str(project.id), "provider": adapter.provider},
        )
        return None

    openai_body = request_to_openai_shape(parsed)
    headers = {
        "X-Varsten-Mode": "optimize",
        "X-Varsten-Cache": "bypass",
        "X-Varsten-Routed": _routed_header(
            requested_provider,
            parsed.model,
            adapter.provider,
            decision.candidate_model,
        ),
        "X-Varsten-Arm": arm,
        origin.ORIGIN_HEADER: origin.ORIGIN_PROVIDER,
    }
    if parsed.stream:
        return StreamingResponse(
            _native_cross_provider_stream(
                db,
                project,
                api_key_id,
                adapter,
                parsed,
                openai_body,
                client_key,
                decision.candidate_model,
                requested_provider,
                breaker,
                arm,
                started,
                draft,
            ),
            media_type=SSE_MEDIA_TYPE,
            headers=headers,
        )

    upstream_body = adapter.prepare_request(openai_body, model=decision.candidate_model, stream=False)
    try:
        resp = await http_client.get_client().post(
            adapter.request_url(model=decision.candidate_model, stream=False),
            headers=adapter.headers(client_key),
            json=upstream_body,
            timeout=settings.proxy_upstream_timeout_seconds,
        )
    except httpx.RequestError as exc:
        breaker.record_failure()
        logger.warning(
            "upstream request failed", extra={"project_id": str(project.id), "error": exc.__class__.__name__}
        )
        return origin.varsten_error(
            code=origin.CODE_UPSTREAM_UNREACHABLE,
            type_="varsten_upstream_error",
            message=f"upstream request failed: {exc.__class__.__name__}",
            status_code=status.HTTP_502_BAD_GATEWAY,
            headers=headers,
        )

    if resp.status_code != 200:
        if is_upstream_failure(resp.status_code):
            breaker.record_failure()
        else:
            breaker.record_success()
        return _response_from_upstream(resp, headers)

    breaker.record_success()
    result = adapter.parse_completion(resp.json())
    latency_ms = int((time.perf_counter() - started) * 1000)
    await _capture(
        db,
        project,
        api_key_id,
        provider=adapter.provider,
        model=result.model or decision.candidate_model,
        cache_model=parsed.model,
        response_payload=canonical.completion_payload(result),
        cache_key=cache.compute_cache_key(openai_body),
        in_tok=result.usage.input_tokens,
        out_tok=result.usage.output_tokens,
        cached_tok=result.usage.provider_cached_input_tokens,
        store_cache=False,
        embedding=None,
        body=openai_body,
        routed_from=parsed.model,
        routed_from_provider=requested_provider,
        arm=arm,
        exp_from=parsed.model,
        exp_to=decision.candidate_model,
        latency_ms=latency_ms,
        draft=draft,
    )
    return JSONResponse(render_completion_for_client(parsed, result), headers=headers)


async def _native_cross_provider_stream(
    db: AsyncSession,
    project: Project,
    api_key_id,
    adapter,
    parsed: ParsedClientRequest,
    openai_body: dict,
    client_key: str,
    upstream_model: str,
    requested_provider: str,
    breaker,
    arm: str,
    started: float,
    draft: DecisionDraft,
) -> AsyncIterator[bytes]:
    upstream_body = adapter.prepare_request(openai_body, model=upstream_model, stream=True)
    translator = adapter.stream_translator()
    renderer = stream_renderer_for_client(parsed)
    first_byte_at: float | None = None
    timeout = httpx.Timeout(
        settings.proxy_stream_read_timeout_seconds,
        connect=settings.proxy_stream_connect_timeout_seconds,
    )
    client = http_client.get_client()
    try:
        async with asyncio.timeout(settings.proxy_stream_total_timeout_seconds):
            async with client.stream(
                "POST",
                adapter.request_url(model=upstream_model, stream=True),
                headers=adapter.headers(client_key),
                json=upstream_body,
                timeout=timeout,
            ) as resp:
                if resp.status_code != 200:
                    if is_upstream_failure(resp.status_code):
                        breaker.record_failure()
                    else:
                        breaker.record_success()
                    yield await resp.aread()
                    return
                breaker.record_success()
                async for chunk in resp.aiter_bytes():
                    if first_byte_at is None:
                        first_byte_at = time.perf_counter()
                    for openai_chunk in translator.push(chunk):
                        for out in renderer.push(openai_chunk):
                            yield out
    except (httpx.RequestError, TimeoutError) as exc:
        breaker.record_failure()
        logger.warning("upstream stream failed", extra={"project_id": str(project.id), "error": exc.__class__.__name__})
        yield f'event: error\ndata: {{"error":{{"message":"upstream request failed: {exc.__class__.__name__}","type":"varsten_upstream_error"}}}}\n\n'.encode()
        return

    try:
        result = translator.finish()
        for out in renderer.finish(result):
            yield out
        latency_ms = int((first_byte_at - started) * 1000) if first_byte_at else None
        payload = canonical.completion_payload(result) if (result.content or result.tool_calls) else {}
        await _capture(
            db,
            project,
            api_key_id,
            provider=adapter.provider,
            model=result.model or upstream_model,
            cache_model=parsed.model or result.model or "",
            response_payload=payload,
            cache_key=cache.compute_cache_key(openai_body),
            in_tok=result.usage.input_tokens,
            out_tok=result.usage.output_tokens,
            cached_tok=result.usage.provider_cached_input_tokens,
            store_cache=False,
            embedding=None,
            body=openai_body,
            routed_from=parsed.model,
            routed_from_provider=requested_provider,
            arm=arm,
            exp_from=parsed.model,
            exp_to=upstream_model,
            latency_ms=latency_ms,
            draft=draft,
        )
    except Exception:
        logger.exception("post-stream capture failed", extra={"project_id": str(project.id)})


async def _audit_native_route_ineligibility(
    db: AsyncSession,
    project: Project,
    parsed: ParsedClientRequest,
    requested_provider: str,
    request_id: str,
) -> None:
    if parsed.operation not in {"messages", "generate_content", "stream_generate_content"}:
        return
    if not parsed.model:
        return
    decision = await routing.resolve_route(
        db,
        project.id,
        parsed.model,
        parsed.body,
        requested_provider=requested_provider,
    )
    if decision is None or decision.candidate_provider == requested_provider:
        return
    ineligibility = cross_provider_ineligibility(
        parsed,
        requested_provider=requested_provider,
        candidate_provider=decision.candidate_provider,
    )
    if ineligibility is None:
        return
    await _record_routing_ineligibility(
        db,
        project,
        parsed,
        request_id=request_id,
        requested_provider=requested_provider,
        candidate_provider=decision.candidate_provider,
        candidate_model=decision.candidate_model,
        reason_code=ineligibility.reason_code,
        reason_detail=ineligibility.reason_detail,
    )


def _native_headers(provider: str, base_headers: dict[str, str], request: Request) -> dict[str, str]:
    headers = dict(base_headers)
    if provider == "anthropic":
        for name in ("anthropic-version", "anthropic-beta"):
            incoming = request.headers.get(name)
            if incoming:
                headers[name] = incoming
    return headers


def _native_request_url(provider: str, parsed: ParsedClientRequest, query: str) -> str:
    if provider == "anthropic":
        base_url = settings.anthropic_base_url.rstrip("/")
    elif provider == "gemini":
        base_url = settings.gemini_base_url.rstrip("/")
    else:
        raise ValueError(f"unsupported native provider: {provider}")
    url = f"{base_url}{parsed.path}"
    return f"{url}?{query}" if query else url


def _native_operation_is_metered(parsed: ParsedClientRequest) -> bool:
    return parsed.operation in {"messages", "generate_content", "stream_generate_content"}


def _response_from_upstream(resp: httpx.Response, headers: dict[str, str]) -> Response:
    try:
        payload = resp.json()
    except ValueError:
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            headers=headers,
            media_type=resp.headers.get("content-type"),
        )
    return JSONResponse(payload, status_code=resp.status_code, headers=headers)


async def _native_forward_once(
    db: AsyncSession,
    project: Project,
    api_key_id,
    adapter,
    parsed: ParsedClientRequest,
    upstream_url: str,
    upstream_headers: dict[str, str],
    breaker,
    response_headers: dict[str, str],
    started: float,
    draft: DecisionDraft,
) -> Response:
    try:
        resp = await http_client.get_client().post(
            upstream_url,
            headers=upstream_headers,
            json=parsed.body,
            timeout=settings.proxy_upstream_timeout_seconds,
        )
    except httpx.RequestError as exc:
        breaker.record_failure()
        logger.warning(
            "upstream request failed", extra={"project_id": str(project.id), "error": exc.__class__.__name__}
        )
        return origin.varsten_error(
            code=origin.CODE_UPSTREAM_UNREACHABLE,
            type_="varsten_upstream_error",
            message=f"upstream request failed: {exc.__class__.__name__}",
            status_code=status.HTTP_502_BAD_GATEWAY,
            headers=response_headers,
        )

    if resp.status_code != 200:
        if is_upstream_failure(resp.status_code):
            breaker.record_failure()
        else:
            breaker.record_success()
        return _response_from_upstream(resp, response_headers)

    breaker.record_success()
    raw = resp.json()
    if _native_operation_is_metered(parsed):
        result = adapter.parse_completion(raw)
        latency_ms = int((time.perf_counter() - started) * 1000)
        await _capture(
            db,
            project,
            api_key_id,
            provider=adapter.provider,
            model=result.model or parsed.model or "",
            cache_model=parsed.model or result.model or "",
            response_payload=canonical.completion_payload(result),
            cache_key=cache.compute_cache_key(parsed.body),
            in_tok=result.usage.input_tokens,
            out_tok=result.usage.output_tokens,
            cached_tok=result.usage.provider_cached_input_tokens,
            store_cache=False,
            embedding=None,
            body=None,
            latency_ms=latency_ms,
            draft=draft,
        )
    return JSONResponse(raw, headers=response_headers)


async def _native_stream_through(
    db: AsyncSession,
    project: Project,
    api_key_id,
    adapter,
    parsed: ParsedClientRequest,
    upstream_url: str,
    upstream_headers: dict[str, str],
    breaker,
    started: float,
    draft: DecisionDraft,
) -> AsyncIterator[bytes]:
    translator = adapter.stream_translator() if _native_operation_is_metered(parsed) else None
    first_byte_at: float | None = None
    timeout = httpx.Timeout(
        settings.proxy_stream_read_timeout_seconds,
        connect=settings.proxy_stream_connect_timeout_seconds,
    )
    client = http_client.get_client()
    try:
        async with asyncio.timeout(settings.proxy_stream_total_timeout_seconds):
            async with client.stream(
                "POST",
                upstream_url,
                headers=upstream_headers,
                json=parsed.body,
                timeout=timeout,
            ) as resp:
                if resp.status_code != 200:
                    if is_upstream_failure(resp.status_code):
                        breaker.record_failure()
                    else:
                        breaker.record_success()
                    yield await resp.aread()
                    return
                breaker.record_success()
                async for chunk in resp.aiter_bytes():
                    if first_byte_at is None:
                        first_byte_at = time.perf_counter()
                    if translator is not None:
                        for _ in translator.push(chunk):
                            pass
                    yield chunk
    except (httpx.RequestError, TimeoutError) as exc:
        breaker.record_failure()
        logger.warning("upstream stream failed", extra={"project_id": str(project.id), "error": exc.__class__.__name__})
        yield f'event: error\ndata: {{"error":{{"message":"upstream request failed: {exc.__class__.__name__}","type":"varsten_upstream_error"}}}}\n\n'.encode()
        return

    if translator is None:
        return
    try:
        result = translator.finish()
        latency_ms = int((first_byte_at - started) * 1000) if first_byte_at else None
        payload = canonical.completion_payload(result) if (result.content or result.tool_calls) else {}
        await _capture(
            db,
            project,
            api_key_id,
            provider=adapter.provider,
            model=result.model or parsed.model or "",
            cache_model=parsed.model or result.model or "",
            response_payload=payload,
            cache_key=cache.compute_cache_key(parsed.body),
            in_tok=result.usage.input_tokens,
            out_tok=result.usage.output_tokens,
            cached_tok=result.usage.provider_cached_input_tokens,
            store_cache=False,
            embedding=None,
            body=None,
            latency_ms=latency_ms,
            draft=draft,
        )
    except Exception:
        logger.exception("post-stream capture failed", extra={"project_id": str(project.id)})


async def _capture(
    db: AsyncSession,
    project: Project,
    api_key_id,
    *,
    provider: str,
    model: str,
    cache_model: str,
    response_payload: dict,
    cache_key: str,
    in_tok: int,
    out_tok: int,
    cached_tok: int,
    store_cache: bool,
    embedding: list[float] | None,
    body: dict | None = None,
    routed_from: str | None = None,
    routed_from_provider: str | None = None,
    arm: str | None = None,
    exp_from: str | None = None,
    exp_to: str | None = None,
    latency_ms: int | None = None,
    draft: DecisionDraft | None = None,
) -> None:
    """Write the ledger row and (unless bypassed) store the cache entry, with its
    prompt embedding, for a miss.

    The ledger uses the upstream's precise response model; the cache stores the
    requested model so the next request (which specifies the same requested model)
    matches in the model-scoped semantic search.

    Best-effort: the response has already been obtained from OpenAI, so bookkeeping
    must never raise and fail the client's request. A failure here should be made
    visible by observability later, never by a 500."""
    # Objective response health, only for arm-tagged (experiment) traffic, so the
    # drift guard can compare the treatment arm against the control arm.
    quality_ok = quality.response_quality_ok(response_payload, quality.wants_json(body or {})) if arm else None
    event = None
    try:
        event = await record_proxy_usage(
            db,
            project,
            api_key_id,
            provider=provider,
            model=model,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cached_input_tokens=cached_tok,
            cache_hit=False,
            naive_model=routed_from,
            naive_provider=routed_from_provider,
            arm=arm,
            experiment_from=exp_from,
            experiment_to=exp_to,
            quality_ok=quality_ok,
            latency_ms=latency_ms,
            context=draft.ctx if draft else None,
        )
    except Exception:
        logger.exception("proxy ledger write failed", extra={"project_id": str(project.id)})

    # Moat evidence: one decision record per metered request. Best-effort, off the
    # response path, and a no-op if the ledger write above failed. Guarded here too
    # (record_request_decision is already self-guarding) so no evidence bug can ever
    # surface as a 500 on a response that already went out.
    if draft is not None and event is not None:
        try:
            await record_request_decision(
                db,
                draft=draft,
                event=event,
                provider_chosen=provider,
                model_chosen=model,
                cache_status="miss",
                arm=arm,
                routed_from=routed_from,
                routed_from_provider=routed_from_provider,
                trim_applied=draft.trim_applied,
                latency_ms=latency_ms,
                quality_ok=quality_ok,
            )
        except Exception:
            logger.exception("decision evidence capture failed", extra={"project_id": str(project.id)})

    if event is not None and store_cache and settings.proxy_cache_enabled and response_payload:
        try:
            # embedding is None unless the semantic layer is on; the entry still
            # serves exact-hash hits either way.
            await cache.store(
                db, project.id, cache_key, cache_model, response_payload, in_tok, out_tok, embedding=embedding
            )
        except Exception:
            logger.exception("proxy cache write failed", extra={"project_id": str(project.id)})

    # Eval harness tap: sample this real (prompt, incumbent response) into the
    # replay corpus, only when the project opted in and we are optimizing (not
    # bypassed). Keyed on the requested model so a model-downshift recommendation on
    # that route can later replay it. Best-effort and off the response path.
    if store_cache and body is not None and response_payload:
        await eval_capture.capture_sample(
            db,
            project,
            body=body,
            response_payload=response_payload,
            model=cache_model,
            input_tokens=in_tok,
            output_tokens=out_tok,
        )


async def _stream_through(
    db,
    project,
    api_key_id,
    client_key,
    adapter,
    body,
    model,
    cache_key,
    breaker,
    embedding,
    store_cache,
    upstream_model=None,
    routed_from=None,
    routed_from_provider=None,
    arm=None,
    exp_from=None,
    exp_to=None,
    started=None,
    draft=None,
    idempotency_key=None,
):
    """Pass the provider's stream through to the client via the adapter's stream
    translator (verbatim for an OpenAI upstream), accumulating a copy to bill and
    (unless bypassed) cache after the client has its bytes."""
    upstream_body = adapter.prepare_request(body, model=upstream_model or model, stream=True)
    translator = adapter.stream_translator()
    first_byte_at: float | None = None
    # Finite timeouts so a hung upstream cannot pin this event-loop slot forever:
    # read = max gap between chunks, plus connect/write/pool. A wall-clock total cap
    # wraps the whole consumption as a backstop.
    timeout = httpx.Timeout(
        settings.proxy_stream_read_timeout_seconds,
        connect=settings.proxy_stream_connect_timeout_seconds,
    )
    ok = False

    # The shared pooled client: a warm keep-alive connection spares this miss the
    # upstream TLS handshake. Per-request timeout; never closed here.
    client = http_client.get_client()
    try:
        async with asyncio.timeout(settings.proxy_stream_total_timeout_seconds):
            async with client.stream(
                "POST",
                adapter.request_url(model=upstream_model or model, stream=True),
                headers=_with_idempotency(adapter.headers(client_key), idempotency_key),
                json=upstream_body,
                timeout=timeout,
            ) as resp:
                ok = resp.status_code == 200
                if not ok:
                    # The upstream responded but with an error. Trip the breaker on
                    # provider failures (5xx/429); a 4xx is the client's mistake.
                    if is_upstream_failure(resp.status_code):
                        breaker.record_failure()
                    else:
                        breaker.record_success()
                    yield await resp.aread()
                    return
                breaker.record_success()
                async for chunk in resp.aiter_bytes():
                    if first_byte_at is None:
                        first_byte_at = time.perf_counter()  # time-to-first-byte
                    for out in translator.push(chunk):
                        yield out
    except (httpx.RequestError, TimeoutError) as exc:
        # OpenAI unreachable/slow/hung (httpx read timeout or the wall-clock cap):
        # count it against the breaker and emit a clean SSE error instead of a
        # stack trace. httpx.ReadTimeout is an httpx.RequestError; the wall-clock
        # cap raises the builtin TimeoutError.
        breaker.record_failure()
        logger.warning("upstream stream failed", extra={"project_id": str(project.id), "error": exc.__class__.__name__})
        yield f'data: {{"error":{{"message":"upstream request failed: {exc.__class__.__name__}","type":"varsten_upstream_error"}}}}\n\n'.encode()
        yield b"data: [DONE]\n\n"
        return

    # Stream finished and the client has every byte. Best-effort bookkeeping.
    try:
        result = translator.finish()
        in_tok = result.usage.input_tokens
        out_tok = result.usage.output_tokens
        cached_tok = result.usage.provider_cached_input_tokens
        out_model = result.model or model
        # Build (and thus meter + cache) the payload when the assistant returned
        # either content or tool calls. A tool-only response has empty content but
        # must still be captured, or the agent workload's calls are silently lost.
        payload = canonical.completion_payload(result) if (result.content or result.tool_calls) else {}
        # Latency = time-to-first-byte from the proxy's view (request receipt to the
        # first upstream chunk), the number a streaming client actually feels.
        latency_ms = int((first_byte_at - started) * 1000) if (first_byte_at and started) else None
        await _capture(
            db,
            project,
            api_key_id,
            provider=adapter.provider,
            model=out_model,
            cache_model=model,
            response_payload=payload,
            cache_key=cache_key,
            in_tok=in_tok,
            out_tok=out_tok,
            cached_tok=cached_tok,
            store_cache=store_cache,
            embedding=embedding,
            body=body,
            routed_from=routed_from,
            routed_from_provider=routed_from_provider,
            arm=arm,
            exp_from=exp_from,
            exp_to=exp_to,
            latency_ms=latency_ms,
            draft=draft,
        )
    except Exception:
        # Never let post-stream bookkeeping break a delivered response.
        logger.exception("post-stream capture failed", extra={"project_id": str(project.id)})


async def _forward_once(
    db,
    project,
    api_key_id,
    client_key,
    adapter,
    body,
    model,
    cache_key,
    breaker,
    embedding,
    store_cache,
    headers,
    started=None,
    upstream_model=None,
    routed_from=None,
    routed_from_provider=None,
    arm=None,
    exp_from=None,
    exp_to=None,
    draft=None,
    idempotency_key=None,
) -> JSONResponse:
    upstream_body = adapter.prepare_request(body, model=upstream_model or model, stream=False)
    try:
        resp = await http_client.get_client().post(
            adapter.request_url(model=upstream_model or model, stream=False),
            headers=_with_idempotency(adapter.headers(client_key), idempotency_key),
            json=upstream_body,
            timeout=settings.proxy_upstream_timeout_seconds,
        )
    except httpx.RequestError as exc:
        # OpenAI unreachable/slow: count it against the breaker, clean 502.
        breaker.record_failure()
        logger.warning(
            "upstream request failed", extra={"project_id": str(project.id), "error": exc.__class__.__name__}
        )
        return origin.varsten_error(
            code=origin.CODE_UPSTREAM_UNREACHABLE,
            type_="varsten_upstream_error",
            message=f"upstream request failed: {exc.__class__.__name__}",
            status_code=status.HTTP_502_BAD_GATEWAY,
            headers=headers,
        )

    if resp.status_code != 200:
        # Provider failure (5xx/429) trips the breaker; a 4xx is the client's.
        if is_upstream_failure(resp.status_code):
            breaker.record_failure()
        else:
            breaker.record_success()
        try:
            detail = resp.json()
        except ValueError:
            detail = {"error": resp.text}
        return JSONResponse(detail, status_code=resp.status_code, headers=headers)

    breaker.record_success()
    # Latency = request receipt to the upstream response (when we can answer).
    latency_ms = int((time.perf_counter() - started) * 1000) if started else None

    result = adapter.parse_completion(resp.json())
    # The client always gets the OpenAI dialect; for an OpenAI upstream this is the
    # original payload reused verbatim, for any other provider it is the canonical
    # form rendered to OpenAI shape.
    payload = canonical.completion_payload(result)
    await _capture(
        db,
        project,
        api_key_id,
        provider=adapter.provider,
        model=result.model or model,
        cache_model=model,
        response_payload=payload,
        cache_key=cache_key,
        in_tok=result.usage.input_tokens,
        out_tok=result.usage.output_tokens,
        cached_tok=result.usage.provider_cached_input_tokens,
        store_cache=store_cache,
        embedding=embedding,
        body=body,
        routed_from=routed_from,
        routed_from_provider=routed_from_provider,
        arm=arm,
        exp_from=exp_from,
        exp_to=exp_to,
        latency_ms=latency_ms,
        draft=draft,
    )
    return JSONResponse(payload, headers=headers)
