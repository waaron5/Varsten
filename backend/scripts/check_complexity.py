"""Fail CI when Python cyclomatic complexity drifts beyond the current budget."""

from __future__ import annotations

from pathlib import Path

from radon.complexity import cc_rank, cc_visit

ROOT = Path(__file__).resolve().parents[1]
PATHS = [ROOT / "app", ROOT / "scripts"]
MAX_SCORE = 25
MAX_RANK = "D"
RANK_ORDER = "ABCDEF"


def _python_files() -> list[Path]:
    files: list[Path] = []
    for base in PATHS:
        files.extend(
            path for path in base.rglob("*.py") if "__pycache__" not in path.parts and path.name != Path(__file__).name
        )
    return sorted(files)


def main() -> int:
    failures: list[str] = []
    max_rank_index = RANK_ORDER.index(MAX_RANK)
    for path in _python_files():
        for block in cc_visit(path.read_text()):
            rank = cc_rank(block.complexity)
            if block.complexity > MAX_SCORE or RANK_ORDER.index(rank) > max_rank_index:
                rel = path.relative_to(ROOT)
                failures.append(f"{rel}:{block.lineno} {block.name} {rank} ({block.complexity})")

    if failures:
        print("Complexity budget exceeded:")
        print("\n".join(f"  {failure}" for failure in failures))
        return 1

    print(f"Complexity budget OK: max score {MAX_SCORE}, max rank {MAX_RANK}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
