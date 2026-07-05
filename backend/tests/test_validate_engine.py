import json
from pathlib import Path
from types import SimpleNamespace

from scripts import validate_engine


def _write_fast_subset_report(report_dir: Path) -> None:
    report = {
        "scenario": "fast_subset_sample",
        "checks": [
            {"name": "direct_matches_raw_arithmetic", "passed": True, "detail": None},
            {"name": "holdback_matches_raw_arithmetic", "passed": True, "detail": None},
            {"name": "requests_survive_fault", "passed": True, "detail": None},
            {"name": "no_content_canary_leaks", "passed": True, "detail": None},
        ],
        "metrics": {},
    }
    (report_dir / "fast_subset_sample.json").write_text(json.dumps(report))


def test_fast_validation_uses_subset_gates(tmp_path, monkeypatch):
    def fake_run(*args, **kwargs):
        _write_fast_subset_report(tmp_path)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(validate_engine.subprocess, "run", fake_run)

    assert validate_engine.run("fast", tmp_path) == 0

    rollup = json.loads((tmp_path / "validation_report.json").read_text())
    assert rollup["gate_scope"] == "fast_pr_subset"
    assert set(rollup["gates"]) == {
        "savings_reconcile_to_ledger",
        "zero_content_leaks_in_fast_subset",
        "requests_survive_chaos",
    }
    assert all(gate["met"] for gate in rollup["gates"].values())


def test_full_validation_requires_full_gate_evidence(tmp_path, monkeypatch):
    def fake_run(*args, **kwargs):
        _write_fast_subset_report(tmp_path)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(validate_engine.subprocess, "run", fake_run)

    assert validate_engine.run("full", tmp_path) == 1

    rollup = json.loads((tmp_path / "validation_report.json").read_text())
    assert rollup["gate_scope"] == "full_acceptance"
    assert rollup["gates"]["savings_reconcile_to_ledger"]["met"] is True
    assert rollup["gates"]["zero_content_leaks"]["met"] is False
