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
from app.db.session import get_db
from app.models import Project
from app.proxy import cache, openai
from app.proxy.keys import openai_key_for_project
from app.proxy.ledger import record_proxy_usage

router = APIRouter(tags=["proxy"])

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

    # --- cache hit: serve without touching OpenAI (skipped when bypassed) ---
    # Fail-open: a cache-lookup failure must never block forwarding. The worst case
    # is we miss a cache hit, never that we break the client's request.
    if not bypass and settings.semantic_cache_enabled:
        entry = None
        try:
            entry = cache.get_cached(db, project.id, cache_key)
        except Exception:
            entry = None
        if entry is not None:
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
                pass
            headers = {"X-Varsten-Mode": "optimize", "X-Varsten-Cache": "hit"}
            if stream:
                return StreamingResponse(
                    iter(list(openai.completion_to_sse(entry.response_payload))),
                    media_type=SSE_MEDIA_TYPE,
                    headers=headers,
                )
            return JSONResponse(entry.response_payload, headers=headers)

    # --- forward to OpenAI (cache miss, or bypassed). store_cache off when bypassed ---
    mode = "bypass" if bypass else "optimize"
    headers = {"X-Varsten-Mode": mode, "X-Varsten-Cache": "bypass" if bypass else "miss"}
    if stream:
        return StreamingResponse(
            _stream_through(
                db, project, api_key_id, client_key, body, model, cache_key, store_cache=not bypass
            ),
            media_type=SSE_MEDIA_TYPE,
            headers=headers,
        )
    return await _forward_once(
        db, project, api_key_id, client_key, body, model, cache_key, store_cache=not bypass, headers=headers
    )


def _capture(
    db: Session,
    project: Project,
    api_key_id,
    *,
    model: str,
    response_payload: dict,
    cache_key: str,
    in_tok: int,
    out_tok: int,
    cached_tok: int,
    store_cache: bool,
) -> None:
    """Write the ledger row and (unless bypassed) store the cache entry for a miss.

    Best-effort: the response has already been obtained from OpenAI, so bookkeeping
    must never raise and fail the client's request. A failure here should be made
    visible by observability later, never by a 500."""
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
        )
        if store_cache and settings.semantic_cache_enabled and response_payload:
            cache.store(db, project.id, cache_key, model, response_payload, in_tok, out_tok)
    except Exception:
        pass


async def _stream_through(db, project, api_key_id, client_key, body, model, cache_key, store_cache):
    """Pass the OpenAI SSE stream through verbatim, buffering a copy in memory to
    bill and (unless bypassed) cache after the client has its bytes."""
    upstream_body = {**body, "stream": True, "stream_options": {"include_usage": True}}
    buffer = bytearray()
    ok = False

    try:
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST",
                openai.upstream_url(),
                headers=openai.upstream_headers(client_key),
                json=upstream_body,
            ) as resp:
                ok = resp.status_code == 200
                if not ok:
                    # Surface the upstream error to the client; do not bill or cache.
                    yield await resp.aread()
                    return
                async for chunk in resp.aiter_bytes():
                    buffer.extend(chunk)
                    yield chunk
    except httpx.RequestError as exc:
        # OpenAI unreachable. Cannot fabricate a completion, but emit a clean SSE
        # error instead of a stack trace.
        yield f'data: {{"error":{{"message":"upstream request failed: {exc.__class__.__name__}","type":"varsten_upstream_error"}}}}\n\n'.encode()
        yield b"data: [DONE]\n\n"
        return

    # Stream finished and the client has every byte. Best-effort bookkeeping.
    try:
        assembled = openai.assemble_stream(
            openai.parse_sse_events(buffer.decode("utf-8", errors="replace"))
        )
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
            response_payload=payload,
            cache_key=cache_key,
            in_tok=in_tok,
            out_tok=out_tok,
            cached_tok=cached_tok,
            store_cache=store_cache,
        )
    except Exception:
        # Never let post-stream bookkeeping break a delivered response.
        pass


async def _forward_once(
    db, project, api_key_id, client_key, body, model, cache_key, store_cache, headers
) -> JSONResponse:
    try:
        async with httpx.AsyncClient(timeout=settings.proxy_upstream_timeout_seconds) as client:
            resp = await client.post(
                openai.upstream_url(),
                headers=openai.upstream_headers(client_key),
                json=body,
            )
    except httpx.RequestError as exc:
        # OpenAI unreachable: clean 502 rather than an unhandled 500.
        return JSONResponse(
            {"error": {"message": f"upstream request failed: {exc.__class__.__name__}", "type": "varsten_upstream_error"}},
            status_code=status.HTTP_502_BAD_GATEWAY,
            headers=headers,
        )

    if resp.status_code != 200:
        try:
            detail = resp.json()
        except ValueError:
            detail = {"error": resp.text}
        return JSONResponse(detail, status_code=resp.status_code, headers=headers)

    data = resp.json()
    in_tok, out_tok, cached_tok = openai.usage_tokens(data.get("usage") or {})
    out_model = data.get("model") or model
    _capture(
        db,
        project,
        api_key_id,
        model=out_model,
        response_payload=data,
        cache_key=cache_key,
        in_tok=in_tok,
        out_tok=out_tok,
        cached_tok=cached_tok,
        store_cache=store_cache,
    )
    return JSONResponse(data, headers=headers)
