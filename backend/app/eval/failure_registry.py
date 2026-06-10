"""Failure registry: append-only JSONL log of candidate losses from eval runs.

Every time run_eval scores a prompt as a loss for the candidate, one structured
record is appended here. Over time this file becomes the golden dataset for
training routing classifiers and seeding future eval runs.

Design constraints:
- Model-agnostic: incumbent/candidate names are runtime values, never hardcoded.
- Best-effort: any I/O or serialization error is logged and swallowed so it
  never crashes a benchmark run or a live eval worker.
- Append-only: records are never mutated; analysis reads the file as-is.
"""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("varsten.eval.registry")


def _registry_path() -> Path:
    raw = settings.eval_failure_registry_path
    p = Path(raw)
    if not p.is_absolute():
        # Resolve relative paths from the repo root (two levels above this file:
        # app/eval/failure_registry.py -> app/ -> backend/ -> repo root).
        p = Path(__file__).parent.parent.parent.parent / p
    return p


def _entry_id(incumbent_model: str, candidate_model: str, messages: list[dict]) -> str:
    user_turns = [str(m.get("content", "")) for m in messages if m.get("role") == "user"]
    blob = f"{incumbent_model}:{candidate_model}:{user_turns[-1] if user_turns else ''}"
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def record_failure(
    *,
    incumbent_model: str,
    candidate_model: str,
    messages: list[dict],
    incumbent_response: dict | None,
    candidate_response: dict | None,
    judge_reasoning: str,
    incumbent_score: float,
    candidate_score: float,
    source_dataset: str = "unknown",
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> None:
    """Append one candidate-loss record to the registry. Never raises."""
    try:
        user_turns = [str(m.get("content", "")) for m in messages if m.get("role") == "user"]
        last_turn = user_turns[-1] if user_turns else ""

        entry = {
            "id": _entry_id(incumbent_model, candidate_model, messages),
            "timestamp": datetime.now(UTC).isoformat(),
            "source_dataset": source_dataset,
            "metrics": {
                "conversation_turns": sum(1 for m in messages if m.get("role") == "user"),
                "last_turn_char_count": len(last_turn),
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            },
            "models_tested": {
                "incumbent": incumbent_model,
                "candidate": candidate_model,
            },
            "prompt_context": messages,
            "outputs": {
                "incumbent_response": incumbent_response,
                "candidate_response": candidate_response,
            },
            "evaluation": {
                "judge_model": settings.eval_judge_model,
                "incumbent_score": incumbent_score,
                "candidate_score": candidate_score,
                "reasoning": judge_reasoning,
            },
            "tags": [],
        }

        path = _registry_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")

    except Exception:
        logger.warning("failure_registry write error; record skipped", exc_info=True)
