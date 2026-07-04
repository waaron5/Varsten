"""V8 — the engine validation runner and proof pack.

Runs the validation scenario suites (tests/validation/) with report emission
on, aggregates every scenario's JSON report, evaluates the acceptance gates
from docs/design/ENGINE_VALIDATION_PLAN.md, and writes:

    <report-dir>/validation_report.json   machine-readable roll-up
    <report-dir>/PROOF_PACK.md            the human-readable proof pack

Exit code is non-zero when any scenario fails or any gate is unmet, so CI can
enforce it. ``--suite fast`` runs the PR subset (harness smoke, golden path,
reconciliation, chaos matrix); ``--suite full`` (default) runs everything.

Usage:
    uv run python scripts/validate_engine.py [--suite fast|full] [--report-dir DIR]
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent

FAST_SELECTOR = "test_v0 or test_v1 or v2_independent_reconciliation or v4_fail_open"

# Acceptance gates: gate name -> (description, predicate over all check dicts).
# A predicate receives the list of {scenario, name, passed, detail} checks.
GATES = {
    "savings_reconcile_to_ledger": (
        "Every published savings figure equals blind arithmetic on raw ledger rows",
        lambda checks: _all_named(checks, "matches_raw_arithmetic"),
    ),
    "zero_content_leaks": (
        "The content canary never appears in any metadata-only store",
        lambda checks: _all_named(checks, "no_content_canary_leaks") and _all_named(checks, "no_cross_tenant_content"),
    ),
    "requests_survive_chaos": (
        "Every request survives every injected fault, poisoned state, and storm",
        lambda checks: _all_named(checks, "requests_survive"),
    ),
    "degradation_always_rolls_back": (
        "Confirmed quality/latency regressions roll back; sub-tolerance dips never do",
        lambda checks: _all_named(checks, "rolled_back") and _all_named(checks, "no_rollback_below_tolerance"),
    ),
    "judge_ceiling_holds": (
        "Subjective verdicts can never reach production without a named human",
        lambda checks: _all_named(checks, "refused"),
    ),
    "learning_reconciles_to_decisions": (
        "Every learning statistic reconciles to persisted decision evidence",
        lambda checks: _all_named(checks, "prior_") and _all_named(checks, "no_phantom_evidence"),
    ),
    "no_painted_numbers": (
        "Do-nothing traffic yields exact zeros; estimates stay labeled estimates",
        lambda checks: _all_named(checks, "no_painted_savings") and _all_named(checks, "all_savings_exactly_zero"),
    ),
}


def _all_named(checks: list[dict], fragment: str) -> bool:
    """True when every check whose name contains the fragment passed, and at
    least one such check exists (a gate with no evidence is unmet)."""
    matched = [c for c in checks if fragment in c["name"]]
    return bool(matched) and all(c["passed"] for c in matched)


def run(suite: str, report_dir: Path) -> int:
    report_dir.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "VALIDATION_REPORT_DIR": str(report_dir)}
    cmd = ["uv", "run", "pytest", "tests/validation/", "-q"]
    if suite == "fast":
        cmd += ["-k", FAST_SELECTOR]
    print(f"[validate_engine] running {suite} suite -> {report_dir}")
    proc = subprocess.run(cmd, cwd=BACKEND_DIR, env=env)

    scenarios = []
    for path in sorted(report_dir.glob("*.json")):
        if path.name == "validation_report.json":
            continue
        scenarios.append(json.loads(path.read_text()))
    all_checks = [{"scenario": s["scenario"], **c} for s in scenarios for c in s["checks"]]

    gates = {}
    for name, (description, predicate) in GATES.items():
        gates[name] = {"description": description, "met": predicate(all_checks)}

    failed_checks = [c for c in all_checks if not c["passed"]]
    rollup = {
        "generated_at": datetime.now(UTC).isoformat(),
        "suite": suite,
        "pytest_exit_code": proc.returncode,
        "scenario_count": len(scenarios),
        "check_count": len(all_checks),
        "failed_checks": failed_checks,
        "gates": gates,
    }
    (report_dir / "validation_report.json").write_text(json.dumps(rollup, indent=2, default=str))
    _write_proof_pack(report_dir, rollup, scenarios)

    unmet = [g for g, v in gates.items() if not v["met"]]
    print(f"[validate_engine] {len(scenarios)} scenarios, {len(all_checks)} checks, {len(failed_checks)} failed")
    print(f"[validate_engine] gates unmet: {unmet or 'none'}")
    return 1 if (proc.returncode != 0 or failed_checks or unmet) else 0


def _write_proof_pack(report_dir: Path, rollup: dict, scenarios: list[dict]) -> None:
    lines = [
        "# Varsten Engine — Validation Proof Pack",
        "",
        f"Generated {rollup['generated_at']} · suite `{rollup['suite']}` · "
        f"{rollup['scenario_count']} scenarios · {rollup['check_count']} checks "
        f"({len(rollup['failed_checks'])} failed)",
        "",
        "Every number below is either reconciled against raw ledger arithmetic or",
        "checked against ground truth planted in a simulated workload. Scenario",
        "sources live in `backend/tests/validation/`.",
        "",
        "## Acceptance gates",
        "",
        "| Gate | Status | Description |",
        "|---|---|---|",
    ]
    for name, gate in rollup["gates"].items():
        status = "✅ met" if gate["met"] else "❌ UNMET"
        lines.append(f"| {name} | {status} | {gate['description']} |")
    lines += ["", "## Scenarios", ""]
    for scenario in scenarios:
        failed = [c for c in scenario["checks"] if not c["passed"]]
        badge = "✅" if not failed else "❌"
        lines.append(f"### {badge} {scenario['scenario']}")
        lines.append("")
        for check in scenario["checks"]:
            mark = "✅" if check["passed"] else "❌"
            detail = f" — `{check['detail']}`" if check.get("detail") not in (None, "clean") else ""
            lines.append(f"- {mark} {check['name']}{detail}")
        if scenario.get("metrics"):
            lines.append("")
            lines.append("Metrics:")
            for key, value in scenario["metrics"].items():
                lines.append(f"- `{key}` = `{value}`")
        lines.append("")
    (report_dir / "PROOF_PACK.md").write_text("\n".join(lines))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=["fast", "full"], default="full")
    parser.add_argument("--report-dir", default=str(BACKEND_DIR / "validation_reports"))
    args = parser.parse_args()
    return run(args.suite, Path(args.report_dir))


if __name__ == "__main__":
    sys.exit(main())
