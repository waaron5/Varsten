# Engine Load Benchmark

Generated: 2026-07-21T16:26:21.350216+00:00

This benchmark drives a real local Varsten HTTP process against a local
OpenAI-compatible mock provider. It spends no provider tokens.

- Target RPS: `100`
- Scenario duration: `60.0s`
- Backend workers: `8`
- Backend DB pool: `pool_size=5`, `max_overflow=5`
- Detached capture: `enabled` (`max_concurrency=1`)
- Passthrough p99 gate: `<= +9.0ms` vs direct mock provider
- Gate result: `FAIL`

## Latency

| Scenario | Sent | Completed | Dropped | Achieved RPS | p50 | p95 | p99 | Added p99 vs direct | Errors | Non-2xx |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| direct_mock_provider | 6000 | 6000 | 0 | 100 | 7.0ms | 8.4ms | 11.9ms | +0.0ms | 0 | 0 |
| varsten_passthrough | 5986 | 5986 | 0 | 94 | 25.9ms | 1810.9ms | 3403.5ms | +3391.6ms | 0 | 0 |
| varsten_cache_hit | 6000 | 6000 | 0 | 100 | 8.7ms | 186.4ms | 443.3ms | +431.4ms | 0 | 0 |
| varsten_routed | 6000 | 6000 | 0 | 100 | 24.6ms | 38.6ms | 75.9ms | +64.0ms | 0 | 0 |

## DB Behavior

| Scenario | DB conns before | DB conns after | Active before | Active after | Usage before | Usage after | Cache before | Cache after |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| direct_mock_provider | 2 | 2 | 1 | 1 | 0 | 0 | 0 | 0 |
| varsten_passthrough | 28 | 45 | 1 | 1 | 0 | 5854 | 0 | 5853 |
| varsten_cache_hit | 45 | 46 | 1 | 2 | 131 | 3861 | 1 | 1 |
| varsten_routed | 45 | 45 | 1 | 1 | 0 | 5557 | 0 | 5555 |

## Header Counts

### direct_mock_provider
- No Varsten headers recorded.

### varsten_passthrough
- `cache:miss`: 5986
- `mode:optimize`: 5986

### varsten_cache_hit
- `cache:hit`: 6000
- `mode:optimize`: 6000

### varsten_routed
- `arm:treatment`: 6000
- `cache:miss`: 6000
- `mode:optimize`: 6000
- `routed:gpt-4o->gpt-4o-mini`: 6000

## Interpretation

- `direct_mock_provider` is the local upstream baseline.
- `varsten_passthrough` exercises auth, planning, ledger writes, and upstream forwarding without an active optimization policy.
- `varsten_cache_hit` exercises the exact-cache hot path after one priming request.
- `varsten_routed` exercises model-routing policy lookup, treatment assignment, ledger proof, and upstream forwarding.
