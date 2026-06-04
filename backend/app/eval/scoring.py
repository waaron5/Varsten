"""Scoring tiers for the eval harness.

Pure functions, no I/O. Each (prompt, incumbent answer, candidate answer) pair is
scored on [-1, 1] from the candidate's perspective:

    +1  candidate better        (judge tier only)
     0  parity / acceptable     (objective pass, or judge tie)
    -1  degraded                (objective fail, or judge prefers incumbent)

The tier used depends on what the route's task allows:

- ``golden``     candidate vs the customer's asserted correct answer. Strongest.
- ``objective``  structural/JSON/equality checks against the incumbent. Cheap,
                 trustworthy, and the ONLY tier that can mark a run auto-eligible.
- ``judge``      pairwise LLM-as-judge for open-ended generation. Drives
                 approve-mode only; its noise never earns auto-apply.
"""
import json
import math
import re
import statistics
from decimal import Decimal
from typing import Any

from app.models import ReplaySample
from app.models.eval import SOURCE_GOLDEN

SCORER_GOLDEN = "golden"
SCORER_OBJECTIVE = "objective"
SCORER_JUDGE = "judge"

_WS = re.compile(r"\s+")


def assistant_text(payload: dict[str, Any] | None) -> str:
    """The assistant message text from an OpenAI chat completion payload."""
    if not payload:
        return ""
    try:
        choice = payload["choices"][0]
        content = choice.get("message", {}).get("content")
        if isinstance(content, list):
            content = " ".join(
                b.get("text", "")
                for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            )
        return content or ""
    except (KeyError, IndexError, TypeError):
        return ""


def _normalize(s: str) -> str:
    return _WS.sub(" ", s.strip().lower())


def _as_json(text: str) -> Any | None:
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


def _wants_json(sample: ReplaySample) -> bool:
    fmt = (sample.request_params or {}).get("response_format")
    if isinstance(fmt, dict):
        return fmt.get("type") in {"json_object", "json_schema"}
    return False


def score_sample(
    sample: ReplaySample, incumbent_text: str, candidate_text: str
) -> tuple[str, Decimal, bool | None]:
    """Score one pair. Returns (scorer, score in [-1,1], objective_pass or None).

    Objective tiers (golden, JSON, structural equality) return a definite pass/fail.
    When no objective signal exists the caller falls back to the judge tier; this
    function signals that by returning scorer=objective with objective_pass=None
    only when it genuinely cannot judge, which the runner treats as "needs judge"."""
    # Tier 1a: golden answer is the strongest signal when present.
    if sample.source == SOURCE_GOLDEN and sample.expected_output:
        ok = _normalize(candidate_text) == _normalize(sample.expected_output)
        return SCORER_GOLDEN, (Decimal("0") if ok else Decimal("-1")), ok

    # Tier 1b: route demands JSON -> candidate must be valid (and structurally
    # equal to the incumbent's object when the incumbent produced one).
    if _wants_json(sample):
        cand = _as_json(candidate_text)
        if cand is None:
            return SCORER_OBJECTIVE, Decimal("-1"), False
        inc = _as_json(incumbent_text)
        ok = inc is None or cand == inc
        return SCORER_OBJECTIVE, (Decimal("0") if ok else Decimal("-1")), ok

    # Tier 1c: incumbent answer is itself JSON -> structured route, compare objects.
    inc = _as_json(incumbent_text)
    if inc is not None:
        cand = _as_json(candidate_text)
        ok = cand is not None and cand == inc
        return SCORER_OBJECTIVE, (Decimal("0") if ok else Decimal("-1")), ok

    # Tier 1d: short/exact incumbent (classification, enum, yes/no) -> exact match
    # is an objective signal.
    if len(_normalize(incumbent_text)) <= 40:
        ok = _normalize(candidate_text) == _normalize(incumbent_text)
        return SCORER_OBJECTIVE, (Decimal("0") if ok else Decimal("-1")), ok

    # No objective signal: subjective generation. Caller must use the judge tier.
    return SCORER_OBJECTIVE, Decimal("0"), None


def judge_score(winner: str) -> tuple[Decimal, str]:
    """Map a resolved pairwise judge winner to a score and a win/tie/loss label."""
    if winner == "candidate":
        return Decimal("1"), "win"
    if winner == "incumbent":
        return Decimal("-1"), "loss"
    return Decimal("0"), "tie"


def mean_ci(scores: list[Decimal]) -> tuple[Decimal, Decimal, Decimal]:
    """Mean score and a 95% normal-approx confidence interval. With n<2 the
    interval is the point itself (we report it, never pretend to precision we lack;
    the verdict logic treats a wide/low interval conservatively)."""
    if not scores:
        return Decimal("0"), Decimal("0"), Decimal("0")
    vals = [float(s) for s in scores]
    mean = statistics.fmean(vals)
    if len(vals) < 2:
        m = Decimal(str(round(mean, 4)))
        return m, m, m
    half = 1.96 * statistics.pstdev(vals) / math.sqrt(len(vals))
    return (
        Decimal(str(round(mean, 4))),
        Decimal(str(round(mean - half, 4))),
        Decimal(str(round(mean + half, 4))),
    )
