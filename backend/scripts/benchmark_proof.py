"""Build the Varsten benchmark report and proof pack.

This runner produces the machine-readable ROI-calculator contract plus a human
proof pack. It deliberately separates four numbers that are easy to blur:

1. gross captured savings before measurement overhead,
2. live holdback measurement cost,
3. Varsten deployment overhead for SDK-wrapper and sidecar paths,
4. customer net after the 25% gain-share fee.

The workload distributions are deterministic and conservative. They are meant
to be refreshed from the live engine benchmark/validation suite as the measured
sample set grows, while preserving the JSON shape that the marketing calculator
can consume.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_REPORT_DIR = BACKEND_DIR / "benchmark_reports"
SCHEMA_VERSION = "benchmark-report.v1"


@dataclass(frozen=True)
class BenchmarkConfig:
    spend_basis_usd: float = 1000.0
    holdback_percent: float = 0.05
    gain_share_percent: float = 0.25
    latency_cost_per_1k_requests_per_ms_usd: float = 0.0001
    generated_at: str = ""


@dataclass(frozen=True)
class DeploymentPath:
    id: str
    label: str
    description: str
    compute_cost_per_1k_requests_usd: float
    latency_overhead_p50_ms: float
    latency_overhead_p95_ms: float


@dataclass(frozen=True)
class WorkloadClass:
    id: str
    label: str
    description: str
    calculator_slider_label: str
    default_mix_percent: float
    average_request_cost_usd: float
    available_gross_savings_rates: tuple[float, ...]
    capture_rates: tuple[float, ...]
    primary_levers: tuple[str, ...]
    evidence_basis: str


@dataclass(frozen=True)
class BenchmarkSample:
    available_gross_savings_rate: float
    capture_rate: float
    request_count: float
    gross_captured_savings_usd: float
    measurement_holdback_cost_usd: float
    architecture_overhead_usd: float
    varsten_overhead_usd: float
    billable_verified_savings_usd: float
    gain_share_fee_usd: float
    true_net_savings_usd: float

    def to_json(self, spend_basis_usd: float) -> dict[str, float]:
        return {
            "available_gross_savings_rate": _round_rate(self.available_gross_savings_rate),
            "capture_rate": _round_rate(self.capture_rate),
            "request_count": _round_money(self.request_count),
            "gross_captured_savings_usd": _round_money(self.gross_captured_savings_usd),
            "gross_captured_savings_rate": _round_rate(self.gross_captured_savings_usd / spend_basis_usd),
            "measurement_holdback_cost_usd": _round_money(self.measurement_holdback_cost_usd),
            "measurement_holdback_cost_rate": _round_rate(self.measurement_holdback_cost_usd / spend_basis_usd),
            "architecture_overhead_usd": _round_money(self.architecture_overhead_usd),
            "architecture_overhead_rate": _round_rate(self.architecture_overhead_usd / spend_basis_usd),
            "varsten_overhead_usd": _round_money(self.varsten_overhead_usd),
            "varsten_overhead_rate": _round_rate(self.varsten_overhead_usd / spend_basis_usd),
            "billable_verified_savings_usd": _round_money(self.billable_verified_savings_usd),
            "billable_verified_savings_rate": _round_rate(self.billable_verified_savings_usd / spend_basis_usd),
            "gain_share_fee_usd": _round_money(self.gain_share_fee_usd),
            "gain_share_fee_rate": _round_rate(self.gain_share_fee_usd / spend_basis_usd),
            "true_net_savings_usd": _round_money(self.true_net_savings_usd),
            "true_net_savings_rate": _round_rate(self.true_net_savings_usd / spend_basis_usd),
        }


def default_deployment_paths(
    *,
    sdk_compute_cost_per_1k_requests_usd: float = 0.018,
    sdk_latency_p50_ms: float = 1.2,
    sdk_latency_p95_ms: float = 4.0,
    sidecar_compute_cost_per_1k_requests_usd: float = 0.045,
    sidecar_latency_p50_ms: float = 3.8,
    sidecar_latency_p95_ms: float = 10.0,
) -> tuple[DeploymentPath, ...]:
    return (
        DeploymentPath(
            id="sdk_wrapper",
            label="SDK wrapper",
            description="Application imports the Varsten package around provider SDK calls.",
            compute_cost_per_1k_requests_usd=sdk_compute_cost_per_1k_requests_usd,
            latency_overhead_p50_ms=sdk_latency_p50_ms,
            latency_overhead_p95_ms=sdk_latency_p95_ms,
        ),
        DeploymentPath(
            id="sidecar",
            label="Sidecar",
            description="Application calls a local Varsten sidecar before provider egress.",
            compute_cost_per_1k_requests_usd=sidecar_compute_cost_per_1k_requests_usd,
            latency_overhead_p50_ms=sidecar_latency_p50_ms,
            latency_overhead_p95_ms=sidecar_latency_p95_ms,
        ),
    )


def default_workloads() -> tuple[WorkloadClass, ...]:
    return (
        WorkloadClass(
            id="support_agent",
            label="Support",
            description="Stable support and internal-agent prompts with repeated user intents.",
            calculator_slider_label="Support",
            default_mix_percent=30,
            average_request_cost_usd=0.012,
            available_gross_savings_rates=(0.10, 0.18, 0.28, 0.40, 0.52),
            capture_rates=(0.72, 0.82, 0.90, 0.95),
            primary_levers=("exact_cache", "prompt_cache", "model_downshift", "token_trim"),
            evidence_basis="V7 support tape plants exact repeats and requires >=90% capture on duplicate cost.",
        ),
        WorkloadClass(
            id="batchable_jobs",
            label="Batchable",
            description="Non-urgent jobs that can use provider batch discounts or scheduled execution.",
            calculator_slider_label="Batchable",
            default_mix_percent=15,
            average_request_cost_usd=0.020,
            available_gross_savings_rates=(0.08, 0.16, 0.26, 0.38, 0.50),
            capture_rates=(0.70, 0.82, 0.92, 1.00),
            primary_levers=("batching",),
            evidence_basis="Batch savings are direct arithmetic against provider batch pricing where catalog coverage exists.",
        ),
        WorkloadClass(
            id="agentic_research",
            label="Agentic research",
            description="Multi-step agent traces where repeated or wasted tool-planning calls can be detected.",
            calculator_slider_label="Agentic",
            default_mix_percent=15,
            average_request_cost_usd=0.030,
            available_gross_savings_rates=(0.04, 0.08, 0.13, 0.19, 0.25),
            capture_rates=(0.60, 0.72, 0.84, 0.92),
            primary_levers=("agent_loop", "prompt_prefix_restructure", "model_downshift"),
            evidence_basis="V7 agent-loop tape plants 16 redundant calls in 64 and requires quantified detection.",
        ),
        WorkloadClass(
            id="long_context",
            label="Long context",
            description="Large prompts, long histories, and repeated instructions where input tokens can be reduced.",
            calculator_slider_label="Long context",
            default_mix_percent=15,
            average_request_cost_usd=0.045,
            available_gross_savings_rates=(0.03, 0.06, 0.10, 0.16, 0.22),
            capture_rates=(0.55, 0.68, 0.80, 0.88),
            primary_levers=("token_trim", "prompt_compression", "prompt_cache"),
            evidence_basis="Compression/trim savings must be holdback or replay measured and net of compression overhead.",
        ),
        WorkloadClass(
            id="classification_routing",
            label="Routing-safe tasks",
            description="Low-risk classification, extraction, and routing tasks eligible for cheaper models.",
            calculator_slider_label="Routing-safe",
            default_mix_percent=15,
            average_request_cost_usd=0.010,
            available_gross_savings_rates=(0.05, 0.10, 0.18, 0.26, 0.35),
            capture_rates=(0.50, 0.64, 0.78, 0.88),
            primary_levers=("smart_routing", "model_downshift"),
            evidence_basis="Routing/downshift claims require eval gates plus holdback or replay measurement.",
        ),
        WorkloadClass(
            id="general_chat",
            label="General chat",
            description="High-variance interactive chat where the honest result is usually no optimization.",
            calculator_slider_label="General chat",
            default_mix_percent=10,
            average_request_cost_usd=0.018,
            available_gross_savings_rates=(0.0, 0.002, 0.006, 0.012),
            capture_rates=(0.0, 0.12, 0.24, 0.35),
            primary_levers=(),
            evidence_basis="V7 high-variance tape requires no cache hits, no invented loops, and no painted savings.",
        ),
    )


def build_report(
    config: BenchmarkConfig,
    workloads: tuple[WorkloadClass, ...] | None = None,
    deployment_paths: tuple[DeploymentPath, ...] | None = None,
) -> dict[str, Any]:
    workloads = workloads or default_workloads()
    deployment_paths = deployment_paths or default_deployment_paths()
    generated_at = config.generated_at or datetime.now(UTC).isoformat()

    workload_reports = {
        workload.id: _workload_report(workload, config, deployment_paths)
        for workload in workloads
    }
    default_deployment = "sdk_wrapper"
    portfolio = _portfolio_summary(workload_reports, default_deployment)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "methodology": {
            "spend_basis_usd": config.spend_basis_usd,
            "holdback_percent": config.holdback_percent,
            "gain_share_percent": config.gain_share_percent,
            "net_formula": (
                "true_net = gross_captured_savings - measurement_holdback_cost "
                "- architecture_overhead - gain_share_fee"
            ),
            "fee_formula": "gain_share_fee = max(billable_verified_savings, 0) * gain_share_percent",
            "architecture_overhead": (
                "Per deployment path: request_count * compute cost plus p50 latency overhead valued "
                "by latency_cost_per_1k_requests_per_ms_usd."
            ),
            "latency_cost_per_1k_requests_per_ms_usd": config.latency_cost_per_1k_requests_per_ms_usd,
        },
        "deployment_paths": {
            path.id: {
                "label": path.label,
                "description": path.description,
                "compute_cost_per_1k_requests_usd": path.compute_cost_per_1k_requests_usd,
                "latency_overhead_p50_ms": path.latency_overhead_p50_ms,
                "latency_overhead_p95_ms": path.latency_overhead_p95_ms,
            }
            for path in deployment_paths
        },
        "calculator": {
            "default_deployment_path": default_deployment,
            "spend_basis_usd": config.spend_basis_usd,
            "holdback_percent": config.holdback_percent,
            "gain_share_percent": config.gain_share_percent,
            "traffic_mix_sliders": [
                _calculator_slider(workload_reports[workload.id], default_deployment)
                for workload in workloads
            ],
            "portfolio_default_mix": portfolio,
        },
        "workload_classes": workload_reports,
        "claim_boundary": {
            "publishable_metric": "P25-P75 true net savings rate after holdback, architecture overhead, and fee.",
            "must_not_claim": [
                "A single flat savings rate for all customers.",
                "Savings on unoptimizable high-variance chat.",
                "Billable estimates before direct, holdback, or replay measurement exists.",
            ],
            "required_refresh_before_public_update": [
                "Run scripts.validate_engine full suite.",
                "Refresh SDK wrapper and sidecar latency/compute calibration from load_benchmark or production telemetry.",
                "Regenerate this report and commit the JSON/proof pack together.",
            ],
        },
    }


def write_artifacts(report: dict[str, Any], report_dir: Path = DEFAULT_REPORT_DIR) -> tuple[Path, Path]:
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / "benchmark_report.json"
    proof_path = report_dir / "BENCHMARK_PROOF_PACK.md"
    json_path.write_text(json.dumps(report, indent=2) + "\n")
    proof_path.write_text(render_proof_pack(report))
    return json_path, proof_path


def render_proof_pack(report: dict[str, Any]) -> str:
    method = report["methodology"]
    portfolio = report["calculator"]["portfolio_default_mix"]
    default_path = report["calculator"]["default_deployment_path"]
    lines = [
        "# Varsten Benchmark Proof Pack",
        "",
        f"Generated: `{report['generated_at']}`",
        f"Report schema: `{report['schema_version']}`",
        "",
        "## Claim",
        "",
        "Use the P25-P75 range, not a single average, and only describe it as expected net savings",
        "after holdback measurement cost, calibrated Varsten deployment overhead, and the 25% gain-share fee.",
        "",
        f"Default mix, `{default_path}` deployment: **{_pct(portfolio['p25']['true_net_savings_rate'])} - "
        f"{_pct(portfolio['p75']['true_net_savings_rate'])} true net savings**.",
        "",
        "## Accounting Formula",
        "",
        f"- Spend basis: `${method['spend_basis_usd']:,.0f}` per workload class.",
        f"- Holdback bypass: `{_pct(method['holdback_percent'])}` of eligible treatment is kept as control.",
        f"- Gain-share fee: `{_pct(method['gain_share_percent'])}` of positive billable verified savings.",
        "- Billable verified savings = gross captured savings - holdback measurement cost - architecture overhead.",
        "- True net savings = billable verified savings - gain-share fee.",
        "",
        "## Architecture Overhead Calibration",
        "",
        "| Path | Compute / 1k requests | P50 latency | P95 latency |",
        "|---|---:|---:|---:|",
    ]
    for path in report["deployment_paths"].values():
        lines.append(
            f"| {path['label']} | ${path['compute_cost_per_1k_requests_usd']:.3f} | "
            f"{path['latency_overhead_p50_ms']:.1f} ms | {path['latency_overhead_p95_ms']:.1f} ms |"
        )

    lines += [
        "",
        "Latency overhead is included in the Varsten overhead metric using the configured",
        "`latency_cost_per_1k_requests_per_ms_usd` value. Keep this value visible so a buyer",
        "can see when it is zero, conservative, or replaced by their own latency cost model.",
        "",
        "## Workload Ranges",
        "",
        "| Workload | Default mix | P25 net | P75 net | Primary levers |",
        "|---|---:|---:|---:|---|",
    ]
    for workload in report["workload_classes"].values():
        path_summary = workload["deployment_paths"][default_path]["percentiles"]
        lines.append(
            f"| {workload['label']} | {workload['default_mix_percent']:.0f}% | "
            f"{_pct(path_summary['p25']['true_net_savings_rate'])} | "
            f"{_pct(path_summary['p75']['true_net_savings_rate'])} | "
            f"{', '.join(workload['primary_levers']) or 'none'} |"
        )

    lines += [
        "",
        "## Evidence Basis",
        "",
    ]
    for workload in report["workload_classes"].values():
        lines.append(f"- **{workload['label']}**: {workload['evidence_basis']}")

    lines += [
        "",
        "## Calculator Contract",
        "",
        "`benchmark_report.json` exposes `calculator.traffic_mix_sliders[]`. Each slider includes",
        "`p25`, `p50`, and `p75` metrics for both `sdk_wrapper` and `sidecar`, so the Next.js",
        "ROI calculator can combine workload-specific ranges rather than multiplying one flat",
        "savings rate by total spend.",
        "",
        "## Refresh Procedure",
        "",
        "1. Run the full validation suite: `uv run python -m scripts.validate_engine --suite full`.",
        "2. Refresh sidecar and SDK-wrapper overhead measurements from `scripts.load_benchmark` or production telemetry.",
        "3. Regenerate this pack: `uv run python -m scripts.benchmark_proof --report-dir benchmark_reports`.",
        "4. Publish only the current P25-P75 net range and keep estimates separate from verified savings.",
        "",
    ]
    return "\n".join(lines)


def _workload_report(
    workload: WorkloadClass,
    config: BenchmarkConfig,
    deployment_paths: tuple[DeploymentPath, ...],
) -> dict[str, Any]:
    deployment_reports = {}
    for path in deployment_paths:
        samples = [
            _sample(workload, config, path, available_rate, capture_rate)
            for available_rate in workload.available_gross_savings_rates
            for capture_rate in workload.capture_rates
        ]
        deployment_reports[path.id] = {
            "sample_count": len(samples),
            "percentiles": _sample_percentiles(samples, config.spend_basis_usd),
            "samples": [sample.to_json(config.spend_basis_usd) for sample in samples],
        }
    return {
        "id": workload.id,
        "label": workload.label,
        "description": workload.description,
        "calculator_slider_label": workload.calculator_slider_label,
        "default_mix_percent": workload.default_mix_percent,
        "average_request_cost_usd": workload.average_request_cost_usd,
        "request_count_per_1000_spend": _round_money(config.spend_basis_usd / workload.average_request_cost_usd),
        "primary_levers": list(workload.primary_levers),
        "evidence_basis": workload.evidence_basis,
        "deployment_paths": deployment_reports,
    }


def _sample(
    workload: WorkloadClass,
    config: BenchmarkConfig,
    deployment_path: DeploymentPath,
    available_gross_savings_rate: float,
    capture_rate: float,
) -> BenchmarkSample:
    request_count = config.spend_basis_usd / workload.average_request_cost_usd
    available_usd = config.spend_basis_usd * available_gross_savings_rate
    captured_before_holdback = available_usd * capture_rate
    gross_captured = captured_before_holdback * (1 - config.holdback_percent)
    holdback_cost = captured_before_holdback * config.holdback_percent
    architecture_overhead = _architecture_overhead_usd(request_count, config, deployment_path)
    billable_verified = gross_captured - holdback_cost - architecture_overhead
    gain_share_fee = max(billable_verified, 0) * config.gain_share_percent
    true_net = billable_verified - gain_share_fee
    return BenchmarkSample(
        available_gross_savings_rate=available_gross_savings_rate,
        capture_rate=capture_rate,
        request_count=request_count,
        gross_captured_savings_usd=gross_captured,
        measurement_holdback_cost_usd=holdback_cost,
        architecture_overhead_usd=architecture_overhead,
        varsten_overhead_usd=holdback_cost + architecture_overhead,
        billable_verified_savings_usd=billable_verified,
        gain_share_fee_usd=gain_share_fee,
        true_net_savings_usd=true_net,
    )


def _architecture_overhead_usd(
    request_count: float,
    config: BenchmarkConfig,
    deployment_path: DeploymentPath,
) -> float:
    request_units = request_count / 1000
    compute_cost = request_units * deployment_path.compute_cost_per_1k_requests_usd
    latency_cost = (
        request_units
        * deployment_path.latency_overhead_p50_ms
        * config.latency_cost_per_1k_requests_per_ms_usd
    )
    return compute_cost + latency_cost


def _sample_percentiles(samples: list[BenchmarkSample], spend_basis_usd: float) -> dict[str, dict[str, float]]:
    raw = [sample.to_json(spend_basis_usd) for sample in samples]
    keys = [
        "gross_captured_savings_rate",
        "measurement_holdback_cost_rate",
        "architecture_overhead_rate",
        "varsten_overhead_rate",
        "billable_verified_savings_rate",
        "gain_share_fee_rate",
        "true_net_savings_rate",
        "gross_captured_savings_usd",
        "measurement_holdback_cost_usd",
        "architecture_overhead_usd",
        "varsten_overhead_usd",
        "billable_verified_savings_usd",
        "gain_share_fee_usd",
        "true_net_savings_usd",
    ]
    return {
        "p25": {key: _percentile([row[key] for row in raw], 25) for key in keys},
        "p50": {key: _percentile([row[key] for row in raw], 50) for key in keys},
        "p75": {key: _percentile([row[key] for row in raw], 75) for key in keys},
    }


def _calculator_slider(workload_report: dict[str, Any], default_deployment: str) -> dict[str, Any]:
    default_percentiles = workload_report["deployment_paths"][default_deployment]["percentiles"]
    return {
        "id": workload_report["id"],
        "label": workload_report["calculator_slider_label"],
        "description": workload_report["description"],
        "default_percent": workload_report["default_mix_percent"],
        "average_request_cost_usd": workload_report["average_request_cost_usd"],
        "request_count_per_1000_spend": workload_report["request_count_per_1000_spend"],
        "p25": default_percentiles["p25"],
        "p50": default_percentiles["p50"],
        "p75": default_percentiles["p75"],
        "deployment_paths": {
            path_id: path_report["percentiles"]
            for path_id, path_report in workload_report["deployment_paths"].items()
        },
    }


def _portfolio_summary(workload_reports: dict[str, Any], default_deployment: str) -> dict[str, Any]:
    total_mix = sum(workload["default_mix_percent"] for workload in workload_reports.values())
    if not math.isclose(total_mix, 100.0):
        raise ValueError(f"default workload mix must sum to 100, got {total_mix}")
    keys = (
        "gross_captured_savings_rate",
        "architecture_overhead_rate",
        "varsten_overhead_rate",
        "billable_verified_savings_rate",
        "gain_share_fee_rate",
        "true_net_savings_rate",
    )
    summary: dict[str, Any] = {"deployment_path": default_deployment, "mix_total_percent": total_mix}
    for pct in ("p25", "p50", "p75"):
        summary[pct] = {}
        for key in keys:
            summary[pct][key] = _round_rate(
                sum(
                    (workload["default_mix_percent"] / total_mix)
                    * workload["deployment_paths"][default_deployment]["percentiles"][pct][key]
                    for workload in workload_reports.values()
                )
            )
    return summary


def _percentile(values: list[float], percentile: int) -> float:
    if not values:
        raise ValueError("cannot percentile an empty list")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * percentile / 100
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[int(rank)]
    weight = rank - lower
    return _round_rate(ordered[lower] * (1 - weight) + ordered[upper] * weight)


def _round_rate(value: float) -> float:
    return round(value, 6)


def _round_money(value: float) -> float:
    return round(value, 4)


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build benchmark_report.json and BENCHMARK_PROOF_PACK.md")
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--spend-basis-usd", type=float, default=1000.0)
    parser.add_argument("--holdback-percent", type=float, default=0.05)
    parser.add_argument("--gain-share-percent", type=float, default=0.25)
    parser.add_argument("--latency-cost-per-1k-requests-per-ms-usd", type=float, default=0.0001)
    parser.add_argument("--sdk-compute-cost-per-1k-requests-usd", type=float, default=0.018)
    parser.add_argument("--sdk-latency-p50-ms", type=float, default=1.2)
    parser.add_argument("--sdk-latency-p95-ms", type=float, default=4.0)
    parser.add_argument("--sidecar-compute-cost-per-1k-requests-usd", type=float, default=0.045)
    parser.add_argument("--sidecar-latency-p50-ms", type=float, default=3.8)
    parser.add_argument("--sidecar-latency-p95-ms", type=float, default=10.0)
    args = parser.parse_args()

    config = BenchmarkConfig(
        spend_basis_usd=args.spend_basis_usd,
        holdback_percent=args.holdback_percent,
        gain_share_percent=args.gain_share_percent,
        latency_cost_per_1k_requests_per_ms_usd=args.latency_cost_per_1k_requests_per_ms_usd,
    )
    deployment_paths = default_deployment_paths(
        sdk_compute_cost_per_1k_requests_usd=args.sdk_compute_cost_per_1k_requests_usd,
        sdk_latency_p50_ms=args.sdk_latency_p50_ms,
        sdk_latency_p95_ms=args.sdk_latency_p95_ms,
        sidecar_compute_cost_per_1k_requests_usd=args.sidecar_compute_cost_per_1k_requests_usd,
        sidecar_latency_p50_ms=args.sidecar_latency_p50_ms,
        sidecar_latency_p95_ms=args.sidecar_latency_p95_ms,
    )
    report = build_report(config, deployment_paths=deployment_paths)
    json_path, proof_path = write_artifacts(report, args.report_dir)
    print(f"Wrote {json_path}")
    print(f"Wrote {proof_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
