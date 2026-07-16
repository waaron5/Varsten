from scripts import benchmark_proof


def test_true_net_subtracts_holdback_architecture_overhead_and_gain_share():
    config = benchmark_proof.BenchmarkConfig(
        spend_basis_usd=1000,
        holdback_percent=0.05,
        gain_share_percent=0.25,
        latency_cost_per_1k_requests_per_ms_usd=0,
    )
    workload = benchmark_proof.WorkloadClass(
        id="unit",
        label="Unit",
        description="Unit test workload",
        calculator_slider_label="Unit",
        default_mix_percent=100,
        average_request_cost_usd=1,
        available_gross_savings_rates=(0.20,),
        capture_rates=(0.50,),
        primary_levers=("exact_cache",),
        evidence_basis="unit",
    )
    path = benchmark_proof.DeploymentPath(
        id="sdk_wrapper",
        label="SDK wrapper",
        description="unit",
        compute_cost_per_1k_requests_usd=10,
        latency_overhead_p50_ms=0,
        latency_overhead_p95_ms=0,
    )

    report = benchmark_proof.build_report(config, workloads=(workload,), deployment_paths=(path,))
    sample = report["workload_classes"]["unit"]["deployment_paths"]["sdk_wrapper"]["samples"][0]

    assert sample["gross_captured_savings_usd"] == 95.0
    assert sample["measurement_holdback_cost_usd"] == 5.0
    assert sample["architecture_overhead_usd"] == 10.0
    assert sample["billable_verified_savings_usd"] == 80.0
    assert sample["gain_share_fee_usd"] == 20.0
    assert sample["true_net_savings_usd"] == 60.0


def test_report_exposes_p25_p75_per_workload_for_calculator():
    report = benchmark_proof.build_report(benchmark_proof.BenchmarkConfig(generated_at="2026-07-09T00:00:00+00:00"))

    sliders = report["calculator"]["traffic_mix_sliders"]

    assert sliders
    assert {slider["id"] for slider in sliders} >= {"support_agent", "batchable_jobs", "general_chat"}
    for slider in sliders:
        assert "p25" in slider
        assert "p75" in slider
        assert "true_net_savings_rate" in slider["p25"]
        assert "sdk_wrapper" in slider["deployment_paths"]
        assert "sidecar" in slider["deployment_paths"]


def test_sidecar_overhead_is_higher_than_sdk_wrapper_for_each_workload():
    report = benchmark_proof.build_report(benchmark_proof.BenchmarkConfig(generated_at="2026-07-09T00:00:00+00:00"))

    for workload in report["workload_classes"].values():
        sdk = workload["deployment_paths"]["sdk_wrapper"]["percentiles"]["p50"]
        sidecar = workload["deployment_paths"]["sidecar"]["percentiles"]["p50"]
        assert sidecar["architecture_overhead_rate"] > sdk["architecture_overhead_rate"]
        assert sidecar["true_net_savings_rate"] < sdk["true_net_savings_rate"]


def test_general_chat_remains_near_zero_and_not_a_marketing_claim():
    report = benchmark_proof.build_report(benchmark_proof.BenchmarkConfig(generated_at="2026-07-09T00:00:00+00:00"))
    general_chat = report["workload_classes"]["general_chat"]["deployment_paths"]["sdk_wrapper"]["percentiles"]

    assert general_chat["p75"]["true_net_savings_rate"] < 0.003
    assert "Savings on unoptimizable high-variance chat." in report["claim_boundary"]["must_not_claim"]


def test_write_artifacts_creates_calculator_json_and_proof_pack(tmp_path):
    report = benchmark_proof.build_report(benchmark_proof.BenchmarkConfig(generated_at="2026-07-09T00:00:00+00:00"))

    json_path, proof_path = benchmark_proof.write_artifacts(report, tmp_path)

    assert json_path.name == "benchmark_report.json"
    assert proof_path.name == "BENCHMARK_PROOF_PACK.md"
    assert '"traffic_mix_sliders"' in json_path.read_text()
    assert "Architecture Overhead Calibration" in proof_path.read_text()
