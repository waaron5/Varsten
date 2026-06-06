"""Phase 1 inline proxy: OpenAI chat completions mirror.

POST /v1/chat/completions
  - authenticate with the vk_ key, resolve the project's OpenAI key
  - on a semantic-cache hit, serve the stored completion ($0, no upstream call)
  - on a miss, stream the OpenAI response straight through (SSE preserved) while
    capturing token/billing metadata in volatile memory, then write the ledger
    row and (optionally) cache the result

Only the semantic-cache lever is active. The other four levers are not wired and
stay bypassed by config.
"""

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import ApiKeyContext, require_api_key_context
from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import get_db
from app.eval import capture as eval_capture
from app.models import Project
from app.proxy import cache, openai, quality, routing, trim
from app.proxy.circuit import get_breaker, is_upstream_failure
from app.proxy.embedding import embed, embedding_input
from app.proxy.keys import openai_key_for_project
from app.proxy.ledger import record_proxy_usage

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
    api_context: ApiKeyContext = Depends(require_api_key_context),
    db: Session = Depends(get_db),
):
    project = api_context.project
    api_key_id = api_context.api_key.id

    client_key = openai_key_for_project(project.id)
    if not client_key:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="no OpenAI key configured for this project",
        )

    body = await request.json()
    stream = bool(body.get("stream", False))
    model = body.get("model", "")
    bypass = _is_bypassed(project)
    cache_key = cache.compute_cache_key(body)

    # --- cache: exact-hash fast path, then semantic. Skipped when bypassed. ---
    # Fail-open throughout: a cache/embedding failure must never block forwarding.
    embedding: list[float] | None = None
    if not bypass and settings.semantic_cache_enabled:
        # 1) Exact hash: byte-identical repeats serve instantly, no embedding call.
        try:
            entry = cache.get_cached(db, project.id, cache_key)
        except Exception:
            logger.exception("cache lookup failed; forwarding", extra={"project_id": str(project.id)})
            entry = None
        if entry is not None:
            return _serve_cache_hit(db, project, api_key_id, entry, stream, "hit")

        # 2) Semantic: embed the prompt and find the nearest cached answer. The
        # embedding is reused for storage on a miss, so we embed at most once.
        try:
            embedding = await embed(embedding_input(body), client_key)
            sem = cache.semantic_search(db, project.id, model, embedding, settings.semantic_cache_threshold)
        except Exception:
            logger.exception("semantic lookup failed; forwarding", extra={"project_id": str(project.id)})
            sem = None
        if sem is not None:
            return _serve_cache_hit(db, project, api_key_id, sem, stream, "semantic")

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
        decision = routing.resolve_route(db, project.id, model, body)
        if decision and decision.candidate_model and decision.candidate_model != model:
            exp_from, exp_to = model, decision.candidate_model
            arm = routing.assign_arm(decision.holdback_percent)
            if arm == routing.ARM_TREATMENT:
                routed_from = model
                upstream_model = decision.candidate_model
        else:
            tdecision = trim.resolve_trim(db, project.id, model)
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


def _serve_cache_hit(db, project, api_key_id, entry, stream, cache_label):
    """Serve a cache entry (exact or semantic), record the hit and the $0 ledger row."""
    try:
        cache.record_hit(db, entry)
        record_proxy_usage(
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
        logger.exception("cache-hit bookkeeping failed", extra={"project_id": str(project.id)})
    headers = {"X-Varsten-Mode": "optimize", "X-Varsten-Cache": cache_label}
    if stream:
        return StreamingResponse(
            iter(list(openai.completion_to_sse(entry.response_payload))),
            media_type=SSE_MEDIA_TYPE,
            headers=headers,
        )
    return JSONResponse(entry.response_payload, headers=headers)


def _capture(
    db: Session,
    project: Project,
    api_key_id,
    *,
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
        record_proxy_usage(
            db,
            project,
            api_key_id,
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
        if store_cache and settings.semantic_cache_enabled and response_payload:
            cache.store(db, project.id, cache_key, cache_model, response_payload, in_tok, out_tok, embedding=embedding)
    except Exception:
        logger.exception("proxy ledger/cache write failed", extra={"project_id": str(project.id)})

    # Eval harness tap: sample this real (prompt, incumbent response) into the
    # replay corpus, only when the project opted in and we are optimizing (not
    # bypassed). Keyed on the requested model so a cheaper-model recommendation on
    # that route can later replay it. Best-effort and off the response path.
    if store_cache and body is not None and response_payload:
        eval_capture.capture_sample(
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
    """Pass the OpenAI SSE stream through verbatim, buffering a copy in memory to
    bill and (unless bypassed) cache after the client has its bytes."""
    upstream_body = {
        **body,
        "model": upstream_model or model,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    buffer = bytearray()
    ok = False

    try:
        async with (
            httpx.AsyncClient(timeout=httpx.Timeout(None, connect=10.0)) as client,
            client.stream(
                "POST",
                openai.upstream_url(),
                headers=openai.upstream_headers(client_key),
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
                buffer.extend(chunk)
                yield chunk
    except httpx.RequestError as exc:
        # OpenAI unreachable/slow: count it against the breaker and emit a clean
        # SSE error instead of a stack trace.
        breaker.record_failure()
        logger.warning("upstream stream failed", extra={"project_id": str(project.id), "error": exc.__class__.__name__})
        yield f'data: {{"error":{{"message":"upstream request failed: {exc.__class__.__name__}","type":"varsten_upstream_error"}}}}\n\n'.encode()
        yield b"data: [DONE]\n\n"
        return

    # Stream finished and the client has every byte. Best-effort bookkeeping.
    try:
        assembled = openai.assemble_stream(openai.parse_sse_events(buffer.decode("utf-8", errors="replace")))
        in_tok, out_tok, cached_tok = openai.usage_tokens(assembled["usage"])
        out_model = assembled["model"] or model
        payload = (
            openai.build_completion_object(
                out_model, assembled["content"], assembled["usage"], assembled["finish_reason"]
            )
            if assembled["content"]
            else {}
        )
        _capture(
            db,
            project,
            api_key_id,
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
    try:
        async with httpx.AsyncClient(timeout=settings.proxy_upstream_timeout_seconds) as client:
            resp = await client.post(
                openai.upstream_url(),
                headers=openai.upstream_headers(client_key),
                json={**body, "model": upstream_model or model},
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

    data = resp.json()
    in_tok, out_tok, cached_tok = openai.usage_tokens(data.get("usage") or {})
    out_model = data.get("model") or model
    _capture(
        db,
        project,
        api_key_id,
        model=out_model,
        cache_model=model,
        response_payload=data,
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
    return JSONResponse(data, headers=headers)
