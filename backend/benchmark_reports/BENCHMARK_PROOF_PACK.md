# Varsten Benchmark Proof Pack

Generated: `2026-07-09T20:15:27.218789+00:00`
Report schema: `benchmark-report.v1`

## Claim

Use the P25-P75 range, not a single average, and only describe it as expected net savings
after holdback measurement cost, calibrated Varsten deployment overhead, and the 25% gain-share fee.

Default mix, `sdk_wrapper` deployment: **5.7% - 15.5% true net savings**.

## Accounting Formula

- Spend basis: `$1,000` per workload class.
- Holdback bypass: `5.0%` of eligible treatment is kept as control.
- Gain-share fee: `25.0%` of positive billable verified savings.
- Billable verified savings = gross captured savings - holdback measurement cost - architecture overhead.
- True net savings = billable verified savings - gain-share fee.

## Architecture Overhead Calibration

| Path | Compute / 1k requests | P50 latency | P95 latency |
|---|---:|---:|---:|
| SDK wrapper | $0.018 | 1.2 ms | 4.0 ms |
| Sidecar | $0.045 | 3.8 ms | 10.0 ms |

Latency overhead is included in the Varsten overhead metric using the configured
`latency_cost_per_1k_requests_per_ms_usd` value. Keep this value visible so a buyer
can see when it is zero, conservative, or replaced by their own latency cost model.

## Workload Ranges

| Workload | Default mix | P25 net | P75 net | Primary levers |
|---|---:|---:|---:|---|
| Support | 30% | 9.5% | 24.4% | exact_cache, prompt_cache, model_downshift, token_trim |
| Batchable | 15% | 8.5% | 23.5% | batching |
| Agentic research | 15% | 3.7% | 10.2% | agent_loop, prompt_prefix_restructure, model_downshift |
| Long context | 15% | 2.6% | 8.3% | token_trim, prompt_compression, prompt_cache |
| Routing-safe tasks | 15% | 3.9% | 12.1% | smart_routing, model_downshift |
| General chat | 10% | -0.1% | 0.0% | none |

## Evidence Basis

- **Support**: V7 support tape plants exact repeats and requires >=90% capture on duplicate cost.
- **Batchable**: Batch savings are direct arithmetic against provider batch pricing where catalog coverage exists.
- **Agentic research**: V7 agent-loop tape plants 16 redundant calls in 64 and requires quantified detection.
- **Long context**: Compression/trim savings must be holdback or replay measured and net of compression overhead.
- **Routing-safe tasks**: Routing/downshift claims require eval gates plus holdback or replay measurement.
- **General chat**: V7 high-variance tape requires no cache hits, no invented loops, and no painted savings.

## Calculator Contract

`benchmark_report.json` exposes `calculator.traffic_mix_sliders[]`. Each slider includes
`p25`, `p50`, and `p75` metrics for both `sdk_wrapper` and `sidecar`, so the Next.js
ROI calculator can combine workload-specific ranges rather than multiplying one flat
savings rate by total spend.

## Refresh Procedure

1. Run the full validation suite: `uv run python -m scripts.validate_engine --suite full`.
2. Refresh sidecar and SDK-wrapper overhead measurements from `scripts.load_benchmark` or production telemetry.
3. Regenerate this pack: `uv run python -m scripts.benchmark_proof --report-dir benchmark_reports`.
4. Publish only the current P25-P75 net range and keep estimates separate from verified savings.
