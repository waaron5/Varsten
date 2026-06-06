"""Phase 1 inline proxy: OpenAI chat completions mirror.

POST /v1/chat/completions
  - authenticate with the vk_ key, resolve the project's OpenAI key
  - on a semantic-cache hit, serve the stored completion ($0, no upstream call)
  - on a miss, stream the OpenAI response straight through (SSE preserved) while
    capturing token/billing metadata in volatile memory, then write the ledger
    row and (optionally) cache the result
"""

import asyncio

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ApiKeyContext, require_api_key_context_async
from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import get_async_db
from app.eval import capture as eval_capture
from app.models import Project
from app.proxy import cache, quality, routing, trim
from app.proxy.circuit import get_breaker, is_upstream_failure
from app.proxy.embedding import embed, embedding_input
from app.proxy.keys import openai_key_for_project
from app.proxy.ledger import record_proxy_usage
from app.proxy.providers import canonical, get_adapter

router = APIRouter(tags=["proxy"])
logger = get_logger("varsten.proxy")

SSE_MEDIA_TYPE = "text/event-stream"


def _is_bypassed(project: Project) -> bool:
    """The kill switch: global (operator) OR per-project (customer). When engaged,
    Varsten forwards straight through with no optimization, still metered."""
    return settings.proxy_kill_switch or project.proxy_bypass_enabled


@router.post("/chat/completions")
async def chat_completions(
    request: Request,
    background_tasks: BackgroundTasks,
    api_context: ApiKeyContext = Depends(require_api_key_context_async),
    db: AsyncSession = Depends(get_async_db),
):
    project = api_context.project
    api_key_id = api_context.api_key.id

    # The upstream provider is resolved through the adapter registry. Phase 1 is
    # OpenAI-only; the routing policy will select this per-request once more
    # providers are registered. The router below is provider-agnostic.
    adapter = get_adapter(settings.proxy_default_provider)

    client_key = openai_key_for_project(project.id)
    if not client_key:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="no provider key configured for this project",
        )

    body = await request.json()
    stream = bool(body.get("stream", False))
    model = body.get("model", "")
    bypass = _is_bypassed(project)
    cache_key = cache.compute_cache_key(body)

    # --- cache: exact-hash fast path, then the optional semantic layer. Skipped
    # when bypassed. Fail-open throughout: a cache/embedding failure must never
    # block forwarding. ---
    embedding: list[float] | None = None
    cache_on = not bypass and settings.proxy_cache_enabled
    if cache_on:
        # 1) Exact hash: byte-identical repeats serve instantly, no embedding call.
        # This is the Day One lever and adds zero latency to a miss.
        try:
            entry = await cache.get_cached(db, project.id, cache_key)
        except Exception:
            logger.exception("cache lookup failed; forwarding", extra={"project_id": str(project.id)})
            entry = None
        if entry is not None:
            return _serve_cache_hit(db, project, api_key_id, entry, stream, "hit", background_tasks)

        # 2) Semantic layer (optional, on top of exact hash): embed the prompt and
        # find the nearest cached answer. Off by default so there is no embedding
        # round-trip on the miss path. When on, the embedding is reused for storage
        # on a miss, so we embed at most once.
        if settings.semantic_cache_enabled:
            try:
                embedding = await embed(embedding_input(body), client_key)
                sem = await cache.semantic_search(db, project.id, model, embedding, settings.semantic_cache_threshold)
            except Exception:
                logger.exception("semantic lookup failed; forwarding", extra={"project_id": str(project.id)})
                sem = None
            if sem is not None:
                return _serve_cache_hit(db, project, api_key_id, sem, stream, "semantic", background_tasks)

    # --- cheaper-model routing with a live holdback A/B. If an applied+eval-passed
    # rule maps this model to a cheaper candidate, randomly assign the request to
    # the control arm (held back on the incumbent) or treatment (routed to the
    # candidate). Both arms are metered so savings are a measured A/B, not modelled.
    # Skipped when bypassed. Fail-open: resolve returns None and we forward. ---
    # A request joins at most one lever's holdback experiment so savings never
    # double-count. Routing claims it first; if no routing swap applies to this
    # model, token-trim may run its own A/B (control = untrimmed, treatment =
    # trimmed body, same model, fewer input tokens).
    routed_from: str | None = None
    upstream_model = model
    arm: str | None = None
    exp_from: str | None = None
    exp_to: str | None = None
    trim_applied = False
    if not bypass:
        decision = await routing.resolve_route(db, project.id, model, body)
        if decision and decision.candidate_model and decision.candidate_model != model:
            exp_from, exp_to = model, decision.candidate_model
            arm = routing.assign_arm(decision.holdback_percent)
            if arm == routing.ARM_TREATMENT:
                routed_from = model
                upstream_model = decision.candidate_model
        else:
            tdecision = await trim.resolve_trim(db, project.id, model)
            if tdecision:
                # Same-model experiment: from == to marks a token-trim A/B.
                exp_from = exp_to = model
                arm = routing.assign_arm(tdecision.holdback_percent)
                if arm == routing.ARM_TREATMENT:
                    body, trim_applied = trim.apply_trim(body, tdecision.params)

    # --- forward to OpenAI (cache miss, or bypassed). store_cache off when bypassed ---
    mode = "bypass" if bypass else "optimize"
    headers = {"X-Varsten-Mode": mode, "X-Varsten-Cache": "bypass" if bypass else "miss"}
    if routed_from:
        headers["X-Varsten-Routed"] = f"{routed_from}->{upstream_model}"
    if trim_applied:
        headers["X-Varsten-Trim"] = "applied"
    if arm:
        headers["X-Varsten-Arm"] = arm

    # Circuit breaker: if the upstream has been failing, fail fast instead of
    # making this request wait the full timeout. Cache hits above are unaffected.
    breaker = get_breaker(project.id)
    if not breaker.allow():
        return JSONResponse(
            {"error": {"message": "upstream temporarily unavailable (circuit open)", "type": "varsten_circuit_open"}},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            headers={**headers, "X-Varsten-Circuit": "open"},
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
                embedding,
                store_cache=not bypass,
                upstream_model=upstream_model,
                routed_from=routed_from,
                arm=arm,
                exp_from=exp_from,
                exp_to=exp_to,
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
        embedding,
        store_cache=not bypass,
        headers=headers,
        upstream_model=upstream_model,
        routed_from=routed_from,
        arm=arm,
        exp_from=exp_from,
        exp_to=exp_to,
    )


async def _meter_cache_hit(db, project, api_key_id, entry) -> None:
    """Record the hit and the $0 ledger row. Runs in a BackgroundTask after the
    response is sent (but before the request session is torn down), so the cache
    hit's time-to-first-byte never includes these DB commits. Best-effort: a
    failure here is logged, never surfaced to the client whose response already
    went out."""
    try:
        await cache.record_hit(db, entry)
        await record_proxy_usage(
            db,
            project,
            api_key_id,
            model=entry.model,
            input_tokens=entry.input_tokens,
            output_tokens=entry.output_tokens,
            cached_input_tokens=0,
            cache_hit=True,
        )
    except Exception:
        logger.exception("cache-hit metering failed", extra={"project_id": str(project.id)})


def _serve_cache_hit(db, project, api_key_id, entry, stream, cache_label, background_tasks: BackgroundTasks):
    """Serve a cache entry (exact or semantic) immediately. Hit accounting and the
    $0 ledger row are deferred to a BackgroundTask so no DB commit sits on the
    critical path; the cached bytes are already in memory."""
    background_tasks.add_task(_meter_cache_hit, db, project, api_key_id, entry)
    headers = {"X-Varsten-Mode": "optimize", "X-Varsten-Cache": cache_label}
    if stream:
        return StreamingResponse(
            iter(list(canonical.to_openai_sse(entry.response_payload))),
            media_type=SSE_MEDIA_TYPE,
            headers=headers,
        )
    return JSONResponse(entry.response_payload, headers=headers)


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
    arm: str | None = None,
    exp_from: str | None = None,
    exp_to: str | None = None,
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
    try:
        await record_proxy_usage(
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
            arm=arm,
            experiment_from=exp_from,
            experiment_to=exp_to,
            quality_ok=quality_ok,
        )
        if store_cache and settings.proxy_cache_enabled and response_payload:
            # embedding is None unless the semantic layer is on; the entry still
            # serves exact-hash hits either way.
            await cache.store(
                db, project.id, cache_key, cache_model, response_payload, in_tok, out_tok, embedding=embedding
            )
    except Exception:
        logger.exception("proxy ledger/cache write failed", extra={"project_id": str(project.id)})

    # Eval harness tap: sample this real (prompt, incumbent response) into the
    # replay corpus, only when the project opted in and we are optimizing (not
    # bypassed). Keyed on the requested model so a cheaper-model recommendation on
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
    arm=None,
    exp_from=None,
    exp_to=None,
):
    """Pass the provider's stream through to the client via the adapter's stream
    translator (verbatim for an OpenAI upstream), accumulating a copy to bill and
    (unless bypassed) cache after the client has its bytes."""
    upstream_body = adapter.prepare_request(body, model=upstream_model or model, stream=True)
    translator = adapter.stream_translator()
    # Finite timeouts so a hung upstream cannot pin this event-loop slot forever:
    # read = max gap between chunks, plus connect/write/pool. A wall-clock total cap
    # wraps the whole consumption as a backstop.
    timeout = httpx.Timeout(
        settings.proxy_stream_read_timeout_seconds,
        connect=settings.proxy_stream_connect_timeout_seconds,
    )
    ok = False

    try:
        async with asyncio.timeout(settings.proxy_stream_total_timeout_seconds):
            async with (
                httpx.AsyncClient(timeout=timeout) as client,
                client.stream(
                    "POST",
                    adapter.endpoint(),
                    headers=adapter.headers(client_key),
                    json=upstream_body,
                ) as resp,
            ):
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
            arm=arm,
            exp_from=exp_from,
            exp_to=exp_to,
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
    upstream_model=None,
    routed_from=None,
    arm=None,
    exp_from=None,
    exp_to=None,
) -> JSONResponse:
    upstream_body = adapter.prepare_request(body, model=upstream_model or model, stream=False)
    try:
        async with httpx.AsyncClient(timeout=settings.proxy_upstream_timeout_seconds) as client:
            resp = await client.post(
                adapter.endpoint(),
                headers=adapter.headers(client_key),
                json=upstream_body,
            )
    except httpx.RequestError as exc:
        # OpenAI unreachable/slow: count it against the breaker, clean 502.
        breaker.record_failure()
        logger.warning(
            "upstream request failed", extra={"project_id": str(project.id), "error": exc.__class__.__name__}
        )
        return JSONResponse(
            {
                "error": {
                    "message": f"upstream request failed: {exc.__class__.__name__}",
                    "type": "varsten_upstream_error",
                }
            },
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
        arm=arm,
        exp_from=exp_from,
        exp_to=exp_to,
    )
    return JSONResponse(payload, headers=headers)
