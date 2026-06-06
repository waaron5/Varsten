"""Off-path OpenAI calls for the eval harness: replay a prompt through a candidate
model, and run a pairwise judge.

These run ONLY in the worker, never in the request hot path. They use httpx the
same way the proxy does, so tests mock them via MockTransport. Both are
best-effort from the runner's view: a None / "tie" on failure degrades the run
rather than crashing it.
"""

import asyncio
import json
import random
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.proxy.providers import get_adapter

logger = get_logger("varsten.eval.ops")

# The eval harness replays/judges against OpenAI off the hot path; reuse the
# OpenAI adapter for the upstream URL and auth headers.
_openai = get_adapter("openai")

_MAX_RETRIES = 5
_BASE_BACKOFF_S = 1.0
_MAX_BACKOFF_S = 60.0


def _parse_retry_after(header: str | None, attempt: int) -> float:
    """Return seconds to wait before the next retry. Respects Retry-After when
    present (seconds or HTTP-date); falls back to full-jitter exponential backoff."""
    if header:
        try:
            return max(0.0, float(header))
        except ValueError:
            pass
        try:
            dt = parsedate_to_datetime(header)
            return max(0.0, (dt - datetime.now(UTC)).total_seconds())
        except Exception:
            pass
    cap = min(_MAX_BACKOFF_S, _BASE_BACKOFF_S * (2**attempt))
    return random.uniform(0, cap)


async def _post_with_retry(url: str, headers: dict, body: dict, timeout: float) -> httpx.Response:
    """POST with exponential backoff on 429. Respects Retry-After headers."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        for attempt in range(_MAX_RETRIES + 1):
            resp = await client.post(url, headers=headers, json=body)
            if resp.status_code != 429 or attempt == _MAX_RETRIES:
                return resp
            wait = _parse_retry_after(resp.headers.get("retry-after"), attempt)
            logger.warning(
                "upstream 429; retrying",
                extra={"attempt": attempt + 1, "wait_s": round(wait, 2)},
            )
            await asyncio.sleep(wait)
    return resp  # type: ignore[return-value]

# Pairwise judge. Position-swapping is handled by the runner (it calls twice with
# the answers swapped), so the judge only ever names "first" or "second".
_JUDGE_SYSTEM = (
    "You are a strict evaluator. Two assistant answers, FIRST and SECOND, respond "
    "to the same user prompt. Decide which answer is better on correctness, "
    "completeness, and helpfulness. If they are equivalent, say tie. Reply with "
    'only JSON: {"winner": "first" | "second" | "tie", "reasoning": "<one sentence>"}.'
)


async def replay_candidate(messages: list[dict], params: dict, model: str, key: str) -> dict | None:
    """Run the prompt through the candidate model (non-stream). Returns the
    completion payload, or None on failure so the runner can skip the sample."""
    body = {**(params or {}), "model": model, "messages": messages, "stream": False}
    try:
        resp = await _post_with_retry(
            _openai.endpoint(),
            _openai.headers(key),
            body,
            settings.proxy_upstream_timeout_seconds,
        )
        if resp.status_code != 200:
            logger.warning("replay candidate non-200", extra={"status": resp.status_code, "model": model})
            return None
        return resp.json()
    except Exception:
        logger.exception("replay candidate failed", extra={"model": model})
        return None


async def _judge_once(prompt: str, first: str, second: str, key: str) -> tuple[str, str]:
    """Returns (winner, reasoning). winner is 'first' | 'second' | 'tie'."""
    body = {
        "model": settings.eval_judge_model,
        "messages": [
            {"role": "system", "content": _JUDGE_SYSTEM},
            {
                "role": "user",
                "content": f"USER PROMPT:\n{prompt}\n\nFIRST:\n{first}\n\nSECOND:\n{second}",
            },
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    resp = await _post_with_retry(
        _openai.endpoint(),
        _openai.headers(key),
        body,
        settings.proxy_upstream_timeout_seconds,
    )
    resp.raise_for_status()
    data = json.loads(resp.json()["choices"][0]["message"]["content"])
    winner = (data.get("winner") or "tie").lower()
    reasoning = data.get("reasoning") or ""
    return winner, reasoning


async def judge_pairwise(prompt: str, incumbent: str, candidate: str, key: str) -> tuple[str, str]:
    """Position-swapped pairwise judge. Calls twice (incumbent-first, then
    candidate-first) and resolves to (winner, reasoning) where winner is
    incumbent | candidate | tie. Disagreement between orderings resolves to tie.
    Any failure resolves to tie with an empty reasoning string."""
    try:
        # Round 1: incumbent is FIRST, candidate is SECOND.
        r1, reason1 = await _judge_once(prompt, incumbent, candidate, key)
        # Round 2: candidate is FIRST, incumbent is SECOND (positions swapped). The
        # consensus reasoning comes from round 1, so round 2's reasoning is unused.
        r2, _ = await _judge_once(prompt, candidate, incumbent, key)
    except Exception:
        logger.exception("judge failed; recording tie")
        return "tie", ""

    # Translate each round to who won, accounting for the swap.
    win1 = {"first": "incumbent", "second": "candidate"}.get(r1, "tie")
    win2 = {"first": "candidate", "second": "incumbent"}.get(r2, "tie")
    if win1 == win2:
        # Use the reasoning from the round that agreed with the consensus.
        return win1, reason1
    return "tie", ""
