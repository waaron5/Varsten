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
from typing import Any, NamedTuple

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
from app.engine import (
    CandidateStatus,
    PlannerInput,
    RequestFacts,
    build_observe_only_plan,
    evaluate_cache_eligibility,
    normalize_request_facts,
)
from app.engine.priors import outcome_priors_for_request
from app.eval import capture as eval_capture
from app.models import Project
from app.proxy import (
    budget_enforcement,
    cache,
    compression,
    http_client,
    origin,
    prompt_prefix,
    quality,
    resilience,
    routing,
    trim,
)
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
from app.proxy.providers import LLMAdapter, canonical, get_adapter
from app.proxy.request_context import parse_request_context
from app.proxy.routing_eligibility import cross_provider_ineligibility

router = APIRouter(tags=["proxy"])
beta_router = APIRouter(prefix="/v1beta", tags=["proxy"])
logger = get_logger("varsten.proxy")

SSE_MEDIA_TYPE = "text/event-stream"
_EXACT_CACHE_ENFORCED_BLOCKERS = frozenset({"multimodal_content", "tools_present"})


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
    store_cache: bool = True


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
    compression_applied: bool = False


class OpenAIDialectContext(NamedTuple):
    parsed: ParsedClientRequest
    adapter: LLMAdapter
    client_key: str
    body: dict
    request_facts: RequestFacts
    stream: bool
    model: str
    bypass: bool
    entitlement: EntitlementState
    observe_only: bool
    optimize_enabled: bool
    cache_key: str
    request_id: str
    draft: DecisionDraft


class OpenAISetup(NamedTuple):
    context: OpenAIDialectContext | None
    response: Response | None


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


async def _openai_dialect_setup(
    request: Request,
    db: AsyncSession,
    project: Project,
    api_key_id,
    destination_provider: str | None,
) -> OpenAISetup:
    parsed = await _parse_client_request(request)
    if parsed.dialect != ClientDialect.OPENAI or parsed.operation != "chat_completions":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="unsupported proxy operation")

    # The upstream provider is resolved through the adapter registry. Future
    # routing policy selects this per-request; the router below stays provider-agnostic.
    adapter = get_adapter(destination_provider or settings.proxy_default_provider)
    client_key = provider_key_for_project(project.id, adapter.provider)
    if not client_key:
        return OpenAISetup(
            None,
            origin.varsten_error(
                code=origin.CODE_NO_PROVIDER_KEY,
                type_="varsten_no_provider_key",
                message="no provider key configured for this project",
                status_code=status.HTTP_502_BAD_GATEWAY,
            ),
        )

    body = parsed.body
    bypass = _is_bypassed(project)
    entitlement = await _resolve_entitlement_state(db, project.organization_id)
    observe_only = entitlement.observe_only
    optimize_enabled = not bypass and not observe_only
    model = parsed.model or ""
    request_id = _request_id(request)
    request_facts = parsed.request_facts
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
    _attach_observe_plan(
        draft,
        body=body,
        request_facts=request_facts,
        provider=adapter.provider,
        model=model,
        optimize_enabled=optimize_enabled,
        exact_cache_enabled=settings.proxy_cache_enabled,
        semantic_cache_enabled=settings.proxy_cache_enabled and settings.semantic_cache_enabled,
        outcome_priors=await _safe_outcome_priors(db, project.id, model),
    )
    return OpenAISetup(
        OpenAIDialectContext(
            parsed,
            adapter,
            client_key,
            body,
            request_facts,
            parsed.stream,
            model,
            bypass,
            entitlement,
            observe_only,
            optimize_enabled,
            cache.compute_cache_key(body),
            request_id,
            draft,
        ),
        None,
    )


def _openai_forward_headers(
    *,
    adapter: LLMAdapter,
    bypass: bool,
    entitlement: EntitlementState,
    observe_only: bool,
    opt: OpenAIOptimizationState,
    request_id: str,
) -> dict[str, str]:
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
    return headers


def _resolve_openai_candidate_provider(
    project: Project,
    adapter: LLMAdapter,
    client_key: str,
    opt: OpenAIOptimizationState,
    draft: DecisionDraft | None = None,
) -> tuple[LLMAdapter, str, OpenAIOptimizationState]:
    if opt.upstream_provider == adapter.provider:
        return adapter, client_key, opt

    candidate_adapter = get_adapter(opt.upstream_provider)
    candidate_key = provider_key_for_project(project.id, candidate_adapter.provider)
    if candidate_key:
        return candidate_adapter, candidate_key, opt

    # Fail open: the candidate provider has no key configured, so keep the
    # request on the incumbent (already keyed above) instead of failing it.
    # A routing/config gap must only cost a saving, never the request. This
    # mirrors the native-dialect path (_native_cross_provider), which also
    # forwards the incumbent when the candidate key is missing -- returning a
    # 502 here would break base-URL-mode users who have no SDK fallback.
    logger.warning(
        "candidate provider key missing; forwarding incumbent",
        extra={"project_id": str(project.id), "provider": candidate_adapter.provider},
    )
    if draft is not None:
        draft.add_runtime_trace(
            stage="routing",
            lever=draft.lever or "model_routing",
            action="fallback",
            reason_code="candidate_provider_key_missing",
            enforced=True,
            policy_id=draft.policy_id,
            source_recommendation_id=draft.source_recommendation_id,
            detail={"candidate_provider": candidate_adapter.provider, "candidate_model": opt.upstream_model},
        )
    incumbent_model = opt.routed_from or opt.upstream_model
    return (
        adapter,
        client_key,
        OpenAIOptimizationState(
            opt.body, incumbent_model, adapter.provider, None, None, None, None, None, opt.trim_applied
        ),
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


async def _safe_outcome_priors(db: AsyncSession, project_id, model: str) -> tuple:
    """Learned priors for the planner, guarded at the seam: the lookup has its own
    internal fail-open, but a bug in the lookup itself must also cost only the
    priors, never the request (found by the V4 chaos battery)."""
    try:
        return await outcome_priors_for_request(db, project_id, model)
    except Exception:
        logger.exception("outcome prior lookup raised; planning without priors")
        return ()


def _attach_observe_plan(
    draft: DecisionDraft,
    *,
    body: dict,
    request_facts: RequestFacts | None = None,
    provider: str,
    model: str,
    optimize_enabled: bool,
    exact_cache_enabled: bool,
    semantic_cache_enabled: bool,
    routing_policy_present: bool = False,
    routing_policy_id: str | None = None,
    trim_policy_present: bool = False,
    trim_policy_id: str | None = None,
    compression_policy_present: bool = False,
    compression_policy_id: str | None = None,
    outcome_priors: tuple = (),
) -> None:
    """Attach a content-free planner snapshot without affecting execution."""
    try:
        # Fingerprint the request here (body in memory, all dialects flow through
        # this point): the cacheable prefix for measured prompt-cache stability,
        # and the whole body for trace-level redundancy detection. Hashes only.
        draft.prefix_hash = prompt_prefix.stable_prefix_hash(body)
        draft.request_fingerprint = prompt_prefix.full_request_fingerprint(body)
        draft.optimization_plan = build_observe_only_plan(
            PlannerInput(
                request_id=draft.request_id,
                provider=provider,
                model=model,
                body=body,
                request_facts=request_facts or normalize_request_facts(body),
                context=draft.ctx,
                optimize_enabled=optimize_enabled,
                exact_cache_enabled=exact_cache_enabled,
                semantic_cache_enabled=semantic_cache_enabled,
                routing_policy_present=routing_policy_present,
                routing_policy_id=routing_policy_id,
                trim_policy_present=trim_policy_present,
                trim_policy_id=trim_policy_id,
                compression_policy_present=compression_policy_present,
                compression_policy_id=compression_policy_id,
                outcome_priors=tuple(outcome_priors),
            )
        )
    except Exception:
        logger.exception("observe-only optimization planner failed")


def _rejected_candidate(draft: DecisionDraft, lever: str):
    plan = draft.optimization_plan
    if plan is None:
        return None
    for candidate in plan.candidates:
        if candidate.lever == lever and candidate.status == CandidateStatus.REJECTED:
            return candidate
    return None


def _trace_rejected_candidate(
    draft: DecisionDraft,
    *,
    stage: str,
    lever: str,
    candidate,
    policy_id=None,
    source_recommendation_id=None,
) -> None:
    draft.add_runtime_trace(
        stage=stage,
        lever=lever,
        action="skipped",
        reason_code=candidate.reason_code,
        enforced=True,
        policy_id=policy_id,
        source_recommendation_id=source_recommendation_id,
        detail={
            "candidate_status": candidate.status.value,
            "quality_gate": candidate.quality_gate.value,
            "risk": candidate.risk.value,
            "reason_detail": candidate.reason_detail,
        },
    )


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

    setup = await _openai_dialect_setup(request, db, project, api_key_id, destination_provider)
    if setup.response is not None:
        return setup.response
    ctx = setup.context
    assert ctx is not None

    # Seam-level fail-open (V4 chaos finding): each lookup inside the probe and
    # the resolvers is individually guarded, but a bug in the resolution code
    # itself must also cost only the optimization, never the request. Any
    # exception here degrades to a plain passthrough forward.
    try:
        cache_probe = await _maybe_serve_openai_cache(
            db,
            project,
            api_key_id,
            ctx.client_key,
            ctx.body,
            ctx.model,
            ctx.cache_key,
            ctx.stream,
            background_tasks,
            started,
            not ctx.optimize_enabled,
            ctx.draft,
        )
    except Exception:
        logger.exception("cache probe raised; passing through (fail-open)", extra={"project_id": str(project.id)})
        cache_probe = OpenAICacheProbe(None, None, False)
    if cache_probe.response is not None:
        return cache_probe.response

    # Hard-cap budget enforcement on the paid forward path. Cache hits above were
    # served at $0 and are exempt; only optimization-enabled (Performance,
    # non-bypassed) traffic is gated, and the check is fail-open.
    if ctx.optimize_enabled:
        blocked = await _budget_block(db, project, ctx.draft.ctx, ctx.request_id)
        if blocked is not None:
            return blocked

    try:
        opt = await _resolve_openai_optimizations(
            db,
            project,
            ctx.parsed,
            ctx.adapter.provider,
            ctx.request_id,
            not ctx.optimize_enabled,
            ctx.draft,
            ctx.request_facts,
        )
    except Exception:
        logger.exception(
            "optimization resolution raised; passing through (fail-open)", extra={"project_id": str(project.id)}
        )
        ctx.draft.add_runtime_trace(
            stage="optimization_resolution",
            lever="none",
            action="error",
            reason_code="resolution_failed_fail_open",
            detail={"fail_open": True},
        )
        opt = _openai_passthrough_state(ctx.body, ctx.model, ctx.adapter.provider)
    body = opt.body
    adapter, client_key, opt = _resolve_openai_candidate_provider(project, ctx.adapter, ctx.client_key, opt, ctx.draft)

    # --- forward to OpenAI (cache miss, bypassed, or observe-only). store_cache is
    # off unless optimization is enabled (Performance and not kill-switched). ---
    headers = _openai_forward_headers(
        adapter=adapter,
        bypass=ctx.bypass,
        entitlement=ctx.entitlement,
        observe_only=ctx.observe_only,
        opt=opt,
        request_id=ctx.request_id,
    )

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
        if (opt.routed_from is None and not opt.trim_applied and not opt.compression_applied)
        else None
    )

    if ctx.stream:
        return StreamingResponse(
            _stream_through(
                db,
                project,
                api_key_id,
                client_key,
                adapter,
                body,
                ctx.model,
                ctx.cache_key,
                breaker,
                cache_probe.embedding,
                store_cache=ctx.optimize_enabled and cache_probe.store_cache,
                upstream_model=opt.upstream_model,
                routed_from=opt.routed_from,
                routed_from_provider=opt.routed_from_provider,
                arm=opt.arm,
                exp_from=opt.exp_from,
                exp_to=opt.exp_to,
                started=started,
                draft=ctx.draft,
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
        ctx.model,
        ctx.cache_key,
        breaker,
        cache_probe.embedding,
        store_cache=ctx.optimize_enabled and cache_probe.store_cache,
        headers=headers,
        started=started,
        upstream_model=opt.upstream_model,
        routed_from=opt.routed_from,
        routed_from_provider=opt.routed_from_provider,
        arm=opt.arm,
        exp_from=opt.exp_from,
        exp_to=opt.exp_to,
        draft=ctx.draft,
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
    if bypass:
        draft.add_runtime_trace(
            stage="cache_lookup",
            lever="exact_cache",
            action="skipped",
            reason_code="optimization_disabled",
            enforced=True,
        )
        draft.add_runtime_trace(
            stage="cache_lookup",
            lever="semantic_cache",
            action="skipped",
            reason_code="optimization_disabled",
            enforced=True,
        )
        return OpenAICacheProbe(None, None)
    if not settings.proxy_cache_enabled:
        draft.add_runtime_trace(
            stage="cache_lookup",
            lever="exact_cache",
            action="skipped",
            reason_code="cache_disabled",
            enforced=True,
        )
        draft.add_runtime_trace(
            stage="cache_lookup",
            lever="semantic_cache",
            action="skipped",
            reason_code="cache_disabled",
            enforced=True,
        )
        return OpenAICacheProbe(None, None)
    exact_cache_allowed, exact_blockers, exact_enforced_blockers = _exact_cache_policy(draft)
    if exact_cache_allowed:
        draft.add_runtime_trace(
            stage="cache_lookup",
            lever="exact_cache",
            action="lookup",
            reason_code="exact_cache_lookup_allowed",
        )
        try:
            entry = await cache.get_cached(db, project.id, cache_key)
        except Exception:
            logger.exception("cache lookup failed; forwarding", extra={"project_id": str(project.id)})
            draft.add_runtime_trace(
                stage="cache_lookup",
                lever="exact_cache",
                action="error",
                reason_code="exact_cache_lookup_failed",
                detail={"fail_open": True},
            )
            entry = None
        if entry is not None:
            draft.add_runtime_trace(
                stage="cache_lookup",
                lever="exact_cache",
                action="hit",
                reason_code="exact_cache_hit",
            )
            return OpenAICacheProbe(
                _serve_cache_hit(db, project, api_key_id, entry, stream, "hit", background_tasks, started, draft),
                None,
            )
        draft.add_runtime_trace(
            stage="cache_lookup",
            lever="exact_cache",
            action="miss",
            reason_code="exact_cache_miss",
        )
    else:
        draft.add_runtime_trace(
            stage="cache_lookup",
            lever="exact_cache",
            action="skipped",
            reason_code="exact_cache_policy_blocked",
            enforced=True,
            detail={"blockers": exact_blockers, "enforced_blockers": exact_enforced_blockers},
        )

    if not settings.semantic_cache_enabled:
        draft.add_runtime_trace(
            stage="cache_lookup",
            lever="semantic_cache",
            action="skipped",
            reason_code="semantic_cache_disabled",
            enforced=True,
        )
        return OpenAICacheProbe(None, None, exact_cache_allowed)
    semantic_cache_allowed, semantic_blockers = _semantic_cache_policy(draft)
    if not semantic_cache_allowed:
        draft.add_runtime_trace(
            stage="cache_lookup",
            lever="semantic_cache",
            action="skipped",
            reason_code="semantic_cache_policy_blocked",
            enforced=True,
            detail={"blockers": semantic_blockers},
        )
        return OpenAICacheProbe(None, None, exact_cache_allowed)
    draft.add_runtime_trace(
        stage="cache_lookup",
        lever="semantic_cache",
        action="lookup",
        reason_code="semantic_cache_lookup_allowed",
    )
    try:
        embedding = await embed(embedding_input(body), client_key, db=db, project=project)
        sem = await cache.semantic_search(db, project.id, model, embedding, settings.semantic_cache_threshold)
    except Exception:
        logger.exception("semantic lookup failed; forwarding", extra={"project_id": str(project.id)})
        draft.add_runtime_trace(
            stage="cache_lookup",
            lever="semantic_cache",
            action="error",
            reason_code="semantic_cache_lookup_failed",
            detail={"fail_open": True},
        )
        return OpenAICacheProbe(None, None, exact_cache_allowed)
    if sem is not None:
        draft.add_runtime_trace(
            stage="cache_lookup",
            lever="semantic_cache",
            action="hit",
            reason_code="semantic_cache_hit",
        )
        return OpenAICacheProbe(
            _serve_cache_hit(db, project, api_key_id, sem, stream, "semantic", background_tasks, started, draft),
            embedding,
        )
    draft.add_runtime_trace(
        stage="cache_lookup",
        lever="semantic_cache",
        action="miss",
        reason_code="semantic_cache_miss",
    )
    return OpenAICacheProbe(None, embedding, exact_cache_allowed)


def _exact_cache_policy(draft: DecisionDraft) -> tuple[bool, list[str], list[str]]:
    """Enforce exact-cache denial only for request shapes that can depend on
    external tool execution or non-text inputs.

    Other rejected exact-cache candidates remain report-only for now so legacy
    exact-cache behavior is not broadly changed in one step.
    """
    if draft.optimization_plan is None:
        return True, [], []
    try:
        gate = evaluate_cache_eligibility("exact_cache", draft.optimization_plan.classification)
    except Exception:
        logger.exception("exact cache policy failed; preserving existing cache behavior")
        return True, [], []
    blockers = list(gate.blockers)
    enforced_blockers = sorted(_EXACT_CACHE_ENFORCED_BLOCKERS.intersection(gate.blockers))
    return not enforced_blockers, blockers, enforced_blockers


def _semantic_cache_policy(draft: DecisionDraft) -> tuple[bool, list[str]]:
    if draft.optimization_plan is None:
        return False, ["planner_missing"]
    gate = evaluate_cache_eligibility("semantic_cache", draft.optimization_plan.classification)
    return gate.allowed, list(gate.blockers)


async def _resolve_openai_optimizations(
    db: AsyncSession,
    project: Project,
    parsed: ParsedClientRequest,
    requested_provider: str,
    request_id: str,
    bypass: bool,
    draft: DecisionDraft,
    request_facts: RequestFacts,
) -> OpenAIOptimizationState:
    # A request joins at most one lever's holdback experiment so savings never
    # double-count: model routing first, token trim only when no route applies.
    model = parsed.model or ""
    body = parsed.body
    if bypass:
        return _openai_passthrough_state(body, model, requested_provider)

    outcome_priors = await _safe_outcome_priors(db, project.id, model)
    decision = await routing.resolve_route(db, project.id, model, body, requested_provider=requested_provider)
    if _has_cross_provider_route(decision, model, requested_provider):
        return await _resolve_openai_route_state(
            db=db,
            project=project,
            parsed=parsed,
            requested_provider=requested_provider,
            request_id=request_id,
            body=body,
            model=model,
            bypass=bypass,
            decision=decision,
            draft=draft,
            request_facts=request_facts,
            outcome_priors=outcome_priors,
        )

    draft.add_runtime_trace(
        stage="routing",
        lever=(decision.lever if decision else None) or "model_routing",
        action="skipped",
        reason_code="routing_no_applicable_policy",
        policy_id=decision.policy_id if decision else None,
        source_recommendation_id=decision.source_recommendation_id if decision else None,
    )
    return await _resolve_openai_trim_state(
        db=db,
        project=project,
        body=body,
        model=model,
        requested_provider=requested_provider,
        bypass=bypass,
        draft=draft,
        request_facts=request_facts,
        outcome_priors=outcome_priors,
    )


def _openai_passthrough_state(body: dict, model: str, requested_provider: str) -> OpenAIOptimizationState:
    return OpenAIOptimizationState(body, model, requested_provider, None, None, None, None, None, False)


def _has_cross_provider_route(decision: Any, model: str, requested_provider: str) -> bool:
    return bool(
        decision
        and decision.candidate_model
        and (decision.candidate_model != model or decision.candidate_provider != requested_provider)
    )


async def _resolve_openai_route_state(
    *,
    db: AsyncSession,
    project: Project,
    parsed: ParsedClientRequest,
    requested_provider: str,
    request_id: str,
    body: dict,
    model: str,
    bypass: bool,
    decision: Any,
    draft: DecisionDraft,
    request_facts: RequestFacts,
    outcome_priors: tuple,
) -> OpenAIOptimizationState:
    ineligibility = cross_provider_ineligibility(
        parsed,
        requested_provider=requested_provider,
        candidate_provider=decision.candidate_provider,
    )
    if ineligibility is not None:
        return await _openai_route_ineligible_state(
            db=db,
            project=project,
            parsed=parsed,
            requested_provider=requested_provider,
            request_id=request_id,
            body=body,
            model=model,
            bypass=bypass,
            decision=decision,
            ineligibility=ineligibility,
            draft=draft,
            request_facts=request_facts,
            outcome_priors=outcome_priors,
        )

    draft.route_eligible = True
    _tag_route_policy(draft, decision)
    _attach_openai_routing_plan(
        draft,
        body=body,
        request_facts=request_facts,
        requested_provider=requested_provider,
        model=model,
        bypass=bypass,
        decision=decision,
        outcome_priors=outcome_priors,
    )
    rejected = _rejected_candidate(draft, "model_routing")
    if rejected is not None:
        draft.route_eligible = False
        draft.route_ineligible_reason = rejected.reason_code
        _trace_rejected_candidate(
            draft,
            stage="routing",
            lever=decision.lever or "model_routing",
            candidate=rejected,
            policy_id=decision.policy_id,
            source_recommendation_id=decision.source_recommendation_id,
        )
        return _openai_passthrough_state(body, model, requested_provider)
    return _openai_route_arm_state(body, model, requested_provider, decision, draft)


async def _openai_route_ineligible_state(
    *,
    db: AsyncSession,
    project: Project,
    parsed: ParsedClientRequest,
    requested_provider: str,
    request_id: str,
    body: dict,
    model: str,
    bypass: bool,
    decision: Any,
    ineligibility,
    draft: DecisionDraft,
    request_facts: RequestFacts,
    outcome_priors: tuple,
) -> OpenAIOptimizationState:
    draft.route_eligible = False
    draft.route_ineligible_reason = ineligibility.reason_code
    _tag_route_policy(draft, decision)
    draft.add_runtime_trace(
        stage="routing",
        lever=decision.lever or "model_routing",
        action="skipped",
        reason_code=ineligibility.reason_code,
        enforced=True,
        policy_id=decision.policy_id,
        source_recommendation_id=decision.source_recommendation_id,
        detail={
            "candidate_provider": decision.candidate_provider,
            "candidate_model": decision.candidate_model,
            "route_eligible": False,
        },
    )
    _attach_openai_routing_plan(
        draft,
        body=body,
        request_facts=request_facts,
        requested_provider=requested_provider,
        model=model,
        bypass=bypass,
        decision=decision,
        outcome_priors=outcome_priors,
    )
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
    return _openai_passthrough_state(body, model, requested_provider)


def _tag_route_policy(draft: DecisionDraft, decision: Any) -> None:
    draft.lever = decision.lever
    draft.policy_id = decision.policy_id
    draft.source_recommendation_id = decision.source_recommendation_id
    # Bandit selection telemetry (shadow or active): which cleared candidate the
    # sampler picked and why. Content-free; absent when the bandit did not run.
    bandit_trace = getattr(decision, "bandit_trace", None)
    if bandit_trace:
        draft.add_runtime_trace(
            stage="bandit_routing",
            lever=decision.lever or "model_routing",
            action="selected",
            reason_code=str(bandit_trace.get("reason") or "unknown"),
            enforced=bandit_trace.get("mode") == "active",
            policy_id=decision.policy_id,
            detail=bandit_trace,
        )


def _attach_openai_routing_plan(
    draft: DecisionDraft,
    *,
    body: dict,
    request_facts: RequestFacts,
    requested_provider: str,
    model: str,
    bypass: bool,
    decision: Any,
    outcome_priors: tuple = (),
) -> None:
    _attach_observe_plan(
        draft,
        body=body,
        request_facts=request_facts,
        provider=requested_provider,
        model=model,
        optimize_enabled=not bypass,
        exact_cache_enabled=settings.proxy_cache_enabled,
        semantic_cache_enabled=settings.proxy_cache_enabled and settings.semantic_cache_enabled,
        routing_policy_present=True,
        routing_policy_id=str(decision.policy_id) if decision.policy_id else None,
        outcome_priors=outcome_priors,
    )


def _openai_route_arm_state(
    body: dict,
    model: str,
    requested_provider: str,
    decision: Any,
    draft: DecisionDraft,
) -> OpenAIOptimizationState:
    arm = routing.assign_arm(decision.holdback_percent)
    routed = arm == routing.ARM_TREATMENT
    draft.add_runtime_trace(
        stage="routing",
        lever=decision.lever or "model_routing",
        action="applied" if routed else "control",
        reason_code="routing_treatment" if routed else "holdback_control",
        policy_id=decision.policy_id,
        source_recommendation_id=decision.source_recommendation_id,
        detail={
            "arm": arm,
            "candidate_provider": decision.candidate_provider,
            "candidate_model": decision.candidate_model,
            "requested_provider": requested_provider,
            "requested_model": model,
        },
    )
    return OpenAIOptimizationState(
        body,
        decision.candidate_model if routed else model,
        decision.candidate_provider if routed else requested_provider,
        model if routed else None,
        requested_provider if routed else None,
        arm,
        model,
        decision.candidate_model,
        False,
    )


async def _resolve_openai_trim_state(
    *,
    db: AsyncSession,
    project: Project,
    body: dict,
    model: str,
    requested_provider: str,
    bypass: bool,
    draft: DecisionDraft,
    request_facts: RequestFacts,
    outcome_priors: tuple,
) -> OpenAIOptimizationState:
    tdecision = await trim.resolve_trim(db, project.id, model)
    if not tdecision:
        draft.add_runtime_trace(
            stage="trim",
            lever=trim.LEVER,
            action="skipped",
            reason_code="trim_policy_missing",
        )
        # No trim policy: the other body transform (prompt compression) gets its
        # turn. Activation guarantees at most one transform is live per model.
        return await _resolve_openai_compression_state(
            db=db,
            project=project,
            body=body,
            model=model,
            requested_provider=requested_provider,
            bypass=bypass,
            draft=draft,
            request_facts=request_facts,
            outcome_priors=outcome_priors,
        )

    draft.lever = trim.LEVER
    draft.policy_id = tdecision.policy_id
    draft.source_recommendation_id = tdecision.source_recommendation_id
    _attach_observe_plan(
        draft,
        body=body,
        request_facts=request_facts,
        provider=requested_provider,
        model=model,
        optimize_enabled=not bypass,
        exact_cache_enabled=settings.proxy_cache_enabled,
        semantic_cache_enabled=settings.proxy_cache_enabled and settings.semantic_cache_enabled,
        trim_policy_present=True,
        trim_policy_id=str(tdecision.policy_id) if tdecision.policy_id else None,
        outcome_priors=outcome_priors,
    )
    rejected = _rejected_candidate(draft, "token_trim")
    if rejected is not None:
        _trace_rejected_candidate(
            draft,
            stage="trim",
            lever=trim.LEVER,
            candidate=rejected,
            policy_id=tdecision.policy_id,
            source_recommendation_id=tdecision.source_recommendation_id,
        )
        return _openai_passthrough_state(body, model, requested_provider)
    arm = routing.assign_arm(tdecision.holdback_percent)
    if arm != routing.ARM_TREATMENT:
        draft.add_runtime_trace(
            stage="trim",
            lever=trim.LEVER,
            action="control",
            reason_code="holdback_control",
            policy_id=tdecision.policy_id,
            source_recommendation_id=tdecision.source_recommendation_id,
            detail={"arm": arm, "requested_model": model},
        )
        return OpenAIOptimizationState(body, model, requested_provider, None, None, arm, model, model, False)
    trimmed_body, trim_applied = trim.apply_trim(body, tdecision.params)
    draft.trim_applied = trim_applied
    draft.add_runtime_trace(
        stage="trim",
        lever=trim.LEVER,
        action="applied" if trim_applied else "noop",
        reason_code="trim_treatment_applied" if trim_applied else "trim_no_changes",
        policy_id=tdecision.policy_id,
        source_recommendation_id=tdecision.source_recommendation_id,
        detail={"arm": arm, "requested_model": model},
    )
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


async def _resolve_openai_compression_state(
    *,
    db: AsyncSession,
    project: Project,
    body: dict,
    model: str,
    requested_provider: str,
    bypass: bool,
    draft: DecisionDraft,
    request_facts: RequestFacts,
    outcome_priors: tuple,
) -> OpenAIOptimizationState:
    """Prompt-compression state: mirror of the trim state for the learned lever.

    On treatment, the approved rewrite is substituted only when the request's
    system prompt hashes exactly to the evaluated original; a non-matching
    request forwards untouched and is traced as a noop, so the lever never
    compresses anything it did not prove."""
    cdecision = await compression.resolve_compression(db, project.id, model)
    if not cdecision or cdecision.artifact_id is None:
        draft.add_runtime_trace(
            stage="compression",
            lever=compression.LEVER,
            action="skipped",
            reason_code="compression_policy_missing",
        )
        return _openai_passthrough_state(body, model, requested_provider)

    draft.lever = compression.LEVER
    draft.policy_id = cdecision.policy_id
    draft.source_recommendation_id = cdecision.source_recommendation_id
    _attach_observe_plan(
        draft,
        body=body,
        request_facts=request_facts,
        provider=requested_provider,
        model=model,
        optimize_enabled=not bypass,
        exact_cache_enabled=settings.proxy_cache_enabled,
        semantic_cache_enabled=settings.proxy_cache_enabled and settings.semantic_cache_enabled,
        compression_policy_present=True,
        compression_policy_id=str(cdecision.policy_id) if cdecision.policy_id else None,
        outcome_priors=outcome_priors,
    )
    rejected = _rejected_candidate(draft, "prompt_compression")
    if rejected is not None:
        _trace_rejected_candidate(
            draft,
            stage="compression",
            lever=compression.LEVER,
            candidate=rejected,
            policy_id=cdecision.policy_id,
            source_recommendation_id=cdecision.source_recommendation_id,
        )
        return _openai_passthrough_state(body, model, requested_provider)
    arm = routing.assign_arm(cdecision.holdback_percent)
    if arm != routing.ARM_TREATMENT:
        draft.add_runtime_trace(
            stage="compression",
            lever=compression.LEVER,
            action="control",
            reason_code="holdback_control",
            policy_id=cdecision.policy_id,
            source_recommendation_id=cdecision.source_recommendation_id,
            detail={"arm": arm, "requested_model": model},
        )
        return OpenAIOptimizationState(body, model, requested_provider, None, None, arm, model, model, False)
    artifact = await compression.load_artifact(db, cdecision.artifact_id)
    if artifact is None:
        draft.add_runtime_trace(
            stage="compression",
            lever=compression.LEVER,
            action="error",
            reason_code="compression_artifact_unavailable",
            detail={"fail_open": True},
        )
        return _openai_passthrough_state(body, model, requested_provider)
    original_hash, compressed_text = artifact
    compressed_body, applied = compression.apply_compression(body, original_hash, compressed_text)
    draft.compression_applied = applied
    draft.add_runtime_trace(
        stage="compression",
        lever=compression.LEVER,
        action="applied" if applied else "noop",
        reason_code="compression_treatment_applied" if applied else "compression_prompt_mismatch",
        policy_id=cdecision.policy_id,
        source_recommendation_id=cdecision.source_recommendation_id,
        detail={"arm": arm, "requested_model": model},
    )
    return OpenAIOptimizationState(
        compressed_body,
        model,
        requested_provider,
        None,
        None,
        arm,
        model,
        model,
        False,
        applied,
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
    headers = {
        "X-Varsten-Mode": "optimize",
        "X-Varsten-Cache": cache_label,
        origin.ORIGIN_HEADER: origin.ORIGIN_VARSTEN,
    }
    if draft is not None:
        headers["X-Varsten-Request-Id"] = draft.request_id
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
    _attach_observe_plan(
        draft,
        body=parsed.body,
        request_facts=parsed.request_facts,
        provider=provider,
        model=parsed.model or "",
        optimize_enabled=not bypass and not observe_only,
        exact_cache_enabled=False,
        semantic_cache_enabled=False,
        outcome_priors=await _safe_outcome_priors(db, project.id, parsed.model or ""),
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
    if _native_route_operation_ineligible(parsed):
        await _trace_native_operation_ineligible(db, project, parsed, requested_provider, request_id, draft)
        return None

    model = parsed.model
    assert model is not None
    decision = await routing.resolve_route(
        db,
        project.id,
        model,
        parsed.body,
        requested_provider=requested_provider,
    )
    if _native_route_policy_missing(decision, requested_provider):
        _trace_native_route_no_policy(draft, decision)
        return None
    assert decision is not None

    outcome_priors = await _safe_outcome_priors(db, project.id, model)
    if not await _native_route_allowed(
        db,
        project,
        parsed,
        requested_provider,
        request_id,
        decision,
        draft,
        outcome_priors,
    ):
        return None

    arm = routing.assign_arm(decision.holdback_percent)
    _trace_native_route_arm(draft, parsed, requested_provider, decision, arm)
    if arm != routing.ARM_TREATMENT:
        return None

    return await _forward_native_cross_provider_route(
        db=db,
        project=project,
        api_key_id=api_key_id,
        parsed=parsed,
        requested_provider=requested_provider,
        decision=decision,
        breaker=breaker,
        arm=arm,
        started=started,
        draft=draft,
    )


def _native_route_operation_ineligible(parsed: ParsedClientRequest) -> bool:
    return parsed.operation not in {"messages", "generate_content", "stream_generate_content"} or not parsed.model


async def _trace_native_operation_ineligible(
    db: AsyncSession,
    project: Project,
    parsed: ParsedClientRequest,
    requested_provider: str,
    request_id: str,
    draft: DecisionDraft,
) -> None:
    draft.add_runtime_trace(
        stage="routing",
        lever="model_routing",
        action="skipped",
        reason_code="native_operation_ineligible",
        enforced=True,
        detail={"operation": parsed.operation},
    )
    await _audit_native_route_ineligibility(db, project, parsed, requested_provider, request_id)


def _native_route_policy_missing(decision: Any, requested_provider: str) -> bool:
    return decision is None or decision.candidate_provider == requested_provider


def _trace_native_route_no_policy(draft: DecisionDraft, decision: Any) -> None:
    draft.add_runtime_trace(
        stage="routing",
        lever=(decision.lever if decision else None) or "model_routing",
        action="skipped",
        reason_code="routing_no_applicable_policy",
        policy_id=decision.policy_id if decision else None,
        source_recommendation_id=decision.source_recommendation_id if decision else None,
    )


async def _native_route_allowed(
    db: AsyncSession,
    project: Project,
    parsed: ParsedClientRequest,
    requested_provider: str,
    request_id: str,
    decision: Any,
    draft: DecisionDraft,
    outcome_priors: tuple,
) -> bool:
    ineligibility = cross_provider_ineligibility(
        parsed,
        requested_provider=requested_provider,
        candidate_provider=decision.candidate_provider,
    )
    if ineligibility is not None:
        await _reject_native_route_ineligibility(
            db=db,
            project=project,
            parsed=parsed,
            requested_provider=requested_provider,
            request_id=request_id,
            decision=decision,
            ineligibility=ineligibility,
            draft=draft,
            outcome_priors=outcome_priors,
        )
        return False

    draft.route_eligible = True
    _tag_route_policy(draft, decision)
    _attach_native_routing_plan(
        draft,
        parsed=parsed,
        requested_provider=requested_provider,
        decision=decision,
        outcome_priors=outcome_priors,
    )
    return not _native_route_rejected_by_plan(draft, decision)


async def _reject_native_route_ineligibility(
    *,
    db: AsyncSession,
    project: Project,
    parsed: ParsedClientRequest,
    requested_provider: str,
    request_id: str,
    decision: Any,
    ineligibility,
    draft: DecisionDraft,
    outcome_priors: tuple,
) -> None:
    draft.route_eligible = False
    draft.route_ineligible_reason = ineligibility.reason_code
    _tag_route_policy(draft, decision)
    draft.add_runtime_trace(
        stage="routing",
        lever=decision.lever or "model_routing",
        action="skipped",
        reason_code=ineligibility.reason_code,
        enforced=True,
        policy_id=decision.policy_id,
        source_recommendation_id=decision.source_recommendation_id,
        detail={
            "candidate_provider": decision.candidate_provider,
            "candidate_model": decision.candidate_model,
            "route_eligible": False,
        },
    )
    _attach_native_routing_plan(
        draft,
        parsed=parsed,
        requested_provider=requested_provider,
        decision=decision,
        outcome_priors=outcome_priors,
    )
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


def _attach_native_routing_plan(
    draft: DecisionDraft,
    *,
    parsed: ParsedClientRequest,
    requested_provider: str,
    decision: Any,
    outcome_priors: tuple = (),
) -> None:
    _attach_observe_plan(
        draft,
        body=parsed.body,
        request_facts=parsed.request_facts,
        provider=requested_provider,
        model=parsed.model or "",
        optimize_enabled=True,
        exact_cache_enabled=False,
        semantic_cache_enabled=False,
        routing_policy_present=True,
        routing_policy_id=str(decision.policy_id) if decision.policy_id else None,
        outcome_priors=outcome_priors,
    )


def _native_route_rejected_by_plan(draft: DecisionDraft, decision: Any) -> bool:
    rejected = _rejected_candidate(draft, "model_routing")
    if rejected is None:
        return False
    draft.route_eligible = False
    draft.route_ineligible_reason = rejected.reason_code
    _trace_rejected_candidate(
        draft,
        stage="routing",
        lever=decision.lever or "model_routing",
        candidate=rejected,
        policy_id=decision.policy_id,
        source_recommendation_id=decision.source_recommendation_id,
    )
    return True


def _trace_native_route_arm(
    draft: DecisionDraft,
    parsed: ParsedClientRequest,
    requested_provider: str,
    decision: Any,
    arm: str,
) -> None:
    treatment = arm == routing.ARM_TREATMENT
    draft.add_runtime_trace(
        stage="routing",
        lever=decision.lever or "model_routing",
        action="applied" if treatment else "control",
        reason_code="routing_treatment" if treatment else "holdback_control",
        policy_id=decision.policy_id,
        source_recommendation_id=decision.source_recommendation_id,
        detail={
            "arm": arm,
            "candidate_provider": decision.candidate_provider,
            "candidate_model": decision.candidate_model,
            "requested_provider": requested_provider,
            "requested_model": parsed.model,
        },
    )


async def _forward_native_cross_provider_route(
    *,
    db: AsyncSession,
    project: Project,
    api_key_id,
    parsed: ParsedClientRequest,
    requested_provider: str,
    decision: Any,
    breaker,
    arm: str,
    started: float,
    draft: DecisionDraft,
) -> Response | None:
    adapter = get_adapter(decision.candidate_provider)
    client_key = provider_key_for_project(project.id, adapter.provider)
    if not client_key:
        logger.warning(
            "candidate provider key missing; forwarding incumbent",
            extra={"project_id": str(project.id), "provider": adapter.provider},
        )
        draft.add_runtime_trace(
            stage="routing",
            lever=decision.lever or "model_routing",
            action="fallback",
            reason_code="candidate_provider_key_missing",
            enforced=True,
            policy_id=decision.policy_id,
            source_recommendation_id=decision.source_recommendation_id,
            detail={"candidate_provider": adapter.provider, "candidate_model": decision.candidate_model},
        )
        return None

    openai_body = request_to_openai_shape(parsed)
    headers = _native_cross_provider_headers(parsed, requested_provider, adapter, decision, arm)
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

    return await _native_cross_provider_once(
        db=db,
        project=project,
        api_key_id=api_key_id,
        adapter=adapter,
        parsed=parsed,
        openai_body=openai_body,
        client_key=client_key,
        requested_provider=requested_provider,
        decision=decision,
        breaker=breaker,
        arm=arm,
        started=started,
        draft=draft,
        headers=headers,
    )


def _native_cross_provider_headers(
    parsed: ParsedClientRequest,
    requested_provider: str,
    adapter,
    decision: Any,
    arm: str,
) -> dict[str, str]:
    return {
        "X-Varsten-Mode": "optimize",
        "X-Varsten-Cache": "bypass",
        "X-Varsten-Routed": _routed_header(
            requested_provider,
            parsed.model or "",
            adapter.provider,
            decision.candidate_model,
        ),
        "X-Varsten-Arm": arm,
        origin.ORIGIN_HEADER: origin.ORIGIN_PROVIDER,
    }


async def _native_cross_provider_once(
    *,
    db: AsyncSession,
    project: Project,
    api_key_id,
    adapter,
    parsed: ParsedClientRequest,
    openai_body: dict,
    client_key: str,
    requested_provider: str,
    decision: Any,
    breaker,
    arm: str,
    started: float,
    draft: DecisionDraft,
    headers: dict[str, str],
) -> Response:
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
        cache_model=parsed.model or "",
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
    fallback_used: bool = False,
    fallback_reason: str | None = None,
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

    if draft is not None and event is not None:
        _trace_cache_store_decision(
            draft,
            store_cache=store_cache,
            response_payload=response_payload,
            embedding=embedding,
        )

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
                fallback_used=fallback_used,
                fallback_reason=fallback_reason,
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


def _trace_cache_store_decision(
    draft: DecisionDraft,
    *,
    store_cache: bool,
    response_payload: dict,
    embedding: list[float] | None,
) -> None:
    if not settings.proxy_cache_enabled:
        draft.add_runtime_trace(
            stage="cache_store_decision",
            lever="exact_cache",
            action="skipped",
            reason_code="cache_disabled",
            enforced=True,
        )
        return
    if not store_cache:
        draft.add_runtime_trace(
            stage="cache_store_decision",
            lever="exact_cache",
            action="skipped",
            reason_code="cache_store_not_allowed",
            enforced=True,
        )
        return
    if not response_payload:
        draft.add_runtime_trace(
            stage="cache_store_decision",
            lever="exact_cache",
            action="skipped",
            reason_code="empty_response_payload",
            enforced=True,
        )
        return
    draft.add_runtime_trace(
        stage="cache_store_decision",
        lever="exact_cache",
        action="allowed",
        reason_code="cache_store_allowed",
        detail={"embedding_present": embedding is not None},
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
    # The shared pooled client: a warm keep-alive connection spares this miss the
    # upstream TLS handshake. Per-request timeout; never closed here.
    client = http_client.get_client()

    # Retries wrap only the connection attempt: a provider failure (connect error or
    # 5xx/429) before the first byte is retried with backoff, but once any byte has
    # streamed to the client we never retry (that would duplicate a partial
    # completion). The breaker records one outcome per request.
    delays = resilience.backoff_delays()
    deadline = time.monotonic() + settings.proxy_retry_budget_seconds
    streamed = False

    for attempt in range(1 + len(delays)):
        retry_delay: float | None = None
        try:
            async with asyncio.timeout(settings.proxy_stream_total_timeout_seconds):
                async with client.stream(
                    "POST",
                    adapter.request_url(model=upstream_model or model, stream=True),
                    headers=_with_idempotency(adapter.headers(client_key), idempotency_key),
                    json=upstream_body,
                    timeout=timeout,
                ) as resp:
                    if resp.status_code != 200:
                        # Provider failure (5xx/429): retry within budget before any
                        # byte; a 4xx is the client's mistake and is relayed.
                        if is_upstream_failure(resp.status_code):
                            if attempt < len(delays) and time.monotonic() < deadline:
                                await resp.aread()
                                retry_delay = resilience.retry_after_seconds(
                                    resp.headers.get("retry-after"), delays[attempt]
                                )
                            else:
                                breaker.record_failure()
                                yield await resp.aread()
                                return
                        else:
                            breaker.record_success()
                            yield await resp.aread()
                            return
                    else:
                        breaker.record_success()
                        async for chunk in resp.aiter_bytes():
                            if first_byte_at is None:
                                first_byte_at = time.perf_counter()  # time-to-first-byte
                            streamed = True
                            for out in translator.push(chunk):
                                yield out
        except (httpx.RequestError, TimeoutError) as exc:
            # OpenAI unreachable/slow/hung (httpx read timeout or the wall-clock
            # cap). Retry only before the first byte; otherwise emit a clean SSE
            # error instead of a stack trace and count it against the breaker.
            if not streamed and attempt < len(delays) and time.monotonic() < deadline:
                retry_delay = delays[attempt]
            else:
                breaker.record_failure()
                logger.warning(
                    "upstream stream failed", extra={"project_id": str(project.id), "error": exc.__class__.__name__}
                )
                yield f'data: {{"error":{{"message":"upstream request failed: {exc.__class__.__name__}","type":"varsten_upstream_error"}}}}\n\n'.encode()
                yield b"data: [DONE]\n\n"
                return
        if retry_delay is not None:
            await asyncio.sleep(retry_delay)
            continue
        break  # streamed to completion -- proceed to post-stream capture below

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
    client = http_client.get_client()
    upstream_model_used = upstream_model or model
    upstream_body = adapter.prepare_request(body, model=upstream_model_used, stream=False)
    # Retries wrap the connection attempt (non-streaming, so nothing has reached the
    # client yet): connect errors and 429/5xx are retried with backoff before the
    # client ever sees a failure. The breaker records one outcome per request below.
    resp, exc = await resilience.post_with_retry(
        client,
        adapter.request_url(model=upstream_model_used, stream=False),
        headers=_with_idempotency(adapter.headers(client_key), idempotency_key),
        json=upstream_body,
        timeout=settings.proxy_upstream_timeout_seconds,
    )

    if resp is not None and resp.status_code == 200:
        breaker.record_success()
        latency_ms = int((time.perf_counter() - started) * 1000) if started else None
        result = adapter.parse_completion(resp.json())
        # The client always gets the OpenAI dialect; for an OpenAI upstream this is
        # the original payload reused verbatim, for any other provider it is the
        # canonical form rendered to OpenAI shape.
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

    # A 4xx (other than 429) is the client's request, not the provider faltering:
    # relay it unchanged, upstream stays healthy on the breaker.
    if resp is not None and not is_upstream_failure(resp.status_code):
        breaker.record_success()
        try:
            detail = resp.json()
        except ValueError:
            detail = {"error": resp.text}
        return JSONResponse(detail, status_code=resp.status_code, headers=headers)

    # Upstream failure (5xx/429 after retries) or unreachable: one breaker failure,
    # then try a same-provider fallback model before giving up.
    breaker.record_failure()
    logger.warning(
        "upstream request failed after retries",
        extra={
            "project_id": str(project.id),
            "error": exc.__class__.__name__ if exc else (resp.status_code if resp is not None else "no_response"),
        },
    )
    fallback = await _forward_fallback(
        db,
        project,
        api_key_id,
        client,
        adapter,
        body,
        model,
        cache_key,
        breaker,
        embedding,
        headers,
        started,
        upstream_model_used,
        client_key,
        idempotency_key,
        draft=draft,
    )
    if fallback is not None:
        return fallback
    if resp is not None:
        try:
            detail = resp.json()
        except ValueError:
            detail = {"error": resp.text}
        return JSONResponse(detail, status_code=resp.status_code, headers=headers)
    return origin.varsten_error(
        code=origin.CODE_UPSTREAM_UNREACHABLE,
        type_="varsten_upstream_error",
        message=f"upstream request failed: {exc.__class__.__name__ if exc else 'upstream_error'}",
        status_code=status.HTTP_502_BAD_GATEWAY,
        headers=headers,
    )


async def _forward_fallback(
    db,
    project,
    api_key_id,
    client,
    adapter,
    body,
    model,
    cache_key,
    breaker,
    embedding,
    headers,
    started,
    failed_model,
    client_key,
    idempotency_key,
    *,
    draft=None,
) -> JSONResponse | None:
    """After retries on the primary are exhausted, try a configured degradation
    model on the same provider so the request still gets an answer. Reliability,
    not optimization: recorded as fallback_used with zero claimed savings (no
    routed_from, so no saved_usd), and the response is tagged so the SDK/client can
    see it was degraded. Returns None when no fallback is configured or the fallback
    also fails (caller relays the error)."""
    fb_model = resilience.fallback_model(project.id, failed_model)
    if not fb_model:
        return None
    fb_body = adapter.prepare_request(body, model=fb_model, stream=False)
    fb_resp, _ = await resilience.post_with_retry(
        client,
        adapter.request_url(model=fb_model, stream=False),
        headers=_with_idempotency(adapter.headers(client_key), idempotency_key),
        json=fb_body,
        timeout=settings.proxy_upstream_timeout_seconds,
    )
    if fb_resp is None or fb_resp.status_code != 200:
        return None
    breaker.record_success()
    latency_ms = int((time.perf_counter() - started) * 1000) if started else None
    result = adapter.parse_completion(fb_resp.json())
    payload = canonical.completion_payload(result)
    logger.info(
        "served via fallback model",
        extra={"project_id": str(project.id), "from": failed_model, "to": fb_model},
    )
    await _capture(
        db,
        project,
        api_key_id,
        provider=adapter.provider,
        model=result.model or fb_model,
        cache_model=model,
        response_payload=payload,
        cache_key=cache_key,
        in_tok=result.usage.input_tokens,
        out_tok=result.usage.output_tokens,
        cached_tok=result.usage.provider_cached_input_tokens,
        # Never cache or optimize a degraded fallback answer under the primary key.
        store_cache=False,
        embedding=embedding,
        body=body,
        latency_ms=latency_ms,
        draft=draft,
        fallback_used=True,
        fallback_reason="upstream_failure",
    )
    return JSONResponse(payload, headers={**headers, "X-Varsten-Fallback": fb_model})
